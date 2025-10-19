from __future__ import annotations

import os
import sys
import asyncio
import logging
import uvicorn
from server.core.config import settings


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


async def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = _env_int("PORT", 54327)
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    app_path = os.getenv("APP_PATH", "server:app")

    reload_enabled = bool(int(os.getenv("RELOAD", "1"))) if settings.DEV else False

    config = uvicorn.Config(
        app_path,
        host=host,
        port=port,
        reload=reload_enabled,
        log_level=log_level,
        proxy_headers=True,
        forwarded_allow_ips="*",
        lifespan="on",
    )

    if os.getenv("UVLOOP", "1") != "0":
        try:
            import uvloop  # type: ignore
            config.loop = "uvloop"
        except Exception:
            if os.name == "nt":
                print("uvloop не поддерживается на Windows - используется стандартный asyncio.")
            else:
                print("uvloop не удалось подключить - продолжение без него.")

    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nСервер остановлен пользователем.")
        sys.exit(0)
    except Exception as e:
        print(f"Ошибка при запуске: {e}")
        sys.exit(1)
