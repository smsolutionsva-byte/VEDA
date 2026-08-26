"""VEDA application entry point."""
from __future__ import annotations

import contextlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, jobs
from .api.routes import router


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    db.init_db()
    jobs.start_worker()
    yield
    with contextlib.suppress(Exception):
        from .mcpc import horizun
        horizun.close()


app = FastAPI(title="VEDA",
              description="Agent-Native Construction Project Intelligence Platform",
              version="1.0.0", lifespan=lifespan)

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


def run() -> None:
    import uvicorn
    uvicorn.run("veda.main:app", host=config.HOST, port=config.PORT,
                log_level="info", reload=False)


if __name__ == "__main__":
    run()
