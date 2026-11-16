"""
Unified Word Games Leaderboard Module for Radha Bot.
Supports interactive switching between:
- Game Modes: WordSeek, WordGrid, Word Quiz, Overall
- Scopes: Group, Global
- Top 10 rankings with individual user rank card
- Small caps Nᴀᴍᴇ button styling with Telegram colored buttons (success/primary/danger)
"""
from __future__ import annotations

import html
from typing import Optional, Dict, Any, List, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from modules.utils.db import (
    get_wordseek_leaderboard,
    get_wordseek_user_score,
    get_wordgrid_leaderboard,
    get_wordgrid_user_score,
    get_wordquiz_leaderboard,
    get_wordquiz_user_score,
    get_overall_leaderboard,
    get_overall_user_score,
)

MODES = ["seek", "grid", "quiz", "overall"]
SCOPES = ["group", "global"]

MODE_LABELS = {
    "seek": "WordSeek",
    "grid": "WordGrid",
    "quiz": "Word Quiz",
    "overall": "Overall",
}

MODE_ICONS = {
    "seek": ("🏆", "WordSeek"),
    "grid": ("🧩", "WordGrid"),
    "quiz": ("💡", "Word Quiz"),
    "overall": ("👑", "Overall"),
}


def build_leaderboard_content(
    mode: str,
    scope: str,
    chat_id: Optional[int],
    user_id: int,
    user_name: str,
) -> Tuple[str, InlineKeyboardMarkup]:
    """Builds formatted leaderboard text and interactive button keyboard."""
    mode = mode if mode in MODES else "overall"
    scope = scope if scope in SCOPES else "group"

    # In private chat, always use global scope
    if not chat_id or chat_id > 0:
        scope = "global"

    filter_chat_id = chat_id if scope == "group" else None
    scope_title = "Group" if scope == "group" else "Global"

    # Fetch data based on mode
    if mode == "seek":
        scores = get_wordseek_leaderboard(filter_chat_id, limit=10)
        user_stat = get_wordseek_user_score(user_id, filter_chat_id)
        mode_title = "WordSeek"
        icon = "🏆"
    elif mode == "grid":
        scores = get_wordgrid_leaderboard(filter_chat_id, limit=10)
        user_stat = get_wordgrid_user_score(user_id, filter_chat_id)
        mode_title = "WordGrid"
        icon = "🧩"
    elif mode == "quiz":
        scores = get_wordquiz_leaderboard(filter_chat_id, limit=10)
        user_stat = get_wordquiz_user_score(user_id, filter_chat_id)
        mode_title = "Word Quiz"
        icon = "💡"
    else:  # overall
        scores = get_overall_leaderboard(filter_chat_id, limit=10)
        user_stat = get_overall_user_score(user_id, filter_chat_id)
        mode_title = "Overall"
        icon = "👑" if scope == "group" else "🌟"

    # Format entries
    medals = ["🥇", "🥈", "🥉"]
    lines: List[str] = []

    if scores:
        for idx, entry in enumerate(scores):
            rank_str = medals[idx] if idx < 3 else f"<b>{idx + 1}.</b>"
            name = html.escape(entry.get("name") or "User")
            pts = entry.get("totalScore", 0)
            lines.append(f"{rank_str} <b>{name}</b> — {pts:,} pts")
    else:
        lines.append("<i>No scores recorded yet! Start playing to claim #1!</i> 🌸")

    scores_body = "\n".join(lines)

    user_rank = user_stat.get("rank", "-")
    user_tot = user_stat.get("totalScore", 0)
    user_tag = html.escape(user_name)

    text = (
        f"{icon} <b>{mode_title.upper()} — {scope_title.upper()} LEADERBOARD</b> {icon}\n\n"
        f"<blockquote>{scores_body}</blockquote>\n\n"
        f"👤 <b>Your Rank:</b> #{user_rank} ({user_tot:,} pts) • <b>{user_tag}</b>\n"
        f"🕹️ <i>Mode: {mode_title} • Scope: {scope_title}</i>"
    )

    # Build Buttons
    cid_str = str(chat_id or 0)

    # Row 1: WordSeek & WordGrid
    b_seek = InlineKeyboardButton(
        "WordSeek",
        callback_data=f"lb:seek:{scope}:{cid_str}",
        api_kwargs={"style": "success" if mode == "seek" else "primary"},
    )
    b_grid = InlineKeyboardButton(
        "WordGrid",
        callback_data=f"lb:grid:{scope}:{cid_str}",
        api_kwargs={"style": "success" if mode == "grid" else "primary"},
    )

    # Row 2: Word Quiz & Overall
    b_quiz = InlineKeyboardButton(
        "Word Quiz",
        callback_data=f"lb:quiz:{scope}:{cid_str}",
        api_kwargs={"style": "success" if mode == "quiz" else "primary"},
    )
    b_overall = InlineKeyboardButton(
        "Overall",
        callback_data=f"lb:overall:{scope}:{cid_str}",
        api_kwargs={"style": "success" if mode == "overall" else "primary"},
    )

    # Row 3: Group & Global
    b_group = InlineKeyboardButton(
        "Group",
        callback_data=f"lb:{mode}:group:{cid_str}",
        api_kwargs={"style": "success" if scope == "group" else "primary"},
    )
    b_global = InlineKeyboardButton(
        "Global",
        callback_data=f"lb:{mode}:global:{cid_str}",
        api_kwargs={"style": "success" if scope == "global" else "primary"},
    )

    # Row 4: Refresh & Close
    b_refresh = InlineKeyboardButton(
        "Refresh",
        callback_data=f"lb:refresh:{mode}:{scope}:{cid_str}",
        api_kwargs={"style": "primary"},
    )
    b_close = InlineKeyboardButton(
        "Close",
        callback_data="lb:close",
        api_kwargs={"style": "danger"},
    )

    keyboard = InlineKeyboardMarkup([
        [b_seek, b_grid],
        [b_quiz, b_overall],
        [b_group, b_global],
        [b_refresh, b_close],
    ])

    return text, keyboard


async def cmd_unified_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /leaderboard [mode] [scope]"""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    # Parse arguments
    args = [a.lower() for a in (context.args or [])]

    # Default to overall (or seek if requested) and group (or global if private)
    mode = "overall"
    scope = "global" if chat.type == "private" else "group"

    for a in args:
        if a in ("seek", "wordseek"):
            mode = "seek"
        elif a in ("grid", "wordgrid", "wg"):
            mode = "grid"
        elif a in ("quiz", "wordquiz"):
            mode = "quiz"
        elif a in ("overall", "all", "total"):
            mode = "overall"
        elif a in ("global", "globally", "world"):
            scope = "global"
        elif a in ("group", "chat", "local"):
            scope = "group"

    user_name = user.first_name or user.username or "Player"
    text, keyboard = build_leaderboard_content(mode, scope, chat.id, user.id, user_name)

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
        auto_delete=False,
    )


async def leaderboard_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handles inline button clicks on the unified leaderboard."""
    query = update.callback_query
    if not query or not query.data or not query.data.startswith("lb:"):
        return False

    data = query.data
    user = update.effective_user
    user_id = user.id if user else 0
    user_name = (user.first_name if user else None) or "Player"

    if data == "lb:close":
        try:
            await query.message.delete()
        except Exception:
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
        await query.answer("Leaderboard closed.", show_alert=False)
        return True

    parts = data.split(":")
    # Formats:
    # lb:{mode}:{scope}:{chat_id} (len == 4)
    # lb:refresh:{mode}:{scope}:{chat_id} (len == 5)
    is_refresh = False
    if len(parts) >= 5 and parts[1] == "refresh":
        is_refresh = True
        mode = parts[2]
        scope = parts[3]
        chat_id_str = parts[4]
    elif len(parts) >= 4:
        mode = parts[1]
        scope = parts[2]
        chat_id_str = parts[3]
    else:
        return False

    try:
        chat_id = int(chat_id_str)
    except ValueError:
        chat_id = None

    text, keyboard = build_leaderboard_content(mode, scope, chat_id, user_id, user_name)

    try:
        await query.edit_message_text(
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        if is_refresh:
            await query.answer("🔄 Leaderboard refreshed!", show_alert=False)
        else:
            await query.answer()
    except Exception as e:
        # If already up to date
        await query.answer("Already up to date!", show_alert=False)

    return True
