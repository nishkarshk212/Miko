from __future__ import annotations

import os
import re
import json
import random
import html
from typing import Dict, Any, Optional, List, Set
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from modules.utils.db import (
    add_wordseek_score,
    get_wordseek_leaderboard,
    get_wordseek_user_score,
    save_active_wordseek_game,
    get_active_wordseek_game_db,
    delete_active_wordseek_game_db,
    update_wordseek_guesses_db,
)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(BASE_DIR, "assets", "wordseek")

# Word lists cache
_ALL_WORDS: Dict[int, Set[str]] = {}
_COMMON_WORDS: Dict[int, List[str]] = {}

MODE_LABEL: Dict[int, str] = {
    4: "4-letter mode",
    5: "5-letter mode",
    6: "6-letter mode",
}

REACTION_EMOJIS = ["🎉", "🏆", "🤩", "⚡", "🫡", "💯", "❤‍🔥", "🦄"]

HINTS: Dict[str, str] = {
    "correct": '🟩 "{letter}" is in the word and in the right spot.',
    "present": '🟨 "{letter}" is in the word, but in a different spot.',
    "absent": '🟥 "{letter}" isn\'t in the word.',
}


def _load_word_lists():
    global _ALL_WORDS, _COMMON_WORDS
    if _ALL_WORDS and _COMMON_WORDS:
        return

    mapping = {
        4: ("all-four.json", "common-four.json"),
        5: ("all-five.json", "common-five.json"),
        6: ("all-six.json", "common-six.json"),
    }

    for length, (all_file, common_file) in mapping.items():
        all_path = os.path.join(DATA_DIR, all_file)
        common_path = os.path.join(DATA_DIR, common_file)

        all_words: Set[str] = set()
        common_words: List[str] = []

        if os.path.exists(all_path):
            try:
                with open(all_path, "r", encoding="utf-8") as f:
                    all_words = {w.strip().lower() for w in json.load(f)}
            except Exception as e:
                print(f"Error loading {all_file}: {e}")

        if os.path.exists(common_path):
            try:
                with open(common_path, "r", encoding="utf-8") as f:
                    common_words = [w.strip().lower() for w in json.load(f)]
            except Exception as e:
                print(f"Error loading {common_file}: {e}")

        if not common_words and all_words:
            common_words = list(all_words)

        _ALL_WORDS[length] = all_words
        _COMMON_WORDS[length] = common_words


# Active in-memory games: {chat_id or "chat_thread": game_dict}
ACTIVE_WORDSEEK_GAMES: Dict[Any, Dict[str, Any]] = {}


def _game_keys(chat_id: int, thread_id: Optional[int] = None) -> List[Any]:
    keys = []
    if thread_id:
        keys.append(f"{chat_id}_{thread_id}")
    keys.append(str(chat_id))
    keys.append(chat_id)
    return keys


def get_active_game(chat_id: int, thread_id: Optional[int] = None) -> tuple[Optional[Any], Optional[Dict[str, Any]]]:
    for k in _game_keys(chat_id, thread_id):
        if k in ACTIVE_WORDSEEK_GAMES:
            return k, ACTIVE_WORDSEEK_GAMES[k]

    # Fallback to persistent SQLite DB
    db_game = get_active_wordseek_game_db(chat_id, thread_id)
    if db_game:
        primary_key = f"{chat_id}_{thread_id}" if thread_id else chat_id
        ACTIVE_WORDSEEK_GAMES[primary_key] = db_game
        ACTIVE_WORDSEEK_GAMES[chat_id] = db_game
        ACTIVE_WORDSEEK_GAMES[str(chat_id)] = db_game
        return primary_key, db_game

    return None, None


def remove_active_game(chat_id: int, thread_id: Optional[int] = None) -> None:
    for k in _game_keys(chat_id, thread_id):
        ACTIVE_WORDSEEK_GAMES.pop(k, None)
    delete_active_wordseek_game_db(chat_id, thread_id)


BUTTON_STYLE = {
    "correct": "success",
    "present": None,
    "absent": "danger",
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


def evaluate_guess(guess: str, solution: str) -> List[str]:
    """
    Exact word evaluation from original WordSeek:
    Returns list of states: 'correct', 'present', 'absent'
    """
    g = guess.lower()
    s = solution.lower()

    remaining: Dict[str, int] = {}
    for c in s:
        remaining[c] = remaining.get(c, 0) + 1

    result = ["absent"] * len(g)

    # 1. Exact matches (green)
    for i in range(len(g)):
        if g[i] == s[i]:
            result[i] = "correct"
            remaining[g[i]] -= 1

    # 2. Present matches (yellow)
    for i in range(len(g)):
        if result[i] == "absent" and remaining.get(g[i], 0) > 0:
            result[i] = "present"
            remaining[g[i]] -= 1

    return result


def render_guess_row(guess: str, solution: str) -> str:
    states = evaluate_guess(guess, solution)
    buttons = []
    for i, letter in enumerate(guess.upper()):
        state = states[i]
        style = BUTTON_STYLE[state]
        style_attr = f' style="{style}"' if style else ""
        label = f"{zero_width_noise()}{letter}{zero_width_noise()}"
        buttons.append(f'<tg-button type="callback_data"{style_attr} data="wh:{state}:{letter}">{label}</tg-button>')
    return f"<p>{''.join(buttons)}</p>"


def build_rich_feedback(guesses: List[str], solution: str, mode_label: str) -> str:
    rows = "".join(render_guess_row(g, solution) for g in guesses)
    return f"<h3>{mode_label}</h3><p><i>{len(guesses)}/30 guesses</i></p>{rows}"


async def reply_rich_message(bot, chat_id: int, html_content: str, thread_id: Optional[int] = None):
    """Sends Telegram RichMessage with tg-button HTML elements."""
    data = {
        "chat_id": chat_id,
        "rich_message": {"html": html_content},
    }
    if thread_id:
        data["message_thread_id"] = thread_id
    try:
        return await bot._post("sendRichMessage", data=data)
    except Exception as e:
        if thread_id:
            data.pop("message_thread_id", None)
            return await bot._post("sendRichMessage", data=data)
        raise e


def render_guess_row_text(guess: str, solution: str) -> str:
    states = evaluate_guess(guess, solution)
    symbols = {"correct": "🟩", "present": "🟨", "absent": "⬛"}
    tiles = []
    for i, ch in enumerate(guess.upper()):
        tiles.append(f"{symbols[states[i]]} {ch}")
    return "  ".join(tiles)


def build_guess_buttons(guesses: List[str], solution: str) -> List[List[InlineKeyboardButton]]:
    """Builds inline keyboard letter tiles for latest guesses with wh:{state}:{letter} callback."""
    if not guesses:
        return []
    latest_guess = guesses[-1]
    states = evaluate_guess(latest_guess, solution)
    row = []
    for i, ch in enumerate(latest_guess.upper()):
        state = states[i]
        btn_style = "success" if state == "correct" else ("danger" if state == "absent" else "primary")
        row.append(
            InlineKeyboardButton(
                text=ch,
                callback_data=f"wh:{state}:{ch}",
                api_kwargs={"style": btn_style},
            )
        )
    return [row]


async def start_game(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    forced_length: Optional[int] = None,
):
    """Starts a new WordSeek game in the current chat."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    _load_word_lists()
    chat_id = chat.id
    thread_id = getattr(update.effective_message, "message_thread_id", None)

    _, existing = get_active_game(chat_id, thread_id)
    if existing:
        await update.message.reply_text(
            "There is already a game in progress in this chat. Use /end to end the current game.",
            auto_delete=False,
        )
        return

    word_length = 5
    if forced_length in (4, 5, 6):
        word_length = forced_length
    elif context.args and len(context.args) > 0:
        arg = context.args[0].strip()
        if arg.isdigit() and int(arg) in (4, 5, 6):
            word_length = int(arg)

    pool = _COMMON_WORDS.get(word_length) or list(_ALL_WORDS.get(word_length, []))
    if not pool:
        await update.message.reply_text("Something went wrong. Please try again.")
        return

    secret_word = random.choice(pool).lower()

    primary_key = f"{chat_id}_{thread_id}" if thread_id else chat_id
    ACTIVE_WORDSEEK_GAMES[primary_key] = {
        "word": secret_word,
        "length": word_length,
        "started_by": user.id,
        "started_by_name": user.first_name or "User",
        "guesses": [],  # List of guessed words
        "chat_id": chat_id,
        "thread_id": thread_id,
    }
    # Also save under chat_id and str(chat_id) for instant lookup
    ACTIVE_WORDSEEK_GAMES[chat_id] = ACTIVE_WORDSEEK_GAMES[primary_key]
    ACTIVE_WORDSEEK_GAMES[str(chat_id)] = ACTIVE_WORDSEEK_GAMES[primary_key]
    save_active_wordseek_game(chat_id, thread_id, ACTIVE_WORDSEEK_GAMES[primary_key])

    await update.message.reply_text(
        f"Game started! Guess the {word_length}-letter word!",
        auto_delete=False,
    )


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /new [4|5|6]"""
    await start_game(update, context)


cmd_wordseek = cmd_new


async def cmd_new4(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /new4"""
    await start_game(update, context, forced_length=4)


async def cmd_new5(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /new5"""
    await start_game(update, context, forced_length=5)


async def cmd_new6(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /new6"""
    await start_game(update, context, forced_length=6)


async def cmd_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /end - End the current active game."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    chat_id = chat.id
    thread_id = getattr(update.effective_message, "message_thread_id", None)
    _, game = get_active_game(chat_id, thread_id)
    if not game:
        await update.message.reply_text("There is no game in progress.")
        return

    word = game["word"]
    word_length = game["length"]

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

    # Delete active game
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
        f"<blockquote>🎮 <b>Game Ended</b>\n"
        f"Correct Word: <b>{word.upper()}</b></blockquote>\n"
        f"<blockquote>{reason}Start a new game with /new{word_length}</blockquote>"
    )

    await update.message.reply_text(msg, parse_mode="HTML", auto_delete=False)


cmd_endseek = cmd_end


async def check_wordseek_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Message watcher for WordSeek guesses.
    Executes exact WordSeek on-message handling.
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

    word_length = game["length"]
    current_guess = re.sub(r"[^a-zA-Z]", "", raw_text).lower()
    if not current_guess:
        return False

    # Ignore if guess length doesn't match current game's length
    if len(current_guess) != word_length:
        return False

    _load_word_lists()
    valid_words = _ALL_WORDS.get(word_length, set())

    # Check validity in dictionary
    if current_guess not in valid_words:
        await msg.reply_text(f"{current_guess} is not a valid {word_length}-letter word.")
        return True

    # Check if already guessed
    if current_guess in game["guesses"]:
        await msg.reply_text("Someone has already guessed your word. Please try another one!")
        return True

    # Check WIN condition
    if current_guess == game["word"]:
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
            record_pending_anon_score(chat.id, score, "wordseek", current_guess)
            clean_bot = (context.bot.username if context.bot else None) or "im_Radhabot"
            _, anon_kb = build_anon_verification_prompt(clean_bot, chat.id)
            reply_markup = anon_kb
            additional_message = (
                f"You scored {score} points!\n"
                f"🕵️ <i>Anonymous Admin: Tap below or reply with</i> <code>/anonid YOUR_ID</code> <i>to store your score on the leaderboard!</i>"
            )
        else:
            additional_message = f"Added {score} to the leaderboard."
            add_wordseek_score(eff_user_id, chat.id, eff_name, eff_uname, score, word_length)

        formatted_response = (
            f"<blockquote>Congrats! You guessed it correctly.\n"
            f"Correct Word: <b>{current_guess.upper()}</b>\n"
            f"{additional_message}</blockquote>\n"
            f"Start with /new{word_length}"
        )

        remove_active_game(chat_id, thread_id)

        await msg.reply_text(
            formatted_response,
            parse_mode="HTML",
            reply_markup=reply_markup,
            auto_delete=False,
        )

        # React with random emoji
        try:
            chosen_emoji = random.choice(REACTION_EMOJIS)
            await msg.set_reaction(chosen_emoji)
        except Exception:
            pass

        return True

    # Register guess
    game["guesses"].append(current_guess)
    all_guesses = game["guesses"]
    update_wordseek_guesses_db(chat_id, thread_id, all_guesses)

    # Check if max guesses (30) reached
    if len(all_guesses) >= 30:
        sol = game["word"]
        remove_active_game(chat_id, thread_id)
        await msg.reply_text(
            f"Game Over! The word was {sol.upper()}\nYou can start a new game with /new{word_length}",
            auto_delete=False,
        )
        return True

    # Format feedback for ongoing game using exact WordSeek rich HTML layout
    mode_label = MODE_LABEL.get(word_length, f"{word_length}-letter mode")
    rich_html = build_rich_feedback(all_guesses, game["word"], mode_label)

    try:
        await reply_rich_message(context.bot, chat.id, rich_html, thread_id)
    except Exception as e:
        print(f"sendRichMessage failed, fallback to text: {e}")
        rows_text = [render_guess_row_text(g, game["word"]) for g in all_guesses[-6:]]
        board_display = "\n".join(rows_text)
        feedback_text = (
            f"<b>{mode_label}</b>\n"
            f"<i>{len(all_guesses)}/30 guesses</i>\n\n"
            f"{board_display}"
        )
        buttons = build_guess_buttons(all_guesses, game["word"])
        reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
        await msg.reply_text(
            feedback_text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            auto_delete=False,
        )
    return True


async def wordseek_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handles wh:{state}:{letter} hint button clicks from WordSeek keyboard."""
    query = update.callback_query
    if not query or not query.data:
        return False

    data = query.data
    if not data.startswith("wh:"):
        return False

    parts = data.split(":")
    if len(parts) >= 3:
        state = parts[1]
        letter = parts[2]
        hint_template = HINTS.get(state, '"{letter}"')
        text = hint_template.format(letter=letter)
        await query.answer(text=text, show_alert=False)
        return True

    return False


async def cmd_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /score - View your WordSeek score."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    name = html.escape(user.first_name or "User")
    mention_link = f'<a href="tg://user?id={user.id}">{name}</a>'

    score_data = get_wordseek_user_score(user.id, chat.id)
    total_score = f"{score_data['totalScore']:,}"
    rank = str(score_data['rank'])

    msg = (
        f"<blockquote><strong>🏆 Regular WordSeek Scores</strong></blockquote>\n"
        f"<b>{mention_link}</b> has a total score of <b>{total_score}</b> in this chat.\n"
        f"Their rank is <b>#{rank}</b>."
    )

    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /leaderboard [group|global]"""
    chat = update.effective_chat
    if not chat:
        return

    is_global = False
    if context.args and "global" in [a.lower() for a in context.args]:
        is_global = True
    elif chat.type == "private":
        is_global = True

    search_chat_id = None if is_global else chat.id
    scope_title = "Global" if is_global else "Group"

    scores = get_wordseek_leaderboard(search_chat_id, limit=10)

    if not scores:
        await update.message.reply_text(
            f"<blockquote>🏆 {scope_title} Leaderboard 🏆</blockquote>\n\nNo scores recorded yet! Start playing with /new",
            parse_mode="HTML",
        )
        return

    lines = []
    for index, entry in enumerate(scores):
        rank_icon = ["🥇", "🥈", "🥉"][index] if index < 3 else "🔅"
        entry_name = html.escape(entry["name"])
        if entry.get("userId"):
            entry_name = f'<a href="tg://user?id={entry["userId"]}">{entry_name}</a>'
        elif entry.get("username"):
            entry_name = f'@{entry["username"]}'
        lines.append(f"{rank_icon} {entry_name} - {entry['totalScore']:,} pts")

    formatted_entries = f"<blockquote>" + "\n".join(lines) + "</blockquote>"
    msg = f"<blockquote>🏆 {scope_title} Leaderboard 🏆</blockquote>\n\n{formatted_entries}"

    await update.message.reply_text(msg, parse_mode="HTML")
