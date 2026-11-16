"""
Global link preview disabler module.
Ensures all Telegram bot messages have link previews disabled by default across the entire application.
"""
from __future__ import annotations

from typing import Any, Callable
from telegram import Bot, Message, CallbackQuery

_PATCHED = False


def disable_link_previews_globally() -> None:
    """
    Patches Telegram messaging methods to ensure disable_web_page_preview=True
    is always applied unless explicitly overridden.
    """
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True

    # Patch Bot.send_message
    orig_send_message = Bot.send_message

    async def _patched_send_message(self: Bot, *args: Any, **kwargs: Any):
        kwargs.setdefault("disable_web_page_preview", True)
        return await orig_send_message(self, *args, **kwargs)

    Bot.send_message = _patched_send_message

    # Patch Bot.edit_message_text
    orig_edit_message_text = Bot.edit_message_text

    async def _patched_edit_message_text(self: Bot, *args: Any, **kwargs: Any):
        kwargs.setdefault("disable_web_page_preview", True)
        return await orig_edit_message_text(self, *args, **kwargs)

    Bot.edit_message_text = _patched_edit_message_text

    # Patch Message.reply_text
    orig_reply_text = Message.reply_text

    async def _patched_reply_text(self: Message, *args: Any, **kwargs: Any):
        kwargs.setdefault("disable_web_page_preview", True)
        return await orig_reply_text(self, *args, **kwargs)

    Message.reply_text = _patched_reply_text

    # Patch Message.edit_text
    orig_edit_text = Message.edit_text

    async def _patched_edit_text(self: Message, *args: Any, **kwargs: Any):
        kwargs.setdefault("disable_web_page_preview", True)
        return await orig_edit_text(self, *args, **kwargs)

    Message.edit_text = _patched_edit_text

    # Patch CallbackQuery.edit_message_text
    orig_cb_edit = CallbackQuery.edit_message_text

    async def _patched_cb_edit(self: CallbackQuery, *args: Any, **kwargs: Any):
        kwargs.setdefault("disable_web_page_preview", True)
        return await orig_cb_edit(self, *args, **kwargs)

    CallbackQuery.edit_message_text = _patched_cb_edit
