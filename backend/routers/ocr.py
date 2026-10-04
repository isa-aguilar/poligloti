"""POST /ocr: photo of a book page -> faithful text (book mode)."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .. import config, ocr
from ..limits import read_upload
from ..services import AIServiceError
from ..sessions import validate_ids

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_IMAGE_BYTES = 12 * 1024 * 1024


@router.post("/ocr")
async def ocr_page(
    user_id: str = Form(...),
    target_language: str = Form(...),
    image: UploadFile = File(...),
) -> dict:
    """Return the page text so the learner can review it before starting the
    session (mode 3, 4 or 8). A local vision model can take tens of seconds."""
    validate_ids(user_id, target_language)
    if not config.AI_VISION_MODEL:
        raise AIServiceError(
            "vision",
            "not_configured",
            "No vision model configured. Set AI_VISION_MODEL to read book pages from a photo.",
        )
    raw = await read_upload(image, _MAX_IMAGE_BYTES, "image")
    if not raw:
        raise HTTPException(400, "empty image")
    t0 = time.perf_counter()
    text = await ocr.transcribe_page(
        raw, image.content_type or "image/jpeg", target_language, user=user_id
    )
    if not text.strip():
        raise HTTPException(422, "could not extract any text from the photo")
    logger.info(
        "[ocr] user=%s lang=%s bytes=%d chars=%d total=%dms",
        user_id,
        target_language,
        len(raw),
        len(text),
        int((time.perf_counter() - t0) * 1000),
    )
    return {"text": text, "chars": len(text)}
