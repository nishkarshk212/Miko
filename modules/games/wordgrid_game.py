from __future__ import annotations

import os
import io
import re
import json
import random
import html
from typing import Dict, Any, Optional, List, Tuple
from PIL import Image, ImageDraw, ImageFont
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ContextTypes

from modules.utils.storage import update_user, get_user
from modules.utils.db import (
    save_active_wordgrid_game,
    get_active_wordgrid_game_db,
    delete_active_wordgrid_game_db,
    update_wordgrid_words_db,
    add_wordgrid_score,
)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(BASE_DIR, "assets", "wordseek")
FONT_BOLD_PATH = os.path.join(BASE_DIR, "assets", "fonts", "Roboto-Bold.ttf")
FONT_REGULAR_PATH = os.path.join(BASE_DIR, "assets", "fonts", "roboto.ttf")

COMMON_THREE = [
    "MOT", "CAT", "DOG", "SUN", "CAR", "DAY", "MAN", "BOY", "RED", "SKY",
    "SEA", "ICE", "CUP", "HAT", "PEN", "BOX", "FLY", "JAM", "MAP", "NUT",
    "PIG", "RUN", "WIN", "TOP", "FOX", "BAT", "BED", "BUS", "COW", "EGG",
    "EYE", "KEY", "LEG", "LIP", "NET", "OIL", "PAN", "PIE", "POT", "RAT",
    "ROW", "TAX", "TOY", "VAN", "WAR", "AIR", "ART", "ARM", "BAG", "BAR"
]

_WORD_LISTS: Dict[int, List[str]] = {}


def _load_words() -> None:
    global _WORD_LISTS
    if _WORD_LISTS:
        return

    _WORD_LISTS[3] = list(COMMON_THREE)

    mapping = {
        4: "common-four.json",
        5: "common-five.json",
        6: "common-six.json",
    }
    for length, filename in mapping.items():
        filepath = os.path.join(DATA_DIR, filename)
        words: List[str] = []
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    words = [w.strip().upper() for w in json.load(f) if len(w.strip()) == length]
            except Exception as e:
                print(f"Error loading {filename}: {e}")
        _WORD_LISTS[length] = words or list(COMMON_THREE)


DIRECTIONS = [
    (0, 1),   # Left to Right
    (1, 0),   # Top to Bottom
    (1, 1),   # Diagonal down-right
    (0, -1),  # Right to Left
    (-1, 0),  # Bottom to Top
    (-1, 1),  # Diagonal up-right
    (1, -1),  # Diagonal down-left
    (-1, -1), # Diagonal up-left
]


WORD_COLOR_PALETTE = [
    {"rgb": (34, 197, 94), "hex": "#22c55e"},   # Green
    {"rgb": (239, 68, 68), "hex": "#ef4444"},   # Red
    {"rgb": (234, 179, 8), "hex": "#eab308"},   # Yellow
    {"rgb": (59, 130, 246), "hex": "#3b82f6"},  # Blue
    {"rgb": (168, 85, 247), "hex": "#a855f7"},  # Purple
    {"rgb": (249, 115, 22), "hex": "#f97316"},  # Orange
    {"rgb": (6, 182, 212), "hex": "#06b6d4"},   # Cyan
    {"rgb": (236, 72, 153), "hex": "#ec4899"},  # Pink
]


def generate_word_grid(size: int = 8) -> Tuple[List[List[str]], Dict[str, Any]]:
    """
    Generates an 8x8 letter grid containing 8-10 hidden words of varying lengths:
    - 1 word of 3 letters
    - 4-5 words of 4 letters
    - 2 words of 5 letters
    - 1-2 words of 6 letters
    """
    _load_words()

    target_specs = [
        (3, 1),
        (4, 5),
        (5, 2),
        (6, 2),
    ]

    chosen_words: List[str] = []
    for length, count in target_specs:
        pool = list(_WORD_LISTS.get(length, []))
        if pool:
            random.shuffle(pool)
            chosen_words.extend(pool[:count])

    grid = [["" for _ in range(size)] for _ in range(size)]
    placed_words: Dict[str, Any] = {}

    for word in chosen_words:
        w_len = len(word)
        dir_choices = list(DIRECTIONS)
        random.shuffle(dir_choices)

        placed = False
        for _ in range(120):
            dr, dc = random.choice(dir_choices)
            r = random.randint(0, size - 1)
            c = random.randint(0, size - 1)

            end_r = r + dr * (w_len - 1)
            end_c = c + dc * (w_len - 1)

            if 0 <= end_r < size and 0 <= end_c < size:
                can_place = True
                coords: List[Tuple[int, int]] = []
                for i in range(w_len):
                    curr_r = r + dr * i
                    curr_c = c + dc * i
                    existing = grid[curr_r][curr_c]
                    if existing != "" and existing != word[i]:
                        can_place = False
                        break
                    coords.append((curr_r, curr_c))

                if can_place:
                    for i, (curr_r, curr_c) in enumerate(coords):
                        grid[curr_r][curr_c] = word[i]
                    color_idx = len(placed_words) % len(WORD_COLOR_PALETTE)
                    placed_words[word] = {
                        "positions": coords,
                        "found_by": None,
                        "found_by_name": None,
                        "color_idx": color_idx,
                    }
                    placed = True
                    break

    # Fill empty cells with random letters
    for r in range(size):
        for c in range(size):
            if grid[r][c] == "":
                grid[r][c] = chr(random.randint(65, 90))

    return grid, placed_words


def render_grid_image(
    grid: List[List[str]],
    found_positions: Optional[List[Tuple[int, int]]] = None,
    words_dict: Optional[Dict[str, Any]] = None,
) -> bytes:
    """Renders high-resolution dark grid image with multi-colored highlighter lines through found words."""
    size = len(grid)
    cell_size = 64
    padding = 24
    w = size * cell_size + padding * 2
    h = size * cell_size + padding * 2

    base = Image.new("RGBA", (w, h), color=(10, 12, 16, 255))
    draw_base = ImageDraw.Draw(base)

    # Outer rounded card border
    draw_base.rounded_rectangle(
        [padding - 8, padding - 8, w - padding + 8, h - padding + 8],
        radius=16,
        outline=(34, 38, 52, 255),
        width=3,
    )

    # Grid cell lines
    for r in range(size):
        for c in range(size):
            x1 = padding + c * cell_size
            y1 = padding + r * cell_size
            x2 = x1 + cell_size
            y2 = y1 + cell_size
            draw_base.rectangle([x1, y1, x2, y2], outline=(24, 27, 36, 255), width=1)

    # Highlighter lines overlay
    overlay = Image.new("RGBA", (w, h), color=(0, 0, 0, 0))
    draw_over = ImageDraw.Draw(overlay)

    capsule_w = 46
    radius = capsule_w // 2

    if words_dict:
        for word, info in words_dict.items():
            if not info.get("found_by"):
                continue
            positions = info.get("positions", [])
            if not positions:
                continue
            r0, c0 = positions[0]
            r1, c1 = positions[-1]
            c_idx = info.get("color_idx", 0) % len(WORD_COLOR_PALETTE)
            rgb = WORD_COLOR_PALETTE[c_idx]["rgb"]

            x0 = padding + c0 * cell_size + cell_size // 2
            y0 = padding + r0 * cell_size + cell_size // 2
            x1 = padding + c1 * cell_size + cell_size // 2
            y1 = padding + r1 * cell_size + cell_size // 2

            fill_rgba = (*rgb, 150)
            stroke_rgba = (*rgb, 230)

            # Draw capsule body & round caps
            draw_over.line([(x0, y0), (x1, y1)], fill=fill_rgba, width=capsule_w)
            draw_over.ellipse([x0 - radius, y0 - radius, x0 + radius, y0 + radius], fill=fill_rgba)
            draw_over.ellipse([x1 - radius, y1 - radius, x1 + radius, y1 + radius], fill=fill_rgba)

            # Draw crisp center line
            draw_over.line([(x0, y0), (x1, y1)], fill=stroke_rgba, width=4)
            draw_over.ellipse([x0 - 2, y0 - 2, x0 + 2, y0 + 2], fill=stroke_rgba)
            draw_over.ellipse([x1 - 2, y1 - 2, x1 + 2, y1 + 2], fill=stroke_rgba)

    # Composite overlay over base
    combined = Image.alpha_composite(base, overlay)
    draw_final = ImageDraw.Draw(combined)

    # Load crisp bold font
    font = None
    if os.path.exists(FONT_BOLD_PATH):
        try:
            font = ImageFont.truetype(FONT_BOLD_PATH, 30)
        except Exception:
            pass
    if not font and os.path.exists(FONT_REGULAR_PATH):
        try:
            font = ImageFont.truetype(FONT_REGULAR_PATH, 30)
        except Exception:
            pass
    if not font:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
        except Exception:
            font = ImageFont.load_default()

    # Draw letters in crisp white on top of lines
    for r in range(size):
        for c in range(size):
            letter = grid[r][c].upper()
            bbox = draw_final.textbbox((0, 0), letter, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            x1 = padding + c * cell_size
            y1 = padding + r * cell_size
            tx = x1 + (cell_size - tw) / 2
            ty = y1 + (cell_size - th) / 2 - 2
            draw_final.text((tx, ty), letter, fill=(255, 255, 255, 255), font=font)

    buf = io.BytesIO()
    combined.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def build_caption(words_dict: Dict[str, Any], is_completed: bool = False) -> str:
    """Builds the challenge caption with clean text without color emojis."""
    sorted_words = sorted(words_dict.items(), key=lambda x: (len(x[0]), x[0]))

    clue_lines: List[str] = []
    found_count = 0
    total_count = len(sorted_words)

    for word, info in sorted_words:
        w_len = len(word)
        if info.get("found_by"):
            found_count += 1
            u_name = info.get("found_by_name", "User")
            clue_lines.append(f"<s><b>{word}</b></s> ({w_len}) • {html.escape(u_name)}")
        else:
            clue = word[0] + "-" * (w_len - 1)
            clue_lines.append(f"<b>{clue}</b> ({w_len})")

    clues_text = "\n".join(clue_lines)

    if is_completed:
        # Build round summary
        finders: Dict[str, int] = {}
        for _, info in words_dict.items():
            if info.get("found_by_name"):
                name = info["found_by_name"]
                finders[name] = finders.get(name, 0) + 1

        leaderboard_lines = []
        medals = ["🥇", "🥈", "🥉"]
        sorted_finders = sorted(finders.items(), key=lambda x: x[1], reverse=True)
        for i, (name, count) in enumerate(sorted_finders):
            medal = medals[i] if i < len(medals) else "🎖️"
            leaderboard_lines.append(f"{medal} <b>{html.escape(name)}</b>: {count} words (+{count * 25} 💰)")

        lb_text = "\n".join(leaderboard_lines) if leaderboard_lines else "None"

        return (
            "🎉 <b>WORD GRID CHALLENGE COMPLETED!</b> 🎉\n\n"
            f"<b>🏆 Top Word Hunters:</b>\n{lb_text}\n\n"
            "Start a new challenge with /wordgrid"
        )

    return (
        "🔲 <b>WORD GRID CHALLENGE</b> 🔲\n\n"
        f"<b>Find these words ({found_count}/{total_count}):</b>\n"
        f"{clues_text}\n\n"
        "Tap 🔄 <b>Refresh Grid to mark!</b>"
    )


def build_keyboard(chat_id: int, thread_id: Optional[int] = None) -> InlineKeyboardMarkup:
    t_key = f"{chat_id}_{thread_id}" if thread_id else str(chat_id)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Refresh Grid", callback_data=f"wg_refresh:{t_key}"),
            InlineKeyboardButton("End Game", callback_data=f"wg_end:{t_key}"),
        ]
    ])


# Active in-memory cache: {key: game_dict}
ACTIVE_WORDGRIDS: Dict[str, Dict[str, Any]] = {}


def _get_grid_key(chat_id: int, thread_id: Optional[int] = None) -> str:
    return f"{chat_id}_{thread_id}" if thread_id else str(chat_id)


def get_active_grid_game(chat_id: int, thread_id: Optional[int] = None) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    key = _get_grid_key(chat_id, thread_id)
    if key in ACTIVE_WORDGRIDS:
        return key, ACTIVE_WORDGRIDS[key]
    fallback_key = str(chat_id)
    if fallback_key in ACTIVE_WORDGRIDS:
        return fallback_key, ACTIVE_WORDGRIDS[fallback_key]

    # Check SQLite DB
    db_game = get_active_wordgrid_game_db(chat_id, thread_id)
    if db_game:
        ACTIVE_WORDGRIDS[key] = db_game
        ACTIVE_WORDGRIDS[str(chat_id)] = db_game
        return key, db_game

    return None, None


def remove_active_grid_game(chat_id: int, thread_id: Optional[int] = None) -> None:
    key = _get_grid_key(chat_id, thread_id)
    ACTIVE_WORDGRIDS.pop(key, None)
    ACTIVE_WORDGRIDS.pop(str(chat_id), None)
    delete_active_wordgrid_game_db(chat_id, thread_id)


async def cmd_wordgrid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts a new Word Grid Challenge in the chat."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    chat_id = chat.id
    thread_id = getattr(update.effective_message, "message_thread_id", None)

    _, existing = get_active_grid_game(chat_id, thread_id)
    if existing:
        await update.message.reply_text(
            "⚠️ There is already an active Word Grid challenge in this chat! Use /endgrid to stop it.",
            auto_delete=False,
        )
        return

    # Generate grid and words
    grid, words = generate_word_grid(size=8)
    image_bytes = render_grid_image(grid)
    caption = build_caption(words, is_completed=False)
    keyboard = build_keyboard(chat_id, thread_id)

    sent_msg = await chat.send_photo(
        photo=io.BytesIO(image_bytes),
        filename="wordgrid.png",
        caption=caption,
        parse_mode="HTML",
        reply_markup=keyboard,
        message_thread_id=thread_id if chat.is_forum else None,
    )

    key = _get_grid_key(chat_id, thread_id)
    game_data = {
        "grid": grid,
        "words": words,
        "message_id": sent_msg.message_id,
        "started_by": user.id,
        "started_by_name": user.first_name or "User",
        "chat_id": chat_id,
        "thread_id": thread_id,
    }

    ACTIVE_WORDGRIDS[key] = game_data
    ACTIVE_WORDGRIDS[str(chat_id)] = game_data
    save_active_wordgrid_game(chat_id, thread_id, game_data)


async def cmd_endgrid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ends the active Word Grid Challenge."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    chat_id = chat.id
    thread_id = getattr(update.effective_message, "message_thread_id", None)
    _, game = get_active_grid_game(chat_id, thread_id)
    if not game:
        await update.message.reply_text("No active Word Grid game in this chat. Start one with /wordgrid")
        return

    is_private = chat.type == "private"
    is_starter = user.id == game["started_by"]
    is_admin = False

    if not is_private and not is_starter:
        try:
            member = await chat.get_member(user.id)
            is_admin = member.status in ("creator", "administrator")
        except Exception:
            is_admin = False

    if not (is_private or is_starter or is_admin):
        await update.message.reply_text("Only the game starter or group administrators can end the game.")
        return

    remove_active_grid_game(chat_id, thread_id)

    # Reveal all words
    unfound_words = [w for w, info in game["words"].items() if not info.get("found_by")]
    revealed_text = ", ".join(unfound_words) if unfound_words else "All words were found!"

    await update.message.reply_text(
        f"🛑 <b>Word Grid Challenge Ended!</b>\n\n"
        f"<b>Unfound words:</b> <code>{revealed_text}</code>\n\n"
        "Start a new challenge with /wordgrid",
        parse_mode="HTML",
        auto_delete=False,
    )


async def check_wordgrid_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Intercepts chat messages to detect found words in the active Word Grid."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return False

    raw_text = (msg.text or "").strip()
    if not raw_text or raw_text.startswith("/"):
        return False

    chat_id = chat.id
    thread_id = getattr(msg, "message_thread_id", None)
    key, game = get_active_grid_game(chat_id, thread_id)
    if not game:
        return False

    guess = re.sub(r"[^a-zA-Z]", "", raw_text).upper()
    if not guess or len(guess) < 3 or len(guess) > 8:
        return False

    words = game["words"]
    if guess in words:
        info = words[guess]
        if info.get("found_by"):
            # Already found
            return False

        from modules.utils.anonymous_admin import (
            resolve_player_identity,
            record_pending_anon_score,
            build_anon_verification_prompt,
        )

        eff_user_id, eff_name, eff_uname, is_unlinked_anon = resolve_player_identity(chat_id, msg, user)

        # Mark as found
        info["found_by"] = eff_user_id
        info["found_by_name"] = eff_name
        info["found_by_username"] = eff_uname

        points = len(guess)
        if is_unlinked_anon:
            record_pending_anon_score(chat_id, points, "wordgrid", guess)
        else:
            # Award rewards (points in gems, plus coins & xp)
            try:
                ud = get_user(eff_user_id)
                new_bal = ud.get("balance", 0) + points * 10
                new_gems = ud.get("gems", 0.0) + points
                new_xp = ud.get("xp", 0) + points * 5
                update_user(eff_user_id, balance=new_bal, gems=new_gems, xp=new_xp)
            except Exception as e:
                print(f"Error awarding wordgrid points: {e}")

            try:
                add_wordgrid_score(eff_user_id, chat_id, eff_name, eff_uname, points, guess)
            except Exception as e:
                print(f"Error saving wordgrid leaderboard score: {e}")

        # Update in DB
        update_wordgrid_words_db(chat_id, thread_id, words)

        # Check if all words are found
        all_found = all(bool(w_info.get("found_by")) for w_info in words.values())

        # Auto-refresh the main grid image and caption immediately with multi-colored found words
        if game.get("message_id"):
            try:
                updated_image = render_grid_image(game["grid"], words_dict=words)
                updated_caption = build_caption(words, is_completed=all_found)
                grid_kb = build_keyboard(chat_id, thread_id) if not all_found else None

                await context.bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=game["message_id"],
                    media=InputMediaPhoto(media=io.BytesIO(updated_image), filename="wordgrid.png", caption=updated_caption, parse_mode="HTML"),
                    reply_markup=grid_kb,
                )
            except Exception as e:
                print(f"Error auto-refreshing grid photo: {e}")

        # Deep link to jump directly to the grid message
        if chat.username:
            grid_url = f"https://t.me/{chat.username}/{game['message_id']}"
        else:
            clean_cid = str(chat_id).replace("-100", "").replace("-", "")
            grid_url = f"https://t.me/c/{clean_cid}/{game['message_id']}"

        reply_buttons = [
            [InlineKeyboardButton("Go to Grid", url=grid_url)]
        ]

        # Add verification button if playing as unlinked anonymous admin
        anon_notice = ""
        if is_unlinked_anon:
            clean_bot = (context.bot.username if context.bot else None) or "im_Radhabot"
            _, anon_kb = build_anon_verification_prompt(clean_bot, chat_id)
            reply_buttons.append(anon_kb.inline_keyboard[0])
            anon_notice = (
                "\n\n🕵️ <i>Anonymous Admin: Tap below or reply with</i> <code>/anonid YOUR_ID</code> <i>to store your score!</i>"
            )

        reply_kb = InlineKeyboardMarkup(reply_buttons)

        user_tag = (
            f'<a href="tg://user?id={eff_user_id}">{html.escape(eff_name)}</a>'
            if isinstance(eff_user_id, int) and eff_user_id != 1087968824
            else f"<b>{html.escape(eff_name)}</b>"
        )

        unlock_text = (
            f"💎 <b>WORD UNLOCKED!</b>\n\n"
            f"👤 {user_tag}\n\n"
            f"<b>WORD: {guess}</b>\n"
            f"<b>POINTS: +{points} 💎</b>\n\n"
            f"◽ <i>Added to your score!</i>{anon_notice}"
        )

        await msg.reply_text(
            unlock_text,
            parse_mode="HTML",
            reply_markup=reply_kb,
            auto_delete=False,
        )

        if all_found:
            remove_active_grid_game(chat_id, thread_id)
            final_caption = build_caption(words, is_completed=True)
            await chat.send_message(
                f"🎉 <b>Word Grid Challenge Completed!</b>\n\n{final_caption}",
                parse_mode="HTML",
                message_thread_id=thread_id if chat.is_forum else None,
                auto_delete=False,
            )

        return True

    return False


async def wordgrid_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handles '🔄 Refresh Grid' and '❌ End Game' inline button clicks."""
    query = update.callback_query
    if not query or not query.data:
        return False

    data = query.data
    if not (data.startswith("wg_refresh:") or data.startswith("wg_end:")):
        return False

    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return False

    chat_id = chat.id
    thread_id = getattr(update.effective_message, "message_thread_id", None)
    key, game = get_active_grid_game(chat_id, thread_id)

    if data.startswith("wg_refresh:"):
        if not game:
            await query.answer("No active challenge found. Start one with /wordgrid", show_alert=True)
            return True

        updated_image = render_grid_image(game["grid"], words_dict=game["words"])
        updated_caption = build_caption(game["words"], is_completed=False)
        keyboard = build_keyboard(chat_id, thread_id)

        try:
            await query.edit_message_media(
                media=InputMediaPhoto(media=io.BytesIO(updated_image), filename="wordgrid.png", caption=updated_caption, parse_mode="HTML"),
                reply_markup=keyboard,
            )
            found_count = sum(1 for w in game["words"].values() if w.get("found_by"))
            total_count = len(game["words"])
            await query.answer(f"🔄 Grid refreshed! ({found_count}/{total_count} words found)", show_alert=False)
        except Exception as e:
            await query.answer(f"Already up to date!", show_alert=False)

        return True

    elif data.startswith("wg_end:"):
        if not game:
            await query.answer("Game already ended.", show_alert=True)
            return True

        is_private = chat.type == "private"
        is_starter = user.id == game["started_by"]
        is_admin = False

        if not is_private and not is_starter:
            try:
                member = await chat.get_member(user.id)
                is_admin = member.status in ("creator", "administrator")
            except Exception:
                is_admin = False

        if not (is_private or is_starter or is_admin):
            await query.answer("Only the starter or an admin can end the challenge.", show_alert=True)
            return True

        remove_active_grid_game(chat_id, thread_id)

        unfound_words = [w for w, info in game["words"].items() if not info.get("found_by")]
        revealed_text = ", ".join(unfound_words) if unfound_words else "All words were found!"

        try:
            await query.edit_message_caption(
                caption=(
                    f"🛑 <b>Word Grid Challenge Ended!</b>\n\n"
                    f"<b>Unfound words:</b> <code>{revealed_text}</code>\n\n"
                    "Start a new challenge with /wordgrid"
                ),
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            pass

        await query.answer("Challenge ended.", show_alert=False)
        return True

    return False
