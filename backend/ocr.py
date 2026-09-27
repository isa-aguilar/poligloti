"""OCR of book pages with a vision model (mode 8, book).

Photo of a page -> faithful text in the original language, ready to feed mode 3
(guided reading) or mode 4 (read aloud). A small vision-language model is
accurate enough even with a rotated phone photo; expect tens of seconds per
page on local hardware.
"""

from __future__ import annotations

import base64
import re

from . import config
from .services import AIServiceError, llm

_PROMPT = (
    "Faithfully transcribe ALL the text on this book page, in the original "
    "language ({lang_name}). Join words hyphenated at the end of a line. Keep "
    "the paragraphs. Do not include page numbers or stray chapter headers. Do "
    "not translate, do not comment: only the complete text."
)

# Line-break hyphen: "räu-\nme" -> "räume" (only when followed by a word char).
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
# A line that is only a number (page) or leftovers like "82".
_PAGE_NUMBER_LINE = re.compile(r"^\s*\d{1,4}\s*$", re.MULTILINE)


def clean_page_text(raw: str) -> str:
    """OCR post-processing: drop page numbers, join hyphenated breaks and
    collapse line breaks inside paragraphs (the model returns the book's
    physical lines; the teacher wants paragraphs)."""
    text = _PAGE_NUMBER_LINE.sub("", raw)
    text = _HYPHEN_BREAK.sub(lambda m: m.group(1) + m.group(2), text)
    paragraphs = [" ".join(chunk.split()) for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]
    return "\n\n".join(paragraphs)


async def transcribe_page(
    image: bytes, content_type: str, lang: str, user: str | None = None
) -> str:
    """OCR the photo with the vision model. Returns the cleaned text."""
    if not config.AI_VISION_MODEL:
        raise AIServiceError(
            "vision",
            "not_configured",
            "Page photos need a vision model: set AI_VISION_MODEL.",
        )
    lang_name = config.LANG_NAMES.get(lang, lang)
    b64 = base64.b64encode(image).decode()
    mime = content_type if content_type.startswith("image/") else "image/jpeg"
    raw = await llm.chat(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _PROMPT.format(lang_name=lang_name)},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ],
        temperature=0.1,
        max_tokens=config.OCR_MAX_TOKENS,
        model=config.AI_VISION_MODEL,
        user=user,
    )
    return clean_page_text(raw.strip())
