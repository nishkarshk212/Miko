from __future__ import annotations

import re
from typing import Optional, Dict, Any
from telegram import InlineKeyboardButton

# Mapping from Unicode small caps to ASCII lowercase
SMALL_TO_NORMAL: Dict[str, str] = {
    'ᴀ': 'a', 'ʙ': 'b', 'ᴄ': 'c', 'ᴅ': 'd', 'ᴇ': 'e', 'ꜰ': 'f',
    'ɢ': 'g', 'ʜ': 'h', 'ɪ': 'i', 'ᴊ': 'j', 'ᴋ': 'k', 'ʟ': 'l',
    'ᴍ': 'm', 'ɴ': 'n', 'ᴏ': 'o', 'ᴘ': 'p', 'Q': 'q', 'ʀ': 'r',
    'ꜱ': 's', 'ᴛ': 't', 'ᴜ': 'u', 'ᴠ': 'v', 'ᴡ': 'w', 'x': 'x',
    'ʏ': 'y', 'ᴢ': 'z'
}

# Mapping from ASCII lowercase to Unicode small caps
NORMAL_TO_SMALL: Dict[str, str] = {
    'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ꜰ',
    'g': 'ɢ', 'h': 'ʜ', 'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ',
    'm': 'ᴍ', 'n': 'ɴ', 'o': 'ᴏ', 'p': 'ᴘ', 'q': 'Q', 'r': 'ʀ',
    's': 'ꜱ', 't': 'ᴛ', 'u': 'ᴜ', 'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x',
    'y': 'ʏ', 'z': 'ᴢ'
}

DANGER_KEYWORDS = [
    'cancel', 'close', 'stop', 'end', 'delete', 'remove', 'ban',
    'kick', 'mute', 'disable', 'demote', 'reject', 'decline', 'leave',
    'off', 'unwarn', 'reset', 'exit', 'no', 'deny', 'disallow'
]

SUCCESS_KEYWORDS = [
    'pay', 'verify', 'join', 'start', 'buy', 'enable', 'accept',
    'claim', 'confirm', 'approve', 'unlock', 'add', 'on', 'deposit',
    'collect', 'win', 'vote', 'continue', 'yes', 'allow', 'agree'
]


def to_name_style(text: str) -> str:
    """
    Transforms button text to Nᴀᴍᴇ style:
    - Capitalized first letter in standard Latin.
    - Subsequent letters in Unicode small caps.
    - Strips all emojis, pictographs, symbols and punctuation.
    """
    if not text:
        return text

    # Convert any existing small caps back to ASCII
    plain = ''.join(SMALL_TO_NORMAL.get(c, c) for c in str(text))

    # Strip emojis and supplementary symbols
    cleaned = re.sub(r'[\U00010000-\U0010ffff]', '', plain)
    # Strip symbols and pictographs, arrows, geometric shapes, variation selectors
    cleaned = re.sub(r'[\u2000-\u32ff]', '', cleaned)
    cleaned = re.sub(r'[\ufe00-\ufe0f]', '', cleaned)
    cleaned = re.sub(r'[\u00ab\u00bb\u2039\u203a]', '', cleaned)
    # Strip ASCII punctuation and symbols except alphanumerics
    cleaned = re.sub(r'[\u0021-\u002f\u003a-\u0040\u005b-\u0060\u007b-\u007e]', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    if not cleaned:
        cleaned = plain.strip()

    words = cleaned.split(' ')
    out = []
    for w in words:
        if not w:
            continue
        first = w[0].upper()
        rest = ''.join(NORMAL_TO_SMALL.get(c.lower(), c) for c in w[1:])
        out.append(first + rest)

    return ' '.join(out) or str(text)


def get_button_style(text: str) -> str:
    """
    Infers the native Telegram button style enum:
    - danger (Red)
    - success (Green)
    - primary (Theme Blue)
    """
    plain = ''.join(SMALL_TO_NORMAL.get(c, c) for c in str(text)).lower()
    for kw in DANGER_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', plain):
            return "danger"
    for kw in SUCCESS_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', plain):
            return "success"
    # Fallback substring match if word boundary not found
    for kw in DANGER_KEYWORDS:
        if kw in plain:
            return "danger"
    for kw in SUCCESS_KEYWORDS:
        if kw in plain:
            return "success"
    return "primary"


_ORIG_INIT = InlineKeyboardButton.__init__
_IS_PATCHED = False


def patch_inline_keyboard_button() -> None:
    """
    Monkey-patches telegram.InlineKeyboardButton so that every button created
    anywhere in the application automatically has:
    1. Text formatted in Nᴀᴍᴇ small caps style without symbols.
    2. Coloured button style ('primary', 'danger', or 'success') injected via api_kwargs.
    """
    global _IS_PATCHED
    if _IS_PATCHED:
        return
    _IS_PATCHED = True

    def _patched_init(self: InlineKeyboardButton, text: str, *args, **kwargs):
        # Format text to Nᴀᴍᴇ style
        styled_text = to_name_style(text)

        api_kwargs = kwargs.get("api_kwargs")
        if api_kwargs is None:
            api_kwargs = {}
            kwargs["api_kwargs"] = api_kwargs
        elif not isinstance(api_kwargs, dict):
            api_kwargs = dict(api_kwargs)
            kwargs["api_kwargs"] = api_kwargs

        if "style" not in api_kwargs:
            api_kwargs["style"] = get_button_style(text)

        _ORIG_INIT(self, styled_text, *args, **kwargs)

    InlineKeyboardButton.__init__ = _patched_init
