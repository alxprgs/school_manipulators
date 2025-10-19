from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Final, List

IS_WINDOWS: Final = platform.system() == "Windows"
BASE_DIR:   Final = Path(__file__).resolve().parent.parent

def _detect_data_root() -> Path:
    if env_root := os.getenv("DATA_ROOT"):
        return Path(env_root).expanduser().resolve()
    if IS_WINDOWS:
        return (BASE_DIR / "core" / "data").resolve()
    return Path("/data")

DATA_ROOT: Final = _detect_data_root()

def _mkdir(path: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise PermissionError(
            f"Не удалось создать каталог {path}; "
            "проверьте права или volume-mount Docker-контейнера."
        ) from exc
    except OSError as exc:
        raise OSError(
            f"Не удалось подготовить каталог {path}: {exc}"
        ) from exc
    return path

_WRITABLE_SUBDIRS: Final[List[str]] = ["db", "logs"]
for _sub in _WRITABLE_SUBDIRS:
    _mkdir(DATA_ROOT / _sub)

DB_DIR: Final        = DATA_ROOT / "db"
LOG_DIR: Final       = DATA_ROOT / "logs"

TEMPLATES_DIR: Final = BASE_DIR / "templates"
STATIC_DIR: Final    = BASE_DIR / "static"

DEVICES_JSON: Final =  DATA_ROOT / "devices.json"

if not TEMPLATES_DIR.exists():
    raise RuntimeError(
        f"Каталог шаблонов не найден: {TEMPLATES_DIR}. "
        "Убедитесь, что он существует и корректно смонтирован."
    )
if not STATIC_DIR.exists():
    raise RuntimeError(
        f"Каталог статических файлов не найден: {STATIC_DIR}. "
        "Убедитесь, что он существует и корректно смонтирован."
    )

__all__ = [
    "IS_WINDOWS",
    "BASE_DIR", "DATA_ROOT",
    "DB_DIR", "LOG_DIR",
    "TEMPLATES_DIR", "STATIC_DIR",
    "DEVICES_JSON",
]
