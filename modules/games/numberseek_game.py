from __future__ import annotations

import re
import html
import random
from typing import Dict, Any, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from modules.utils.storage import update_user, get_user
from modules.utils.db import (
    save_active_numberseek_game,
    get_active_numberseek_game_db,
    delete_active_numberseek_game_db,
    update_numberseek_guesses_db,
    add_numberseek_score,
)

# Active in-memory games: {chat_id or "chat_thread": game_dict}
ACTIVE_NUMBERSEEK_GAMES: Dict[Any, Dict[str, Any]] = {}


def _game_keys(chat_id: int, thread_id: Optional[int] = None) -> List[Any]:
    keys = []
    if thread_id:
        keys.append(f"{chat_id}_{thread_id}")
    keys.append(str(chat_id))
    keys.append(chat_id)
    return keys


def get_active_game(chat_id: int, thread_id: Optional[int] = None) -> tuple[Optional[Any], Optional[Dict[str, Any]]]:
    for k in _game_keys(chat_id, thread_id):
        if k in ACTIVE_NUMBERSEEK_GAMES:
            return k, ACTIVE_NUMBERSEEK_GAMES[k]

    # Fallback to persistent SQLite DB
    db_game = get_active_numberseek_game_db(chat_id, thread_id)
    if db_game:
        primary_key = f"{chat_id}_{thread_id}" if thread_id else chat_id
        ACTIVE_NUMBERSEEK_GAMES[primary_key] = db_game
        ACTIVE_NUMBERSEEK_GAMES[chat_id] = db_game
        ACTIVE_NUMBERSEEK_GAMES[str(chat_id)] = db_game
        return primary_key, db_game

    return None, None


def remove_active_game(chat_id: int, thread_id: Optional[int] = None) -> None:
    for k in _game_keys(chat_id, thread_id):
        ACTIVE_NUMBERSEEK_GAMES.pop(k, None)
    delete_active_numberseek_game_db(chat_id, thread_id)


BUTTON_STYLE = {
    "correct": "success",
    "present": "primary",
    "absent": "danger",
    "untouched": "primary",
}

ZERO_WIDTH = [
    "\u200B",  # zero width space
    "\u200C",  # zero width non-joiner
    "\u200D",  # zero width joiner
    "\u2060",  # word joiner
    "\uFEFF",  # zero width no-break space
]


def zero_width_noise(min_c: int = 1, max_c: int = 6) -> str:
    count = random.randint(min_c, max_c)
    return "".join(random.choice(ZERO_WIDTH) for _ in range(count))


def generate_secret_number(length: int = 5) -> str:
    """Generates a random sequence of N digits (0-9)."""
    return "".join(str(random.randint(0, 9)) for _ in range(length))


def evaluate_number_guess(guess: str, solution: str) -> List[str]:
    """
    Evaluates guess against solution:
    Returns list of states: 'correct', 'present', 'absent'
    """
    remaining: Dict[str, int] = {}
    for d in solution:
        remaining[d] = remaining.get(d, 0) + 1

    result = ["absent"] * len(guess)

    # 1. Exact matches (green / success)
    for i in range(len(guess)):
        if guess[i] == solution[i]:
            result[i] = "correct"
            remaining[guess[i]] -= 1

    # 2. Present matches (blue / wrong position)
    for i in range(len(guess)):
        if result[i] == "absent" and remaining.get(guess[i], 0) > 0:
            result[i] = "present"
            remaining[guess[i]] -= 1

    return result


def get_digit_statuses(guesses: List[str], solution: str) -> Dict[str, str]:
    """Computes the status of digits 0-9 across all guesses."""
    status: Dict[str, str] = {str(d): "untouched" for d in range(10)}
    for g in guesses:
        evals = evaluate_number_guess(g, solution)
        for d, state in zip(g, evals):
            if d not in solution:
                status[d] = "absent"
            else:
                curr = status[d]
                if state == "correct":
                    status[d] = "correct"
                elif curr != "correct":
                    status[d] = "present"
    return status


def render_guess_row(guess: str, solution: str) -> str:
    states = evaluate_number_guess(guess, solution)
    buttons = []
    for i, digit in enumerate(guess):
        state = states[i]
        style = BUTTON_STYLE[state]
        buttons.append(
            f'<tg-button type="callback_data" style="{style}" data="ns:{state}:{digit}">{digit}</tg-button>'
        )
    return f"<p>{''.join(buttons)}</p>"


def build_rich_feedback(guesses: List[str], solution: str, length: int) -> str:
    """Builds full rich HTML matching Number Seek layout with guess rows."""
    guess_rows = "".join(render_guess_row(g, solution) for g in guesses)
    return f"<h3>Number Seek</h3><p><i>{len(guesses)}/30 guesses</i></p>{guess_rows}"


async def reply_rich_message(
    bot,
    chat_id: int,
    html_content: str,
    thread_id: Optional[int] = None,
    reply_to_message_id: Optional[int] = None,
):
    """Sends Telegram RichMessage with tg-button HTML elements."""
    data = {
        "chat_id": chat_id,
        "rich_message": {"html": html_content},
    }
    if thread_id:
        data["message_thread_id"] = thread_id
    if reply_to_message_id:
        data["reply_parameters"] = {"message_id": reply_to_message_id}
    try:
        return await bot._post("sendRichMessage", data=data)
    except Exception as e:
        if reply_to_message_id:
            data.pop("reply_parameters", None)
            try:
                return await bot._post("sendRichMessage", data=data)
            except Exception:
                pass
        if thread_id:
            data.pop("message_thread_id", None)
            return await bot._post("sendRichMessage", data=data)
        raise e


def render_guess_row_text(guess: str, solution: str) -> str:
    states = evaluate_number_guess(guess, solution)
    symbols = {"correct": "🟩", "present": "🟦", "absent": "🟥"}
    tiles = []
    for i, ch in enumerate(guess):
        tiles.append(f"{symbols[states[i]]} {ch}")
    return "  ".join(tiles)


def build_guess_buttons(guesses: List[str], solution: str) -> List[List[InlineKeyboardButton]]:
    """Builds inline keyboard digit tiles for latest guess."""
    if not guesses:
        return []
    latest_guess = guesses[-1]
    states = evaluate_number_guess(latest_guess, solution)
    row = []
    for i, ch in enumerate(latest_guess):
        state = states[i]
        btn_style = "success" if state == "correct" else ("danger" if state == "absent" else "primary")
        row.append(
            InlineKeyboardButton(
                text=ch,
                callback_data=f"ns:{state}:{ch}",
                api_kwargs={"style": btn_style},
            )
        )
    return [row]


async def start_numberseek_game(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    forced_length: Optional[int] = None,
):
    """Starts a new Number Seek game in the current chat."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    chat_id = chat.id
    thread_id = getattr(update.effective_message, "message_thread_id", None)

    _, existing = get_active_game(chat_id, thread_id)
    if existing:
        await update.message.reply_text(
            "There is already a Number Seek game in progress in this chat. Use /endnum to end the current game.",
            auto_delete=False,
        )
        return

    num_length = 5
    if forced_length in (4, 5, 6):
        num_length = forced_length
    elif context.args and len(context.args) > 0:
        arg = context.args[0].strip()
        if arg.isdigit() and int(arg) in (4, 5, 6):
            num_length = int(arg)

    secret_number = generate_secret_number(num_length)

    primary_key = f"{chat_id}_{thread_id}" if thread_id else chat_id
    ACTIVE_NUMBERSEEK_GAMES[primary_key] = {
        "number": secret_number,
        "length": num_length,
        "started_by": user.id,
        "started_by_name": user.first_name or "User",
        "guesses": [],
        "chat_id": chat_id,
        "thread_id": thread_id,
    }
    ACTIVE_NUMBERSEEK_GAMES[chat_id] = ACTIVE_NUMBERSEEK_GAMES[primary_key]
    ACTIVE_NUMBERSEEK_GAMES[str(chat_id)] = ACTIVE_NUMBERSEEK_GAMES[primary_key]
    save_active_numberseek_game(chat_id, thread_id, ACTIVE_NUMBERSEEK_GAMES[primary_key])

    await update.message.reply_text(
        f"Number Seek Game started! Guess the {num_length}-digit number!",
        auto_delete=False,
    )


async def cmd_num(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /num [4|5|6]"""
    await start_numberseek_game(update, context)


async def cmd_num4(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /num4"""
    await start_numberseek_game(update, context, forced_length=4)


async def cmd_num5(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /num5"""
    await start_numberseek_game(update, context, forced_length=5)


async def cmd_num6(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /num6"""
    await start_numberseek_game(update, context, forced_length=6)


async def cmd_endnum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /endnum - End the current active Number Seek game."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    chat_id = chat.id
    thread_id = getattr(update.effective_message, "message_thread_id", None)
    _, game = get_active_game(chat_id, thread_id)
    if not game:
        await update.message.reply_text("There is no Number Seek game in progress.")
        return

    number = game["number"]
    num_length = game["length"]

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
        await update.message.reply_text("Only group administrators or the game starter can end the game.")
        return

    remove_active_game(chat_id, thread_id)

    user_name = html.escape(user.first_name or "User")
    user_link = f'<a href="tg://user?id={user.id}">{user_name}</a>'

    if is_private:
        reason = ""
    elif is_starter:
        reason = f"<b>Ended by game starter: </b>{user_link}\n"
    elif is_admin:
        reason = f"<b>Ended by group administrator: </b>{user_link}\n"
    else:
        reason = f"<b>Ended by: </b>{user_link}\n"

    msg = (
        f"<blockquote>🎮 <b>Number Seek Ended</b>\n"
        f"Correct Number: <b>{number}</b></blockquote>\n"
        f"<blockquote>{reason}Start a new game with /num{num_length}</blockquote>"
    )

    await update.message.reply_text(msg, parse_mode="HTML", auto_delete=False)


async def check_numberseek_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Message watcher for Number Seek guesses.
    Detects numeric guesses matching the current game's length.
    """
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
    game_key, game = get_active_game(chat_id, thread_id)
    if not game:
        return False

    num_length = game["length"]

    # Match pure digits
    clean_guess = re.sub(r"[^\d]", "", raw_text)
    if not clean_guess or len(clean_guess) != num_length:
        return False

    # Check if already guessed
    if clean_guess in game["guesses"]:
        await msg.reply_text("Someone has already guessed this number. Please try another one!")
        return True

    # Check WIN condition
    if clean_guess == game["number"]:
        all_guesses = game["guesses"]
        score = 30 - len(all_guesses)

        from modules.utils.anonymous_admin import (
            resolve_player_identity,
            record_pending_anon_score,
            build_anon_verification_prompt,
        )

        eff_user_id, eff_name, eff_uname, is_unlinked_anon = resolve_player_identity(chat.id, msg, user)
        reply_markup = None

        if is_unlinked_anon:
            record_pending_anon_score(chat.id, score, "numberseek", clean_guess)
            clean_bot = (context.bot.username if context.bot else None) or "im_Radhabot"
            _, anon_kb = build_anon_verification_prompt(clean_bot, chat.id)
            reply_markup = anon_kb
            additional_message = (
                f"You scored {score} points!\n"
                f"🕵️ <i>Anonymous Admin: Tap below or reply with</i> <code>/anonid YOUR_ID</code> <i>to store your score on the leaderboard!</i>"
            )
        else:
            additional_message = f"Added {score} to the leaderboard."
            try:
                ud = get_user(eff_user_id)
                new_bal = ud.get("balance", 0) + score * 10
                new_gems = ud.get("gems", 0.0) + score
                new_xp = ud.get("xp", 0) + score * 5
                update_user(eff_user_id, balance=new_bal, gems=new_gems, xp=new_xp)
            except Exception as e:
                print(f"Error awarding numberseek balance: {e}")

            add_numberseek_score(eff_user_id, chat.id, eff_name, eff_uname, score, num_length)

        formatted_response = (
            f"<blockquote><strong>🎉 Congratulations!</strong>\n"
            f"Correct Number: <b>{clean_guess}</b>\n"
            f"Guesses: <b>{len(all_guesses) + 1}/30</b>\n"
            f"{additional_message}</blockquote>\n"
            f"Start with /num{num_length}"
        )

        remove_active_game(chat_id, thread_id)

        await msg.reply_text(
            formatted_response,
            parse_mode="HTML",
            reply_markup=reply_markup,
            auto_delete=False,
        )

        try:
            await msg.set_reaction("🎉")
        except Exception:
            pass

        return True

    # Register guess
    game["guesses"].append(clean_guess)
    all_guesses = game["guesses"]
    update_numberseek_guesses_db(chat_id, thread_id, all_guesses)

    # Check if max guesses (30) reached
    if len(all_guesses) >= 30:
        sol = game["number"]
        remove_active_game(chat_id, thread_id)
        await msg.reply_text(
            f"Game Over! The correct number was {sol}\nYou can start a new game with /num{num_length}",
            auto_delete=False,
        )
        return True

    # Format feedback using Number Seek rich HTML
    rich_html = build_rich_feedback(all_guesses, game["number"], num_length)

    try:
        await reply_rich_message(
            context.bot,
            chat.id,
            rich_html,
            thread_id=thread_id,
            reply_to_message_id=msg.message_id,
        )
    except Exception as e:
        print(f"sendRichMessage failed for NumberSeek, fallback to text: {e}")
        rows_text = [render_guess_row_text(g, game["number"]) for g in all_guesses[-6:]]
        board_display = "\n".join(rows_text)
        feedback_text = (
            f"<b>Number Seek</b>\n"
            f"<i>{len(all_guesses)}/30 guesses</i>\n\n"
            f"{board_display}"
        )
        buttons = build_guess_buttons(all_guesses, game["number"])
        reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
        await msg.reply_text(
            feedback_text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            auto_delete=False,
        )
    return True


async def numberseek_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handles ns: and ns_k: callback queries from Number Seek buttons."""
    query = update.callback_query
    if not query or not query.data:
        return False

    data = query.data
    if data.startswith("ns_k:"):
        digit = data.split(":")[1]
        await query.answer(f"Digit: {digit}", show_alert=False)
        return True

    if data.startswith("ns:"):
        parts = data.split(":")
        if len(parts) >= 3:
            state = parts[1]
            digit = parts[2]
            state_text = {
                "correct": "Correct position (Green)",
                "present": "Present in number, wrong position (Blue)",
                "absent": "Not in number (Red)",
            }.get(state, state)
            await query.answer(f"{digit}: {state_text}", show_alert=False)
            return True

    return False
