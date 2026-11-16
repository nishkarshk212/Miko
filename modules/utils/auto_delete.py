"""
Auto-delete helper module.
Automatically deletes bot replies and user command messages in group chats after 10 seconds,
keeping group chats clean and spam-free.
"""
from __future__ import annotations

import os
import asyncio
from typing import Any, Callable, Coroutine
from telegram import Message

AUTO_DELETE_DELAY = int(os.getenv("AUTO_DELETE_DELAY", "10"))
_PATCHED = False


def schedule_auto_delete(
    sent_msg: Any,
    trigger_msg: Any = None,
    delay: int = AUTO_DELETE_DELAY,
) -> None:
    """Manually schedules an auto-delete task for any message."""
    async def _worker():
        await asyncio.sleep(delay)
        try:
            if sent_msg:
                await sent_msg.delete()
        except Exception:
            pass
        try:
            if trigger_msg and trigger_msg.chat and trigger_msg.chat.type in ("group", "supergroup"):
                await trigger_msg.delete()
        except Exception:
            pass

    asyncio.create_task(_worker())


def setup_auto_delete(delay: int = AUTO_DELETE_DELAY) -> None:
    """
    Patches telegram.Message reply methods so that any bot reply in a group/supergroup
    automatically deletes itself and the user's trigger message after `delay` seconds.
    To prevent deletion on a specific message (e.g. an active game board), pass `auto_delete=False`.
    """
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True

    methods = [
        "reply_text",
        "reply_photo",
        "reply_animation",
        "reply_video",
        "reply_audio",
        "reply_document",
        "reply_voice",
        "reply_sticker",
    ]

    for method_name in methods:
        orig = getattr(Message, method_name, None)
        if not orig:
            continue

        def _make_wrapper(original_method: Callable[..., Coroutine[Any, Any, Message]]):
            async def wrapped(self: Message, *args, **kwargs):
                auto_del = kwargs.pop("auto_delete", True)
                custom_delay = kwargs.pop("delete_after", delay)
                if method_name in ("reply_text", "reply_html", "reply_markdown", "reply_markdown_v2"):
                    kwargs.setdefault("disable_web_page_preview", True)

                sent_msg = await original_method(self, *args, **kwargs)

                # Only auto-delete in group / supergroup chats
                is_group = bool(self.chat and self.chat.type in ("group", "supergroup"))
                if is_group and auto_del:
                    schedule_auto_delete(sent_msg, trigger_msg=self, delay=custom_delay)

                return sent_msg

            return wrapped

        setattr(Message, method_name, _make_wrapper(orig))
