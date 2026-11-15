import os
import re
import json
import time
import random
import html
from typing import Dict, Any, Optional, Set
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(BASE_DIR, "assets", "wordseek")

# Word lists cache
_WORD_LISTS: Dict[int, Set[str]] = {}
_COMMON_WORDS: Dict[int, list] = {}

def _load_word_lists():
    global _WORD_LISTS, _COMMON_WORDS
    if _WORD_LISTS:
        return

    mapping = {
        4: ("all-four.json", "common-four.json"),
        5: ("all-five.json", "common-five.json"),
        6: ("all-six.json", "common-six.json"),
    }

    for length, (all_file, common_file) in mapping.items():
        all_path = os.path.join(DATA_DIR, all_file)
        common_path = os.path.join(DATA_DIR, common_file)

        all_words = set()
        common_words = []

        if os.path.exists(all_path):
            try:
                with open(all_path, "r", encoding="utf-8") as f:
                    all_words = {w.strip().upper() for w in json.load(f)}
            except Exception as e:
                print(f"Error loading {all_file}: {e}")

        if os.path.exists(common_path):
            try:
                with open(common_path, "r", encoding="utf-8") as f:
                    common_words = [w.strip().upper() for w in json.load(f)]
            except Exception as e:
                print(f"Error loading {common_file}: {e}")

        if not common_words and all_words:
            common_words = list(all_words)

        _WORD_LISTS[length] = all_words
        _COMMON_WORDS[length] = common_words


# Active in-memory games: {chat_id: game_dict}
ACTIVE_WORDSEEK_GAMES: Dict[int, Dict[str, Any]] = {}


def evaluate_guess(target_word: str, guess_word: str) -> str:
    """Evaluates guess against target with standard Wordle rules."""
    target = list(target_word.upper())
    guess = list(guess_word.upper())
    n = len(target)
    tiles = ["⬛"] * n
    counts = {}

    for ch in target:
        counts[ch] = counts.get(ch, 0) + 1

    # First pass: Green (exact match)
    for i in range(n):
        if guess[i] == target[i]:
            tiles[i] = "🟩"
            counts[guess[i]] -= 1

    # Second pass: Yellow (misplaced letter)
    for i in range(n):
        if tiles[i] == "⬛" and counts.get(guess[i], 0) > 0:
            tiles[i] = "🟨"
            counts[guess[i]] -= 1

    return "".join(tiles)


async def cmd_wordseek(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a new WordSeek game: /wordseek [4|5|6]"""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    _load_word_lists()

    chat_id = chat.id
    if chat_id in ACTIVE_WORDSEEK_GAMES:
        g = ACTIVE_WORDSEEK_GAMES[chat_id]
        await update.message.reply_text(
            f"⚠️ <b>A WᴏʀᴅSᴇᴇᴋ ɢᴀᴍᴇ ɪꜱ ᴀʟʀᴇᴀᴅʏ ɪɴ ᴘʀᴏɢʀᴇꜱꜱ!</b>\n\n"
            f"🎯 <b>Length:</b> {g['length']} letters\n"
            f"🔢 <b>Attempts:</b> {len(g['guesses'])}/{g['max_attempts']}\n\n"
            f"👉 <i>Type your guess or use <code>/endseek</code> to end it!</i>",
            parse_mode="HTML"
        )
        return

    # Choose length: default 5
    length = 5
    if context.args:
        arg = context.args[0].strip()
        if arg in ("4", "5", "6"):
            length = int(arg)

    common_pool = _COMMON_WORDS.get(length, [])
    if not common_pool:
        common_pool = list(_WORD_LISTS.get(length, []))

    if not common_pool:
        await update.message.reply_text("❌ No words found for this length.")
        return

    target = random.choice(common_pool).upper()

    ACTIVE_WORDSEEK_GAMES[chat_id] = {
        "word": target,
        "length": length,
        "guesses": [],
        "max_attempts": 20 if chat.type != "private" else 8,
        "started_by": user.id,
        "started_by_name": user.first_name or "User",
        "start_time": time.time(),
        "keyboard_status": {},  # letter -> 🟩/🟨/⬛
    }

    start_msg = (
        "🎯 <b>WᴏʀᴅSᴇᴇᴋ Gᴀᴍᴇ Sᴛᴀʀᴛᴇᴅ!</b> 🎯\n\n"
        f"👑 <b>Hᴏꜱᴛ:</b> <a href=\"tg://user?id={user.id}\">{html.escape(user.first_name or 'User')}</a>\n"
        f"🔤 <b>Wᴏʀᴅ Lᴇɴɢᴛʜ:</b> <code>{length} Letters</code>\n"
        f"🔢 <b>Mᴀx Aᴛᴛᴇᴍᴘᴛꜱ:</b> <code>{ACTIVE_WORDSEEK_GAMES[chat_id]['max_attempts']}</code>\n\n"
        "<b>🎨 Hᴏᴡ ᴛᴏ Pʟᴀʏ:</b>\n"
        "• 🟩 = Correct letter in the right spot\n"
        "• 🟨 = Correct letter in the wrong spot\n"
        "• ⬛ = Letter not in the secret word\n\n"
        f"👉 <b>Type any {length}-letter English word in chat to guess!</b>\n"
        "🛑 Stop game: <code>/endseek</code>"
    )
    await update.message.reply_text(start_msg, parse_mode="HTML")


async def cmd_endseek(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """End the current WordSeek game."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    chat_id = chat.id
    if chat_id not in ACTIVE_WORDSEEK_GAMES:
        await update.message.reply_text("ℹ️ There is no active WordSeek game in this chat. Start with /wordseek!")
        return

    game = ACTIVE_WORDSEEK_GAMES.pop(chat_id)
    word = game["word"]
    await update.message.reply_text(
        f"🛑 <b>WᴏʀᴅSᴇᴇᴋ Gᴀᴍᴇ Eɴᴅᴇᴅ!</b>\n\n"
        f"✨ The secret word was: <b>{word}</b>\n"
        f"Start a new game anytime with <code>/wordseek</code>! 🎮",
        parse_mode="HTML"
    )


async def check_wordseek_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Watches incoming chat messages for WordSeek guesses."""
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message

    if not chat or not user or not msg or not msg.text:
        return False

    chat_id = chat.id
    if chat_id not in ACTIVE_WORDSEEK_GAMES:
        return False

    game = ACTIVE_WORDSEEK_GAMES[chat_id]
    text = msg.text.strip().upper()

    # Ignore commands
    if text.startswith(("/", ".", "!", "?")):
        return False

    # Check if string matches single word of required length
    if not re.match(r"^[A-Z]+$", text) or len(text) != game["length"]:
        return False

    _load_word_lists()
    valid_words = _WORD_LISTS.get(game["length"], set())

    # Check dictionary validation
    if valid_words and text not in valid_words:
        await msg.reply_text(f"⚠️ <code>{text}</code> is not in the dictionary! Try a valid English word.")
        return True

    # Check if already guessed
    if any(g["guess"] == text for g in game["guesses"]):
        await msg.reply_text(f"⚠️ <code>{text}</code> has already been guessed! Try another word.")
        return True

    # Evaluate guess
    tiles = evaluate_guess(game["word"], text)
    user_name = user.first_name or "User"
    mention = f'<a href="tg://user?id={user.id}">{html.escape(user_name)}</a>'

    # Update keyboard letter statuses
    for i, ch in enumerate(text):
        tile = tiles[i]
        curr = game["keyboard_status"].get(ch)
        if tile == "🟩":
            game["keyboard_status"][ch] = "🟩"
        elif tile == "🟨" and curr != "🟩":
            game["keyboard_status"][ch] = "🟨"
        elif tile == "⬛" and not curr:
            game["keyboard_status"][ch] = "⬛"

    game["guesses"].append({
        "user_id": user.id,
        "name": user_name,
        "guess": text,
        "tiles": tiles,
    })

    current_attempt = len(game["guesses"])
    max_attempts = game["max_attempts"]

    # 1. Check WIN condition
    if text == game["word"]:
        ACTIVE_WORDSEEK_GAMES.pop(chat_id, None)

        # Rewards: 5000 coins + 50 XP
        reward_coins = 5000
        reward_xp = 50
        try:
            from modules.utils.storage import get_user, update_user, add_xp
            ud = get_user(user.id, user.username or user_name, user_name)
            ud["balance"] = ud.get("balance", 0) + reward_coins
            update_user(user.id, balance=ud["balance"])
            add_xp(user.id, reward_xp)
        except Exception as ee:
            print(f"Error giving rewards: {ee}")

        # Build victory grid
        lines = []
        for idx, g in enumerate(game["guesses"][-6:], start=max(1, len(game["guesses"]) - 5)):
            spaced = " ".join(list(g["guess"]))
            lines.append(f"{idx}. {g['tiles']} <code>{spaced}</code> — {html.escape(g['name'])}")

        grid_str = "\n".join(lines)

        win_msg = (
            f"🎉 <b>BINGO! WE HAVE A WINNER!</b> 🎉\n\n"
            f"🏆 <b>Winner:</b> {mention}\n"
            f"✨ <b>Word:</b> <code>{game['word']}</code>\n"
            f"🔢 <b>Attempts:</b> {current_attempt}/{max_attempts}\n"
            f"💰 <b>Reward:</b> +${reward_coins} Coins &amp; +{reward_xp} XP!\n\n"
            f"<b>📜 Final Board:</b>\n{grid_str}\n\n"
            "Play again anytime with <code>/wordseek</code>! 🍀"
        )
        await msg.reply_text(win_msg, parse_mode="HTML")
        return True

    # 2. Check LOSS condition (attempts exhausted)
    if current_attempt >= max_attempts:
        ACTIVE_WORDSEEK_GAMES.pop(chat_id, None)

        lines = []
        for idx, g in enumerate(game["guesses"][-6:], start=max(1, len(game["guesses"]) - 5)):
            spaced = " ".join(list(g["guess"]))
            lines.append(f"{idx}. {g['tiles']} <code>{spaced}</code> — {html.escape(g['name'])}")

        grid_str = "\n".join(lines)

        loss_msg = (
            f"💀 <b>GAME OVER! Out of attempts!</b>\n\n"
            f"The secret word was: <b>{game['word']}</b>\n\n"
            f"<b>📜 Board:</b>\n{grid_str}\n\n"
            "Better luck next time! Type <code>/wordseek</code> to retry. 🌸"
        )
        await msg.reply_text(loss_msg, parse_mode="HTML")
        return True

    # 3. Intermediate guess response
    # Show last 5 guesses
    recent = game["guesses"][-5:]
    lines = []
    start_num = max(1, len(game["guesses"]) - len(recent) + 1)
    for idx, g in enumerate(recent, start=start_num):
        spaced = " ".join(list(g["guess"]))
        lines.append(f"<code>{g['tiles']}</code>  <code>{spaced}</code>  — {html.escape(g['name'])}")

    board_text = "\n".join(lines)

    # Key letters used
    greens = [ch for ch, s in game["keyboard_status"].items() if s == "🟩"]
    yellows = [ch for ch, s in game["keyboard_status"].items() if s == "🟨"]
    grays = [ch for ch, s in game["keyboard_status"].items() if s == "⬛"]

    letters_summary = ""
    if greens:
        letters_summary += f"🟩 Correct: <b>{' '.join(sorted(greens))}</b>\n"
    if yellows:
        letters_summary += f"🟨 Misplaced: <b>{' '.join(sorted(yellows))}</b>\n"
    if grays:
        letters_summary += f"⬛ Not in word: <s>{' '.join(sorted(grays))}</s>\n"

    reply_text = (
        f"🎯 <b>WᴏʀᴅSᴇᴇᴋ ({game['length']} Lᴇᴛᴛᴇʀꜱ)</b> • <i>Aᴛᴛᴇᴍᴘᴛ {current_attempt}/{max_attempts}</i>\n\n"
        f"{board_text}\n\n"
        f"{letters_summary}\n"
        f"👉 <i>Type next {game['length']}-letter guess in chat!</i>"
    )
    await msg.reply_text(reply_text, parse_mode="HTML")
    return True
