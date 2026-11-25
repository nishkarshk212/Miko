from __future__ import annotations

import os
import html
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes

# Configurable Ludo Web App URL (Live Cloudflare SSL Tunnel on VPS)
DEFAULT_LUDO_URL = os.getenv("LUDO_WEBAPP_URL", "https://addition-ruby-skip-road.trycloudflare.com/ludo")

LUDO_COVER_PHOTO = "https://cdn.imageurlgenerator.com/uploads/856e0adb-1891-441e-ae03-1987d6befbf6.jpg"


def get_ludo_url(mode: Optional[str] = None, user_id: Optional[int] = None, name: Optional[str] = None, room: Optional[str] = None) -> str:
    import time
    url = os.getenv("LUDO_WEBAPP_URL", DEFAULT_LUDO_URL)
    sep = "&" if "?" in url else "?"
    params = []
    if mode:
        params.append(f"mode={mode}")
    if user_id:
        params.append(f"user_id={user_id}")
    if name:
        params.append(f"name={name}")
    if room:
        params.append(f"room={room}")
    params.append(f"v={int(time.time())}")
    return f"{url}{sep}{'&'.join(params)}"


def build_ludo_keyboard(
    user_id: int,
    user_name: str,
    is_private: bool = False,
    bot_username: Optional[str] = None,
    room_code: Optional[str] = None,
) -> InlineKeyboardMarkup:
    play_url = get_ludo_url(mode="pvp" if room_code else "bot", user_id=user_id, name=user_name, room=room_code)
    bot_uname = bot_username or "im_Radhabot"

    if is_private:
        # In 1-on-1 private chat, web_app buttons work directly and display the 🔲 Mini App icon
        btn_play = InlineKeyboardButton("Play Ludo", web_app=WebAppInfo(url=play_url))
    else:
        # In groups/supergroups, direct Telegram Mini App link
        start_param = room_code if room_code else "ludo"
        app_direct_link = f"https://t.me/{bot_uname}/ludo?startapp={start_param}"
        btn_play = InlineKeyboardButton("Play Ludo", url=app_direct_link)

    return InlineKeyboardMarkup([[btn_play]])


async def cmd_ludo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /ludo [room_code] - Sends the Ludo Mini Web Telegram Game card."""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user:
        return

    name = user.first_name or "Player"
    is_private = (chat.type == "private") if chat else False
    bot_uname = (context.bot.username if context.bot else None) or "im_Radhabot"

    # Room code: if provided use it, otherwise automatically generate a new room code
    room_code = None
    if context.args and len(context.args) > 0:
        room_code = context.args[0].strip().upper()

    if not room_code:
        import random
        chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        room_code = "".join(random.choices(chars, k=6))

    # Pre-register room in LUDO_ROOMS so this user is the Host / Leader
    try:
        from modules.payment.server import LUDO_ROOMS
        import time
        if room_code not in LUDO_ROOMS:
            LUDO_ROOMS[room_code] = {
                "code": room_code,
                "host_id": user.id,
                "status": "lobby",
                "seated": 1,
                "created_at": time.time(),
                "players": {
                    "red": {"id": user.id, "name": name, "avatar": "", "is_bot": False, "is_host": True},
                    "green": None,
                    "yellow": None,
                    "blue": None,
                },
                "chat": [],
                "events": [
                    {"text": f"{name} created room {room_code}.", "type": "Room event"},
                    {"text": f"{name} is the room leader.", "type": "Room event"}
                ],
                "turn": "red",
                "dice": 0,
                "roll_id": 0,
                "turn_version": 1,
            }
    except Exception as e:
        print(f"Ludo room init notice: {e}")

    caption = (
        "<b>ludo</b>\n"
        "<i>ludo</i>\n\n"
        "Roll the dice, race your tokens home, capture rivals, and climb the leaderboard in a fast Telegram Ludo match.\n\n"
        f"🔑 <b>Room:</b> <code>{room_code}</code>\n"
        f"👑 <b>Leader:</b> {html.escape(name)}\n\n"
        "✨ <i>Tap Play Ludo below to join this lobby!</i>"
    )

    reply_markup = build_ludo_keyboard(user.id, name, is_private=is_private, bot_username=bot_uname, room_code=room_code)

    # Local banner path (high-res 640x360 3D Ludo cover)
    local_banner = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "web", "ludo", "banner.jpg")
    if not os.path.exists(local_banner):
        local_banner = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "web", "ludo", "card_preview.jpg")

    sent_msg = None
    try:
        if os.path.exists(local_banner):
            with open(local_banner, "rb") as photo_f:
                sent_msg = await msg.reply_photo(
                    photo=photo_f,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    auto_delete=False,
                )
        else:
            sent_msg = await msg.reply_photo(
                photo=LUDO_COVER_PHOTO,
                caption=caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
                auto_delete=False,
            )
    except Exception as e:
        print(f"Ludo reply_photo notice ({e}), falling back to text")
        # Fallback to rich text card
        sent_msg = await msg.reply_text(
            caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
            auto_delete=False,
        )

    # Auto-pin Ludo message in group / supergroup
    if sent_msg and not is_private and chat:
        try:
            await context.bot.pin_chat_message(
                chat_id=chat.id,
                message_id=sent_msg.message_id,
                disable_notification=True,
            )
        except Exception as pin_err:
            print(f"Could not pin Ludo message in {chat.id}: {pin_err}")


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
