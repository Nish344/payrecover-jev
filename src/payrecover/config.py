from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DiagnosisProvider = Literal["auto", "rules", "jev", "gemini", "keyword"]


class Settings(BaseSettings):
    """Env-backed settings. Keys never have defaults; secrets stay wrapped."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    razorpay_key_id: str
    razorpay_key_secret: SecretStr
    gemini_api_key: SecretStr = SecretStr("")
    llm_model: str = "gemini-3.5-flash-lite"
    openrouter_api_key: SecretStr = SecretStr("")
    jev_model: str = "typesafe/jev-1.14"
    jev_base_url: str = "https://openrouter.ai/api/v1/systemone"
    jev_timeout_seconds: float = Field(default=30.0, gt=0)
    jev_read_retries: int = Field(default=3, ge=1, le=5)
    diagnosis_provider: DiagnosisProvider = "auto"
    kill_switch: bool = False
    razorpay_timeout_seconds: float = Field(default=10.0, gt=0)
    razorpay_read_retries: int = Field(default=3, ge=1, le=5)
    db_path: Path = Path("data/payrecover.db")

    @field_validator("razorpay_key_id")
    @classmethod
    def _strip_key_id(cls, value: str) -> str:
        return value.strip()

    @field_validator("jev_base_url")
    @classmethod
    def _strip_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
