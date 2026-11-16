from __future__ import annotations

import os
import re
import json
import time
import random
import html
import asyncio
from typing import Dict, Any, Optional, List, Set
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from modules.utils.storage import get_user, update_user, add_xp

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DICT_PATH = os.path.join(BASE_DIR, "assets", "word_chain_dict.json")

# Global dictionary
_DICTIONARY: Optional[Set[str]] = None


def _get_dict() -> Set[str]:
    global _DICTIONARY
    if _DICTIONARY is None:
        if os.path.exists(DICT_PATH):
            try:
                with open(DICT_PATH, "r", encoding="utf-8") as f:
                    _DICTIONARY = set(json.load(f))
            except Exception as e:
                print(f"Error loading word chain dict: {e}")
                _DICTIONARY = set()
        else:
            _DICTIONARY = set()
    return _DICTIONARY


# Active games in memory: {chat_id: GameSession}
WORD_CHAIN_GAMES: Dict[int, Dict[str, Any]] = {}

DIFFICULTY_CONFIGS = {
    "easy": {
        "timer": 30,
        "min_len": 3,
        "lives": 2,
        "desc": "30s timer • Min 3 letters • 2 lives",
        "hard_rules": False,
    },
    "medium": {
        "timer": 20,
        "min_len": 4,
        "lives": 1,
        "desc": "20s timer • Min 4 letters • 1 life • No start=end letter",
        "hard_rules": False,
    },
    "hard": {
        "timer": 15,
        "min_len": 5,
        "lives": 1,
        "desc": "15s timer • Min 5 letters • 1 life • No 'S' endings • No start=end letter",
        "hard_rules": True,
    },
}


def _get_game_key(chat_id: int, thread_id: Optional[int] = None) -> Any:
    return f"{chat_id}_{thread_id}" if thread_id else chat_id


def get_chain_game(chat_id: int, thread_id: Optional[int] = None) -> tuple[Optional[Any], Optional[Dict[str, Any]]]:
    keys = []
    if thread_id:
        keys.append(f"{chat_id}_{thread_id}")
    keys.append(str(chat_id))
    keys.append(chat_id)
    for k in keys:
        if k in WORD_CHAIN_GAMES:
            return k, WORD_CHAIN_GAMES[k]
    return None, None


def remove_chain_game(chat_id: int, thread_id: Optional[int] = None) -> None:
    keys = []
    if thread_id:
        keys.append(f"{chat_id}_{thread_id}")
    keys.append(str(chat_id))
    keys.append(chat_id)
    for k in keys:
        g = WORD_CHAIN_GAMES.pop(k, None)
        if g and g.get("timer_task") and not g["timer_task"].done():
            g["timer_task"].cancel()


async def cmd_word_chain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Start a Word Chain lobby:
    /wordchain [2|4] [easy|medium|hard] [bet]
    Example:
    /wordchain 2
    /wordchain 4 hard 500
    """
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    if chat.type == "private":
        await update.message.reply_text("🎮 Word Chain is a multiplayer game! Please play inside a group.")
        return

    thread_id = getattr(update.effective_message, "message_thread_id", None)
    _, existing = get_chain_game(chat.id, thread_id)
    if existing:
        await update.message.reply_text("⚠️ A Word Chain game is already active in this chat! Use /endchain to stop it.")
        return

    # Parse arguments
    target_players = 2
    difficulty = "easy"
    bet = 0

    args = [a.lower().strip() for a in (context.args or [])]
    for arg in args:
        if arg in ("2", "3", "4", "5", "6", "8"):
            target_players = int(arg)
        elif arg in ("easy", "low"):
            difficulty = "easy"
        elif arg in ("medium", "med", "mid"):
            difficulty = "medium"
        elif arg in ("hard", "expert"):
            difficulty = "hard"
        elif arg.isdigit() and int(arg) > 0:
            bet = int(arg)

    # Check creator balance if bet > 0
    ud = get_user(user.id, user.username or "User", user.first_name)
    if bet > 0:
        if ud.get("balance", 0) < bet:
            await update.message.reply_text(f"💸 Insufficient balance to host with ${bet}! You have: ${ud.get('balance', 0)}")
            return
        # Deduct host bet
        update_user(user.id, balance=ud.get("balance", 0) - bet)

    config = DIFFICULTY_CONFIGS[difficulty]
    primary_key = _get_game_key(chat.id, thread_id)

    game = {
        "chat_id": chat.id,
        "thread_id": thread_id,
        "state": "lobby",  # lobby or playing
        "host_id": user.id,
        "host_name": user.first_name or "User",
        "target_players": target_players,
        "difficulty": difficulty,
        "bet": bet,
        "pool": bet,
        "timer_seconds": config["timer"],
        "min_len": config["min_len"],
        "lives": config["lives"],
        "hard_rules": config["hard_rules"],
        "players": [
            {
                "id": user.id,
                "name": user.first_name or "User",
                "username": user.username,
                "mention": user.mention_html(),
                "lives": config["lives"],
            }
        ],
        "active_player_index": 0,
        "current_letter": "",
        "used_words": set(),
        "round_number": 1,
        "timer_task": None,
        "lobby_msg_id": None,
    }

    WORD_CHAIN_GAMES[primary_key] = game
    WORD_CHAIN_GAMES[chat.id] = game
    WORD_CHAIN_GAMES[str(chat.id)] = game

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔗 Join Game", callback_data=f"chain_join:{primary_key}"),
            InlineKeyboardButton("▶️ Start Game", callback_data=f"chain_start:{primary_key}"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data=f"chain_cancel:{primary_key}"),
        ]
    ])

    text = (
        "🔤 <b>Wᴏʀᴅ Cʜᴀɪɴ Qᴜɪᴢ Lᴏʙʙʏ</b> 🔤\n\n"
        f"👑 <b>Host:</b> {user.mention_html()}\n"
        f"👥 <b>Players:</b> 1/{target_players}\n"
        f"🎚️ <b>Difficulty:</b> <code>{difficulty.upper()}</code>\n"
        f"💰 <b>Bet:</b> ${bet} (Pool: ${game['pool']})\n"
        f"⏱️ <b>Timer:</b> {config['timer']}s per turn\n\n"
        f"📜 <b>Rules ({difficulty.upper()}):</b>\n"
        f"• {config['desc']}\n"
        "• Each word must START with the LAST letter of the previous word!\n\n"
        "👉 <i>Type <code>/join</code> or tap below to enter!</i>"
    )

    msg = await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML", auto_delete=False)
    game["lobby_msg_id"] = msg.message_id


async def word_chain_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    query = update.callback_query
    if not query or not query.data:
        return False

    data = query.data
    if not data.startswith("chain_"):
        return False

    parts = data.split(":", 1)
    action = parts[0]
    game_key = parts[1] if len(parts) > 1 else ""

    chat = update.effective_chat
    user = query.from_user
    if not chat or not user:
        return False

    thread_id = getattr(query.message, "message_thread_id", None)
    _, game = get_chain_game(chat.id, thread_id)
    if not game:
        await query.answer("⚠️ This Word Chain lobby has already ended or does not exist!", show_alert=True)
        return True

    if action == "chain_join":
        # Check if already joined
        if any(p["id"] == user.id for p in game["players"]):
            await query.answer("⚠️ You have already joined this game!", show_alert=True)
            return True

        if len(game["players"]) >= game["target_players"]:
            await query.answer("⚠️ This lobby is already full!", show_alert=True)
            return True

        # Check bet
        bet = game["bet"]
        if bet > 0:
            ud = get_user(user.id, user.username or "User", user.first_name)
            if ud.get("balance", 0) < bet:
                await query.answer(f"💸 Insufficient balance! Need ${bet}.", show_alert=True)
                return True
            update_user(user.id, balance=ud.get("balance", 0) - bet)
            game["pool"] += bet

        game["players"].append({
            "id": user.id,
            "name": user.first_name or "User",
            "username": user.username,
            "mention": user.mention_html(),
            "lives": game["lives"],
        })

        await query.answer(f"✅ Joined! ({len(game['players'])}/{game['target_players']})")

        # Update lobby text
        players_list = "\n".join([f"• {p['mention']}" for p in game["players"]])
        text = (
            "🔤 <b>Wᴏʀᴅ Cʜᴀɪɴ Qᴜɪᴢ Lᴏʙʙʏ</b> 🔤\n\n"
            f"👑 <b>Host:</b> {html.escape(game['host_name'])}\n"
            f"👥 <b>Players ({len(game['players'])}/{game['target_players']}):</b>\n{players_list}\n\n"
            f"🎚️ <b>Difficulty:</b> <code>{game['difficulty'].upper()}</code>\n"
            f"💰 <b>Bet Pool:</b> ${game['pool']}\n"
            f"⏱️ <b>Timer:</b> {game['timer_seconds']}s per turn\n\n"
            "👉 <i>Waiting for players... Tap Start when ready!</i>"
        )
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔗 Join Game", callback_data=f"chain_join:{game_key}"),
                InlineKeyboardButton("▶️ Start Game", callback_data=f"chain_start:{game_key}"),
            ],
            [
                InlineKeyboardButton("❌ Cancel", callback_data=f"chain_cancel:{game_key}"),
            ]
        ])
        try:
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass

        # Auto-start if target reached
        if len(game["players"]) >= game["target_players"]:
            await start_chain_match(context.bot, chat.id, thread_id)

        return True

    elif action == "chain_start":
        if user.id != game["host_id"]:
            await query.answer("⚠️ Only the game host can start the game!", show_alert=True)
            return True

        if len(game["players"]) < 2:
            await query.answer("⚠️ Need at least 2 players to start Word Chain!", show_alert=True)
            return True

        await query.answer("🚀 Starting Word Chain!")
        await start_chain_match(context.bot, chat.id, thread_id)
        return True

    elif action == "chain_cancel":
        if user.id != game["host_id"]:
            # Check admin
            is_admin = False
            try:
                member = await chat.get_member(user.id)
                is_admin = member.status in ("creator", "administrator")
            except Exception:
                is_admin = False
            if not is_admin:
                await query.answer("⚠️ Only the host or group admin can cancel the game!", show_alert=True)
                return True

        # Refund bets
        bet = game["bet"]
        if bet > 0:
            for p in game["players"]:
                pud = get_user(p["id"], p.get("username") or "User", p["name"])
                update_user(p["id"], balance=pud.get("balance", 0) + bet)

        remove_chain_game(chat.id, thread_id)
        await query.answer("❌ Word Chain cancelled. Bets refunded.")
        try:
            await query.edit_message_text("❌ <b>Word Chain lobby has been cancelled.</b>", parse_mode="HTML")
        except Exception:
            pass
        return True

    return False


async def cmd_chain_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /join when word chain is active."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    thread_id = getattr(update.effective_message, "message_thread_id", None)
    _, game = get_chain_game(chat.id, thread_id)
    if not game or game["state"] != "lobby":
        return

    # Check already in
    if any(p["id"] == user.id for p in game["players"]):
        await update.message.reply_text("⚠️ You have already joined this Word Chain lobby.")
        return

    if len(game["players"]) >= game["target_players"]:
        await update.message.reply_text("⚠️ This Word Chain lobby is already full.")
        return

    bet = game["bet"]
    if bet > 0:
        ud = get_user(user.id, user.username or "User", user.first_name)
        if ud.get("balance", 0) < bet:
            await update.message.reply_text(f"💸 Insufficient balance! Need ${bet}.")
            return
        update_user(user.id, balance=ud.get("balance", 0) - bet)
        game["pool"] += bet

    game["players"].append({
        "id": user.id,
        "name": user.first_name or "User",
        "username": user.username,
        "mention": user.mention_html(),
        "lives": game["lives"],
    })

    await update.message.reply_text(
        f"✅ {user.mention_html()} joined the Word Chain! ({len(game['players'])}/{game['target_players']})",
        parse_mode="HTML"
    )

    if len(game["players"]) >= game["target_players"]:
        await start_chain_match(context.bot, chat.id, thread_id)


async def cmd_chain_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel Word Chain game."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    thread_id = getattr(update.effective_message, "message_thread_id", None)
    _, game = get_chain_game(chat.id, thread_id)
    if not game:
        await update.message.reply_text("ℹ️ No active Word Chain game in this chat.")
        return

    is_host = user.id == game["host_id"]
    is_admin = False
    try:
        member = await chat.get_member(user.id)
        is_admin = member.status in ("creator", "administrator")
    except Exception:
        is_admin = False

    if not (is_host or is_admin):
        await update.message.reply_text("⚠️ Only the host or an administrator can end the Word Chain.")
        return

    # Refund bets
    bet = game["bet"]
    if bet > 0 and game["state"] == "lobby":
        for p in game["players"]:
            pud = get_user(p["id"], p.get("username") or "User", p["name"])
            update_user(p["id"], balance=pud.get("balance", 0) + bet)

    remove_chain_game(chat.id, thread_id)
    await update.message.reply_text("🛑 <b>Word Chain game has been stopped.</b>", parse_mode="HTML")


async def start_chain_match(bot, chat_id: int, thread_id: Optional[int] = None):
    """Begins the turn-based Word Chain match."""
    _, game = get_chain_game(chat_id, thread_id)
    if not game or game["state"] == "playing":
        return

    game["state"] = "playing"
    # Shuffle players for fair randomized order
    random.shuffle(game["players"])

    # Pick a random starting letter (common vowels or friendly consonants)
    starting_letters = list("ABCDEFGHIKLMNOPRSTUW")
    initial_letter = random.choice(starting_letters)
    game["current_letter"] = initial_letter
    game["active_player_index"] = 0
    game["round_number"] = 1
    game["used_words"] = set()

    start_text = (
        "🚀 <b>Wᴏʀᴅ Cʜᴀɪɴ Qᴜɪᴢ Hᴀꜱ Bᴇɢᴜɴ!</b> 🚀\n\n"
        f"🎚️ <b>Difficulty:</b> <code>{game['difficulty'].upper()}</code>\n"
        f"💰 <b>Prize Pool:</b> ${game['pool']}\n"
        f"⏱️ <b>Turn Timer:</b> {game['timer_seconds']}s\n"
        f"🔤 <b>Starting Letter:</b> <code>{initial_letter}</code>\n\n"
        "<b>Turn Order:</b>\n" +
        "\n".join([f"{i+1}. {p['name']}" for i, p in enumerate(game["players"])])
    )
    await bot.send_message(chat_id=chat_id, message_thread_id=thread_id, text=start_text, parse_mode="HTML")

    # Prompt the first player
    await prompt_current_turn(bot, chat_id, thread_id)


async def prompt_current_turn(bot, chat_id: int, thread_id: Optional[int] = None):
    _, game = get_chain_game(chat_id, thread_id)
    if not game or game["state"] != "playing":
        return

    active_players = [p for p in game["players"] if p["lives"] > 0]
    if len(active_players) <= 1:
        await conclude_game(bot, chat_id, thread_id)
        return

    curr_p = game["players"][game["active_player_index"]]
    letter = game["current_letter"]
    timer = game["timer_seconds"]
    diff = game["difficulty"].upper()

    hint = f"Must be at least {game['min_len']} letters."
    if game["hard_rules"]:
        hint += " • Cannot end in 'S' • First != Last letter."

    prompt_msg = (
        f"🎯 <b>Rᴏᴜɴᴅ {game['round_number']}</b>\n"
        f"👉 <b>Turn:</b> {curr_p['mention']}\n"
        f"🔤 <b>Word MUST start with:</b> <code>{letter}</code>\n"
        f"⏱️ <b>Time remaining:</b> {timer} seconds\n"
        f"📜 <i>{hint}</i>"
    )

    await bot.send_message(chat_id=chat_id, message_thread_id=thread_id, text=prompt_msg, parse_mode="HTML")

    # Cancel previous timer if any
    if game.get("timer_task") and not game["timer_task"].done():
        game["timer_task"].cancel()

    # Schedule turn timeout worker
    round_no = game["round_number"]
    player_id = curr_p["id"]

    async def _turn_timer_worker():
        await asyncio.sleep(timer)
        # Check if still this player's turn
        _, cur_g = get_chain_game(chat_id, thread_id)
        if not cur_g or cur_g["state"] != "playing":
            return
        if cur_g["round_number"] == round_no and cur_g["players"][cur_g["active_player_index"]]["id"] == player_id:
            await handle_turn_timeout(bot, chat_id, thread_id, curr_p)

    game["timer_task"] = asyncio.create_task(_turn_timer_worker())


async def handle_turn_timeout(bot, chat_id: int, thread_id: Optional[int], timed_out_player: Dict[str, Any]):
    _, game = get_chain_game(chat_id, thread_id)
    if not game or game["state"] != "playing":
        return

    timed_out_player["lives"] -= 1

    if timed_out_player["lives"] <= 0:
        await bot.send_message(
            chat_id=chat_id,
            message_thread_id=thread_id,
            text=f"⏰ <b>Time's up!</b>\n❌ {timed_out_player['mention']} failed to respond and has been <b>ELIMINATED</b>!",
            parse_mode="HTML"
        )
    else:
        await bot.send_message(
            chat_id=chat_id,
            message_thread_id=thread_id,
            text=f"⏰ <b>Time's up!</b>\n⚠️ {timed_out_player['mention']} lost a life! (Lives remaining: {timed_out_player['lives']})",
            parse_mode="HTML"
        )

    # Advance to next active player
    await advance_to_next_player(bot, chat_id, thread_id, fresh_letter=True)


async def advance_to_next_player(bot, chat_id: int, thread_id: Optional[int], fresh_letter: bool = False):
    _, game = get_chain_game(chat_id, thread_id)
    if not game or game["state"] != "playing":
        return

    active_players = [p for p in game["players"] if p["lives"] > 0]
    if len(active_players) <= 1:
        await conclude_game(bot, chat_id, thread_id)
        return

    # Cycle to next player with lives > 0
    total = len(game["players"])
    idx = (game["active_player_index"] + 1) % total
    while game["players"][idx]["lives"] <= 0:
        idx = (idx + 1) % total

    game["active_player_index"] = idx
    game["round_number"] += 1

    if fresh_letter:
        game["current_letter"] = random.choice(list("ABCDEFGHIKLMNOPRSTUW"))

    await prompt_current_turn(bot, chat_id, thread_id)


async def check_word_chain_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Watches incoming chat messages during active Word Chain match."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not msg or not chat or not user:
        return False

    raw_text = (msg.text or "").strip()
    if not raw_text or raw_text.startswith("/"):
        return False

    thread_id = getattr(msg, "message_thread_id", None)
    _, game = get_chain_game(chat.id, thread_id)
    if not game or game["state"] != "playing":
        return False

    curr_p = game["players"][game["active_player_index"]]

    # Only process messages from the player whose turn it is!
    if user.id != curr_p["id"]:
        return False

    # Extract alphabetic word
    word = re.sub(r"[^a-zA-Z]", "", raw_text).lower()
    if not word:
        return False

    req_letter = game["current_letter"].lower()

    # 1. Starting letter check
    if not word.startswith(req_letter):
        await msg.reply_text(f"❌ <code>{word.upper()}</code> does NOT start with <b>'{req_letter.upper()}'</b>!")
        return True

    # 2. Length check
    if len(word) < game["min_len"]:
        await msg.reply_text(f"❌ <code>{word.upper()}</code> is too short! Minimum {game['min_len']} letters required.")
        return True

    # 3. Medium & Hard: first letter != last letter
    if game["difficulty"] in ("medium", "hard") and word[0] == word[-1]:
        await msg.reply_text(f"❌ In {game['difficulty'].upper()} mode, the first and last letters cannot be identical!")
        return True

    # 4. Hard rule: cannot end in 'S'
    if game["hard_rules"] and word.endswith("s"):
        await msg.reply_text("❌ In HARD mode, words cannot end with the letter 'S'!")
        return True

    # 5. Already used check
    if word in game["used_words"]:
        await msg.reply_text(f"❌ <code>{word.upper()}</code> has already been used in this match! Try another one.")
        return True

    # 6. Dictionary verification
    dictionary = _get_dict()
    if word not in dictionary:
        await msg.reply_text(f"❌ <code>{word.upper()}</code> is not in the English dictionary!")
        return True

    # VALID WORD! Cancel turn timer
    if game.get("timer_task") and not game["timer_task"].done():
        game["timer_task"].cancel()

    game["used_words"].add(word)
    next_letter = word[-1].upper()
    game["current_letter"] = next_letter

    # Announce valid play
    p_name = curr_p["name"]
    await msg.reply_text(
        f"✅ <b>{html.escape(p_name)} played:</b> <code>{word.upper()}</code>\n"
        f"🔤 <b>Ending letter:</b> <code>{next_letter}</code> ➔ Next player must start with <b>'{next_letter}'</b>!",
        parse_mode="HTML"
    )

    # Advance to next player
    await advance_to_next_player(context.bot, chat.id, thread_id, fresh_letter=False)
    return True


async def conclude_game(bot, chat_id: int, thread_id: Optional[int] = None):
    _, game = get_chain_game(chat_id, thread_id)
    if not game:
        return

    if game.get("timer_task") and not game["timer_task"].done():
        game["timer_task"].cancel()

    active_players = [p for p in game["players"] if p["lives"] > 0]
    winner = active_players[0] if active_players else game["players"][0]

    pool = game["pool"]
    if pool > 0:
        w_ud = get_user(winner["id"], winner.get("username") or "User", winner["name"])
        update_user(winner["id"], balance=w_ud.get("balance", 0) + pool)

    add_xp(winner["id"], 100)

    win_text = (
        "🏆 <b>Wᴏʀᴅ Cʜᴀɪɴ Cʜᴀᴍᴘɪᴏɴ!</b> 🏆\n\n"
        f"👑 <b>Winner:</b> {winner['mention']}\n"
        f"💰 <b>Prize Won:</b> ${pool}\n"
        "🌟 <b>XP Gained:</b> +100 XP\n"
        f"📚 <b>Words Chained:</b> {len(game['used_words'])}\n\n"
        "🎉 <i>Gɢ! Sᴛᴀʀᴛ ᴀ ɴᴇᴡ ᴍᴀᴛᴄʜ ᴡɪᴛʜ <code>/chain</code>!</i>"
    )

    remove_chain_game(chat_id, thread_id)
    await bot.send_message(chat_id=chat_id, message_thread_id=thread_id, text=win_text, parse_mode="HTML")
