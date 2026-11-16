from __future__ import annotations

import html
from typing import Optional, Dict, Any, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from modules.utils.db import (
    set_anonymous_link,
    get_anonymous_link,
    clear_anonymous_link,
    add_wordgrid_score,
    add_wordseek_score,
)
from modules.utils.storage import update_user, get_user

# In-memory pending scores for unlinked anonymous admins:
# {chat_id: [{"points": int, "game": str, "word": str, "chat_id": int}]}
PENDING_ANON_SCORES: Dict[int, list] = {}


def is_anonymous_admin(msg, user) -> bool:
    """Checks whether the message was sent as an anonymous admin."""
    if not user:
        return False
    if user.id == 1087968824 or getattr(user, "username", "") == "GroupAnonymousBot":
        return True
    if getattr(msg, "sender_chat", None) is not None:
        return True
    return False


def resolve_player_identity(chat_id: int, msg, user) -> Tuple[int, str, str, bool]:
    """
    Resolves the player's effective user_id, display_name, username, and whether they are an unlinked anonymous admin.
    Returns: (user_id, display_name, username, is_unlinked_anon)
    """
    if not is_anonymous_admin(msg, user):
        u_name = user.first_name or user.username or "User"
        u_name_clean = html.escape(u_name)
        return user.id, u_name_clean, user.username or "", False

    # Check SQLite for linked admin identity
    link = get_anonymous_link(chat_id)
    if link:
        uid = int(link["user_id"]) if str(link["user_id"]).isdigit() else link["user_id"]
        return uid, link["name"], link["username"], False

    # Unlinked anonymous admin
    return 1087968824, "Anonymous Admin", "GroupAnonymousBot", True


def record_pending_anon_score(chat_id: int, points: int, game_type: str, word: str) -> None:
    """Stores pending points for an anonymous admin until they verify."""
    if chat_id not in PENDING_ANON_SCORES:
        PENDING_ANON_SCORES[chat_id] = []
    PENDING_ANON_SCORES[chat_id].append({
        "points": points,
        "game": game_type,
        "word": word,
    })


def apply_pending_anon_scores(chat_id: int, user_id: int) -> int:
    """Credits all accumulated pending points to the newly linked user ID."""
    pending = PENDING_ANON_SCORES.pop(chat_id, [])
    total_points = sum(p["points"] for p in pending)
    if total_points > 0:
        try:
            ud = get_user(user_id)
            new_bal = ud.get("balance", 0) + total_points * 10
            new_gems = ud.get("gems", 0.0) + total_points
            new_xp = ud.get("xp", 0) + total_points * 5
            update_user(user_id, balance=new_bal, gems=new_gems, xp=new_xp)

            u_name = ud.get("name") or f"User {user_id}"
            u_uname = ud.get("username") or ""
            for item in pending:
                if item.get("game") == "wordgrid":
                    add_wordgrid_score(user_id, chat_id, u_name, u_uname, item["points"], item.get("word", ""))
                elif item.get("game") == "wordseek":
                    add_wordseek_score(user_id, chat_id, u_name, u_uname, item["points"], len(item.get("word", "")))
        except Exception as e:
            print(f"Error crediting pending anon score: {e}")
    return total_points


def build_anon_verification_prompt(bot_username: str, chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    """Builds prompt message and button for unlinked anonymous admins."""
    clean_bot = bot_username or "im_Radhabot"
    dm_link = f"https://t.me/{clean_bot}?start=anon_{abs(chat_id)}"

    text = (
        "🕵️ <b>Anonymous Admin Detected!</b>\n\n"
        "To save your scores to your personal profile & leaderboard:\n"
        "👉 Reply with: <code>/anonid YOUR_USER_ID</code> (e.g. <code>/anonid 123456789</code>)\n"
        "👉 Or reply with: <code>/anonid @username</code>\n\n"
        "🔗 <i>Or verify instantly via DM using the button below:</i>"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Verify in DM 🔐", url=dm_link)]
    ])

    return text, kb


async def cmd_anonid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Command: /anonid <user_id or @username>
    Links an anonymous admin in the current group to their real personal Telegram account.
    """
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message

    if not chat or not msg:
        return

    if chat.type == "private":
        await msg.reply_text("This command is used in group chats to link anonymous admin scores.")
        return

    args = context.args or []
    if not args:
        clean_bot = (context.bot.username if context.bot else None) or "im_Radhabot"
        text, kb = build_anon_verification_prompt(clean_bot, chat.id)
        await msg.reply_text(text, parse_mode="HTML", reply_markup=kb, auto_delete=False)
        return

    target = args[0].strip()

    # Determine user identity
    linked_id = None
    linked_uname = ""
    linked_name = ""

    if target.isdigit():
        linked_id = int(target)
        # Check if user exists in our DB
        u_doc = get_user(linked_id)
        if u_doc:
            linked_name = u_doc.get("name") or f"User {linked_id}"
            linked_uname = u_doc.get("username") or ""
        else:
            linked_name = f"Admin {linked_id}"
    elif target.startswith("@"):
        linked_uname = target.lstrip("@")
        linked_name = f"@{linked_uname}"
        linked_id = linked_uname
    else:
        linked_uname = target
        linked_name = f"@{linked_uname}"
        linked_id = target

    # Save mapping to SQLite
    set_anonymous_link(chat.id, linked_id, linked_uname, linked_name)

    # Apply any pending scores
    credited_pts = 0
    if isinstance(linked_id, int):
        credited_pts = apply_pending_anon_scores(chat.id, linked_id)

    bonus_msg = f"\n🎁 Credited <b>{credited_pts}</b> pending points to your account!" if credited_pts > 0 else ""

    await msg.reply_text(
        f"✅ <b>Anonymous Admin Verified!</b>\n"
        f"All scores in this group are now linked to <b>{html.escape(linked_name)}</b>.{bonus_msg}\n\n"
        f"You can now play WordSeek and WordGrid freely!",
        parse_mode="HTML",
        auto_delete=False,
    )
