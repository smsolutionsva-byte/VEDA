"""VEDA application entry point."""
from __future__ import annotations

import contextlib
import threading

from fastapi import FastAPI

from . import __version__
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, jobs
from .api.routes import router


def _warm_reasoning_runtime() -> None:
    """Pay optional ML import/model-load cost while the operator sets up work."""
    with contextlib.suppress(Exception):
        from .retrieval import embeddings
        embeddings.get_backend()
    with contextlib.suppress(Exception):
        from .resolution import meta_router
        meta_router.warmup_models()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    db.init_db()
    jobs.start_worker()
    threading.Thread(target=_warm_reasoning_runtime, daemon=True,
                     name="veda-retrieval-warmup").start()
    yield
    with contextlib.suppress(Exception):
        from .mcpc import horizun
        horizun.close()


app = FastAPI(title="VEDA",
              description="Agent-Native Construction Project Intelligence Platform",
              version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(router)

if config.WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(config.WEB_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(config.WEB_DIR / "index.html"))


@app.get("/favicon.ico")
def favicon():
    return FileResponse(str(config.WEB_DIR / "favicon.svg"))


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(str(config.WEB_DIR / "manifest.webmanifest"),
                        media_type="application/manifest+json")


@app.get("/service-worker.js")
def service_worker():
    return FileResponse(str(config.WEB_DIR / "service-worker.js"),
                        media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/",
                                 "Cache-Control": "no-cache"})


def run() -> None:
    import uvicorn
    uvicorn.run("veda.main:app", host=config.HOST, port=config.PORT,
                log_level="info", reload=False)


if __name__ == "__main__":
    run()
