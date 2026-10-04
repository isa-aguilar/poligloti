"""FastAPI app: joins speech-to-text, the chat model, text-to-speech and memory.

This module only assembles the app: CORS, /health, AI error handling, static
files (/audio and the built frontend), the session sweeper and the routers.
The teaching logic lives in teacher.py, post_session.py, sessions.py and
backend/routers/.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, config, sessions
from .limits import BodySizeLimitMiddleware
from .routers import books as books_router
from .routers import history as history_router
from .routers import ocr as ocr_router
from .routers import progress as progress_router
from .routers import session as session_router
from .routers import srs as srs_router
from .routers import stories as stories_router
from .routers import suggestion as suggestion_router
from .routers import syllabus as syllabus_router
from .routers import turn as turn_router
from .schemas import HealthResult
from .services import AIServiceError, status

# uvicorn only configures its own loggers; make backend.* print INFO too.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    probe = asyncio.create_task(status.safe_probe())
    sweeper = asyncio.create_task(sessions.expire_stale_sessions_loop())
    yield
    for task in (probe, sweeper):
        task.cancel()


app = FastAPI(title="poligloti", version=__version__, lifespan=lifespan)

# First of all: an oversized request is rejected before it is parsed.
app.add_middleware(BodySizeLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AIServiceError)
async def _ai_error(_: Request, exc: AIServiceError) -> JSONResponse:
    """A missing or failing AI service is never a 500: it is a clear, typed error."""
    # bad_audio is the learner's recording, not a failing service.
    status_code = {"unsupported": 501, "bad_audio": 422}.get(exc.code, 503)
    return JSONResponse(
        status_code=status_code,
        content={"detail": exc.message, "service": exc.service, "code": exc.code},
    )


config.AUDIO_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=str(config.AUDIO_ROOT)), name="audio")
sessions.sweep_stale_audio()


@app.get("/health", response_model=HealthResult)
async def health(deep: bool = False) -> dict:
    """Service status. Without `deep` it reports the last probe (cheap enough for a
    container health check); with `deep=1` it probes every service again first."""
    if deep:
        await status.probe()
    services = status.snapshot()
    return {
        "status": status.overall(services),
        "version": __version__,
        "services": services,
        "active_sessions": len(sessions.SESSIONS),
    }


app.include_router(session_router.router)
app.include_router(turn_router.router)
app.include_router(progress_router.router)
app.include_router(srs_router.router)
app.include_router(stories_router.router)
app.include_router(ocr_router.router)
app.include_router(books_router.router)
app.include_router(suggestion_router.router)
app.include_router(syllabus_router.router)
app.include_router(history_router.router)


# ---------------------------------------------------------------------------
# Built frontend (single-page app). Registered LAST so the catch-all route does
# not shadow the API or /audio. Only active if the build exists.
# ---------------------------------------------------------------------------
if config.FRONTEND_DIST.is_dir():
    _ASSETS = config.FRONTEND_DIST / "assets"
    if _ASSETS.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_ASSETS)), name="assets")
    _DIST = config.FRONTEND_DIST.resolve()
    _INDEX = _DIST / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        """Serve build files if they exist, index.html otherwise (client routes)."""
        if full_path:
            candidate = (_DIST / full_path).resolve()
            if candidate.is_file() and _DIST in candidate.parents:
                return FileResponse(candidate)
        return FileResponse(_INDEX)

    logger.info("[static] serving the frontend from %s", _DIST)
