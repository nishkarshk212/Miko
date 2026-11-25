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


def build_ludo_keyboard(
    user_id: int,
    user_name: str,
    is_private: bool = False,
    bot_username: Optional[str] = None,
) -> InlineKeyboardMarkup:
    play_url = get_ludo_url(mode="bot", user_id=user_id, name=user_name)
    pvp_url = get_ludo_url(mode="2p", user_id=user_id, name=user_name)
    bot_uname = bot_username or "im_Radhabot"

    if is_private:
        # In 1-on-1 private chat, web_app buttons work directly
        btn_play = InlineKeyboardButton("🎲 Play Ludo", web_app=WebAppInfo(url=play_url))
        btn_bot = InlineKeyboardButton("🤖 vs Bot Alpha", web_app=WebAppInfo(url=play_url))
        btn_pvp = InlineKeyboardButton("👥 2P Pass & Play", web_app=WebAppInfo(url=pvp_url))
    else:
        # In groups/supergroups, Telegram Bot API rejects web_app buttons with 'Button_type_invalid'
        # Instead, use Telegram's official Mini App launch link or direct game URL
        app_direct_link = f"https://t.me/{bot_uname}?startapp=ludo"
        btn_play = InlineKeyboardButton("🎲 Play Ludo", url=app_direct_link)
        btn_bot = InlineKeyboardButton("🤖 vs Bot Alpha", url=play_url)
        btn_pvp = InlineKeyboardButton("👥 2P Pass & Play", url=pvp_url)

    keyboard = [
        [btn_play],
        [btn_bot, btn_pvp],
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
    is_private = (chat.type == "private") if chat else False
    bot_uname = (context.bot.username if context.bot else None) or "im_Radhabot"

    caption = (
        "<blockquote>🎲 <b>ludo</b>\n"
        "<i>ludo</i>\n\n"
        "Roll the dice, race your tokens home, capture rivals, and climb the leaderboard in a fast Telegram Ludo match.</blockquote>\n\n"
        f"👤 <b>Player:</b> {clean_name}\n"
        "✨ <i>Tap <b>Play Ludo</b> below to start the game directly in Telegram!</i>"
    )

    reply_markup = build_ludo_keyboard(user.id, name, is_private=is_private, bot_username=bot_uname)

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
        print(f"Ludo reply_photo notice ({e}), falling back to text")
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
    chat = update.effective_chat
    is_private = (chat.type == "private") if chat else False
    bot_uname = (context.bot.username if context.bot else None) or "im_Radhabot"

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
        play_url = get_ludo_url(user_id=uid, name=name)

        if is_private:
            play_btn = InlineKeyboardButton("🎲 Play Now", web_app=WebAppInfo(url=play_url))
        else:
            play_btn = InlineKeyboardButton("🎲 Play Now", url=f"https://t.me/{bot_uname}?startapp=ludo")

        back_markup = InlineKeyboardMarkup([
            [play_btn],
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
        reply_markup = build_ludo_keyboard(uid, name, is_private=is_private, bot_username=bot_uname)
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
