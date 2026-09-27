"""Progress dashboard: /progress/<user>/<lang> and /memory/<user>/<lang>/progress."""

from __future__ import annotations

import hashlib
import json
import logging

from fastapi import APIRouter

from .. import config, llm_parse, memory
from ..cefr import levelup_eligible, next_cefr
from ..schemas import ProgressData
from ..services import llm
from ..sessions import validate_ids

logger = logging.getLogger(__name__)

router = APIRouter()

_UI_LANG_NAMES = config.UI_LANG_NAMES

# In-process cache of the progress dashboard translations. Key (user, lang, ui)
# -> {"h": hash of the source content, "data": (focus, milestones, active, resolved, reviews)}.
# Avoids translating on every load; invalidated when the content changes, emptied on restart.
_PROGRESS_I18N_CACHE: dict = {}


# ---------------------------------------------------------------------------
# /memory/<user>/<lang>/progress  (raw read, for debugging)
# ---------------------------------------------------------------------------
@router.get("/memory/{user}/{lang}/progress")
def get_progress(user: str, lang: str) -> dict:
    validate_ids(user, lang)
    return {
        "user": user,
        "lang": lang,
        "progress": memory.read_progress_tail(user, lang, n=10_000),
        "vocab": memory.read_vocab(user, lang),
    }


# ---------------------------------------------------------------------------
# /progress/<user>/<lang>  (data for the "My progress" screen, mode 6)
# ---------------------------------------------------------------------------
async def _translate_progress(
    ui: str, focus, milestones, active, resolved, reviews, user: str | None = None
):
    """Translate the dashboard texts (focus, milestones, errors, weekly reviews)
    into the UI language with a single chat call. The content is generated and
    stored in the support language; this localizes it for display. On failure the
    caller uses the originals."""
    target = _UI_LANG_NAMES.get(ui, ui)
    payload = {
        "focus": focus,
        "milestones": milestones,
        "active_errors": active,
        "resolved_errors": resolved,
        "weekly_reviews": [r.get("text", "") for r in reviews],
    }
    instruction = (
        f"Translate into {target} ALL the texts of this JSON (teaching notes about a "
        "language learner's progress). Keep EXACTLY the same structure and the same "
        "number of items in every list. Do not translate example words or phrases in "
        "the language the learner studies if they are in quotes. "
        "Answer ONLY with the translated JSON object, no extra text and no ```."
    )
    raw = await llm.chat(
        [
            {"role": "system", "content": instruction},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.1,
        max_tokens=900,
        output="json",
        user=user,
    )
    data = llm_parse.extract_json_object(raw)
    if not isinstance(data, dict):
        return focus, milestones, active, resolved, reviews

    def _lst(value, fallback):
        if isinstance(value, list):
            out = [str(x).strip() for x in value if str(x).strip()]
            return out if out else fallback
        return fallback

    new_focus = str(data.get("focus") or "").strip() or focus
    new_ms = _lst(data.get("milestones"), milestones)
    new_act = _lst(data.get("active_errors"), active)
    new_res = _lst(data.get("resolved_errors"), resolved)
    rev_texts = data.get("weekly_reviews")
    new_rev = reviews
    if isinstance(rev_texts, list) and len(rev_texts) == len(reviews):
        new_rev = [
            {"week": r["week"], "text": (str(t).strip() or r.get("text", ""))}
            for r, t in zip(reviews, rev_texts, strict=False)
        ]
    return new_focus, new_ms, new_act, new_res, new_rev


@router.get("/progress/{user}/{lang}", response_model=ProgressData)
async def progress_dashboard(user: str, lang: str, ui: str | None = None):
    validate_ids(user, lang)
    ui = ui or config.SUPPORT_LANG
    tr = memory.read_skill_tracker(user, lang)
    cur = memory.read_curriculum(user, lang)
    cefr = tr["cefr"] or memory.read_user_cefr(user, lang)
    vals = [v for v in tr["scores"].values() if isinstance(v, int)]
    avg = round(sum(vals) / len(vals)) if vals else 0
    focus = cur["focus"]
    milestones = cur["milestones"]
    active = tr["active_errors"]
    resolved = tr["resolved_errors"]
    reviews = memory.list_weekly_reviews(user, lang)
    # Localize the content (generated in the support language) into the UI language.
    if ui in _UI_LANG_NAMES and ui != config.SUPPORT_LANG and tr["exists"]:
        src = json.dumps(
            [focus, milestones, active, resolved, [r.get("text", "") for r in reviews]],
            ensure_ascii=False,
        )
        h = hashlib.sha1(src.encode("utf-8")).hexdigest()
        ckey = (user, lang, ui)
        cached = _PROGRESS_I18N_CACHE.get(ckey)
        if cached and cached["h"] == h:
            focus, milestones, active, resolved, reviews = cached["data"]
        else:
            try:
                focus, milestones, active, resolved, reviews = await _translate_progress(
                    ui, focus, milestones, active, resolved, reviews, user=user
                )
                _PROGRESS_I18N_CACHE[ckey] = {
                    "h": h,
                    "data": (focus, milestones, active, resolved, reviews),
                }
            except Exception:
                logger.exception("[progress-i18n] translation failed; returning the original")
    return {
        "user": user,
        "lang": lang,
        "has_data": tr["exists"],
        # Not the same as has_data: a tracker can exist without an assessment.
        # The screen uses it to offer "take" or "retake" the assessment.
        "has_assessment": memory.has_assessment(user, lang),
        "cefr": cefr,
        "next_cefr": next_cefr(cefr),
        "target_cefr": cur["target_cefr"],
        "avg_score": avg,
        "levelup_eligible": levelup_eligible(tr["scores"]),
        "dims": [
            {"key": k, "label": label, "score": tr["scores"].get(k)}
            for k, label in config.SKILL_DIMS
        ],
        "active_errors": active,
        "resolved_errors": resolved,
        "focus": focus,
        "milestones": milestones,
        "weekly_reviews": reviews,
        "expressions_count": memory.count_expressions(user, lang),
        # Time series of the 8 dimensions, oldest first. Only entries that carry
        # scores are included: the curve starts there and the past is not invented.
        "history": memory.read_skill_history(user, lang),
        "updated": tr["updated"],
    }
