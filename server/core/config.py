from __future__ import annotations

from typing import Final
from pathlib import Path
from dotenv import load_dotenv
from pydantic import EmailStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

env_path = Path(__file__).resolve().parents[2] / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)

COMMON_CONFIG = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    case_sensitive=False,
    extra="ignore",
)

class BaseAppSettings(BaseSettings):
    DEV: bool = Field(True)
    DEVICE_SECRET: str = Field(...)
    model_config = COMMON_CONFIG

class WebServerSettings(BaseAppSettings):
    DOMAIN_WITHOUT_WWW: str = Field("asfes.ru")
    DOMAIN: str = Field("manipulators.school.asfes.ru")

class LocalServerSettings(BaseAppSettings):
    MailPunishment: bool = Field(True)
    DOMAIN_WITHOUT_WWW: str = Field("localhost")

work_type = os.getenv("WORK_TYPE")
if work_type == "WebServer":
    settings: Final = WebServerSettings()
elif work_type == "LocalServer":
    settings: Final = LocalServerSettings()
else:
    settings: Final = BaseAppSettings()

class MailSettings(BaseSettings):
    MAIL_USERNAME: EmailStr = Field(
        default_factory=lambda: f"schoolmanipulators@asfes.ru"
    )
    MAIL_FROM: EmailStr = Field(
        default_factory=lambda: f"schoolmanipulators@asfes.ru"
    )

    MAIL_PORT_IMAP: int = Field(993, ge=1, le=65535)
    MAIL_PORT_SMTP: int = Field(465, ge=1, le=65535)

    MAIL_SERVER_IMAP: str = Field(
        default_factory=lambda: f"mail.asfes.ru"
    )
    MAIL_SERVER_SMTP: str = Field(
        default_factory=lambda: f"mail.asfes.ru"
    )

    MAIL_SSL: bool = Field(True)
    MAIL_PASSWORD: str = Field(..., min_length=6)

    model_config = COMMON_CONFIG

mail_settings: Final = MailSettings()
