from __future__ import annotations

import os
import html
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes

# Configurable Ludo Web App URL (Vercel, GitHub Pages, or VPS HTTPS)
DEFAULT_LUDO_URL = os.getenv("LUDO_WEBAPP_URL", "https://mike-payment.vercel.app/ludo.html")

LUDO_COVER_PHOTO = "https://cdn.imageurlgenerator.com/uploads/856e0adb-1891-441e-ae03-1987d6befbf6.jpg"


def get_ludo_url(mode: Optional[str] = None, user_id: Optional[int] = None, name: Optional[str] = None) -> str:
    url = os.getenv("LUDO_WEBAPP_URL", DEFAULT_LUDO_URL)
    sep = "&" if "?" in url else "?"
    params = []
    if mode:
        params.append(f"mode={mode}")
    if user_id:
        params.append(f"user_id={user_id}")
    if name:
        params.append(f"name={name}")
    if params:
        return f"{url}{sep}{'&'.join(params)}"
    return url


def build_ludo_keyboard(user_id: int, user_name: str) -> InlineKeyboardMarkup:
    play_url = get_ludo_url(mode="bot", user_id=user_id, name=user_name)
    pvp_url = get_ludo_url(mode="2p", user_id=user_id, name=user_name)

    keyboard = [
        [
            InlineKeyboardButton("🎲 Play Ludo", web_app=WebAppInfo(url=play_url)),
        ],
        [
            InlineKeyboardButton("🤖 vs Bot Alpha", web_app=WebAppInfo(url=play_url)),
            InlineKeyboardButton("👥 2P Pass & Play", web_app=WebAppInfo(url=pvp_url)),
        ],
        [
            InlineKeyboardButton("📜 How to Play", callback_data="ludo_rules"),
            InlineKeyboardButton("🏆 Leaderboard", callback_data="lb_overall"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def cmd_ludo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /ludo - Sends the Ludo Mini Web Telegram Game card."""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user:
        return

    name = user.first_name or "Player"
    clean_name = html.escape(name)

    caption = (
        "<blockquote>🎲 <b>ludo</b>\n"
        "<i>ludo</i>\n\n"
        "Roll the dice, race your tokens home, capture rivals, and climb the leaderboard in a fast Telegram Ludo match.</blockquote>\n\n"
        f"👤 <b>Player:</b> {clean_name}\n"
        "✨ <i>Tap <b>Play Ludo</b> below to start the game directly in Telegram!</i>"
    )

    reply_markup = build_ludo_keyboard(user.id, name)

    try:
        # Send with photo if accessible
        await msg.reply_photo(
            photo=LUDO_COVER_PHOTO,
            caption=caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
            auto_delete=False,
        )
    except Exception as e:
        # Fallback to rich text card
        await msg.reply_text(
            caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
            auto_delete=False,
        )


async def ludo_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handles ludo_* callbacks."""
    query = update.callback_query
    if not query or not query.data:
        return False

    data = query.data
    if data == "ludo_rules":
        rules_text = (
            "<blockquote>🎲 <b>LUDO GAME RULES</b>\n\n"
            "• <b>Starting:</b> Roll a <b>6</b> to move a token out of your home base onto the track.\n"
            "• <b>Bonus Turn:</b> Rolling a <b>6</b> or capturing an enemy token gives an extra roll!\n"
            "• <b>Capturing:</b> Land on an opponent's token to send it back to their base.\n"
            "• <b>Safe Stars (★):</b> Tokens on star squares cannot be captured.\n"
            "• <b>Winning:</b> Guide all 4 tokens into the center home triangle to win!</blockquote>"
        )
        user = update.effective_user
        name = user.first_name if user else "Player"
        uid = user.id if user else 0
        back_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 Play Now", web_app=WebAppInfo(url=get_ludo_url(user_id=uid, name=name)))],
            [InlineKeyboardButton("🔙 Back", callback_data="ludo_back")]
        ])
        try:
            await query.edit_message_caption(caption=rules_text, parse_mode="HTML", reply_markup=back_markup)
        except Exception:
            try:
                await query.edit_message_text(text=rules_text, parse_mode="HTML", reply_markup=back_markup)
            except Exception:
                pass
        await query.answer()
        return True

    elif data == "ludo_back":
        user = update.effective_user
        name = user.first_name if user else "Player"
        uid = user.id if user else 0
        caption = (
            "<blockquote>🎲 <b>ludo</b>\n"
            "<i>ludo</i>\n\n"
            "Roll the dice, race your tokens home, capture rivals, and climb the leaderboard in a fast Telegram Ludo match.</blockquote>\n\n"
            f"👤 <b>Player:</b> {html.escape(name)}\n"
            "✨ <i>Tap <b>Play Ludo</b> below to start the game directly in Telegram!</i>"
        )
        reply_markup = build_ludo_keyboard(uid, name)
        try:
            await query.edit_message_caption(caption=caption, parse_mode="HTML", reply_markup=reply_markup)
        except Exception:
            try:
                await query.edit_message_text(text=caption, parse_mode="HTML", reply_markup=reply_markup)
            except Exception:
                pass
        await query.answer()
        return True

    return False
