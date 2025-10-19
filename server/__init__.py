from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from server.core.config import settings
from server.core.paths import STATIC_DIR, TEMPLATES_DIR
from server.core.LoggingModule import logger
from server.core.WebSocketManager import WebSocketManager
from server.core.functions.auth import init_devices_cache

manager = WebSocketManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.logger = logger
    await init_devices_cache()
    asyncio.create_task(manager._cleanup_task())
    yield
    await manager.shutdown()

app = FastAPI(
    title="Сервер учебных робототехнических ячеек",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEV else None,
    redoc_url="/redoc" if settings.DEV else None,
    openapi_url="/api/v1/openapi.json" if settings.DEV else None,
    debug=settings.DEV,
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=TEMPLATES_DIR)

from server.routes import main_websocket  