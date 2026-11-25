import os
import html
import random
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes

CHESS_COVER_PHOTO = "https://images.unsplash.com/photo-1529699211952-734e80c4d42b?auto=format&fit=crop&w=1200&q=80"


def build_chess_keyboard(user_id: int, name: str, is_private: bool = False, bot_username: str = "im_Radhabot", room_code: str = None) -> InlineKeyboardMarkup:
    """Builds the Play Chess WebApp button."""
    start_param = room_code if room_code else "chess"
    if is_private:
        # In private chat, open WebApp directly inside Telegram
        app_url = f"https://addition-ruby-skip-road.trycloudflare.com/chess?room={start_param}"
        btn_play = InlineKeyboardButton("Play Chess ♟️", web_app=WebAppInfo(url=app_url))
    else:
        # In groups/supergroups, direct Telegram Mini App link
        app_direct_link = f"https://t.me/{bot_username}/chess?startapp={start_param}"
        btn_play = InlineKeyboardButton("Play Chess ♟️", url=app_direct_link)

    return InlineKeyboardMarkup([[btn_play]])


async def cmd_chess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /chess [room_code] - Sends the Chess Mini Web Telegram Game card."""
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
        chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        room_code = "".join(random.choices(chars, k=6))

    # Pre-register room in CHESS_ROOMS
    try:
        from modules.payment.server import CHESS_ROOMS
        if room_code not in CHESS_ROOMS:
            CHESS_ROOMS[room_code] = {
                "code": room_code,
                "host_id": user.id,
                "status": "lobby",
                "created_at": time.time(),
                "white_player": {"id": user.id, "name": name, "avatar": "", "is_bot": False},
                "black_player": None,
                "turn": "white",
                "move_history": [],
            }
    except Exception as e:
        print(f"Chess room init notice: {e}")

    caption = (
        "<b>Chess</b> ♟️\n"
        "<i>Royal Strategy & Tactics</i>\n\n"
        "Challenge your mind, strategize attacks, capture rival pieces, and deliver checkmate in a fast Telegram Chess match.\n\n"
        f"🔑 <b>Room:</b> <code>{room_code}</code>\n"
        f"👑 <b>Leader:</b> {html.escape(name)}\n\n"
        "✨ <i>Tap Play Chess below to join this match!</i>"
    )

    reply_markup = build_chess_keyboard(user.id, name, is_private=is_private, bot_username=bot_uname, room_code=room_code)

    # Local banner path if available
    local_banner = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "web", "chess", "banner.jpg")

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
                photo=CHESS_COVER_PHOTO,
                caption=caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
                auto_delete=False,
            )
    except Exception as e:
        print(f"Chess reply_photo notice ({e}), falling back to text")
        sent_msg = await msg.reply_text(
            caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
            auto_delete=False,
        )

    # Auto-pin in group / supergroup chats
    if sent_msg and not is_private and chat:
        try:
            await context.bot.pin_chat_message(
                chat_id=chat.id,
                message_id=sent_msg.message_id,
                disable_notification=True,
            )
        except Exception as pin_err:
            print(f"Could not pin Chess message in {chat.id}: {pin_err}")
