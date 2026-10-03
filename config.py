"""
Morning Gazette Configuration Module.

Loads and validates application settings using pydantic-settings.
Follows the zero-leakage principle and strict environment separation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Union
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Google Gemini Settings
    GEMINI_API_KEY: Optional[str] = Field(
        default=None,
        description="Google Gemini API key. If not provided, fallback summarizer is used.",
    )
    GEMINI_MODEL: str = Field(
        default="gemini-3.8-flash",
        description="Gemini model identifier for structured JSON summarization.",
    )

    # SMTP Configuration (Gmail API is strictly prohibited)
    SMTP_HOST: str = Field(
        default="smtp.example.com",
        description="Standard SMTP server hostname.",
    )
    SMTP_PORT: int = Field(
        default=587,
        description="SMTP server port (e.g. 587 for STARTTLS, 465 for SSL).",
    )
    SMTP_USER: str = Field(
        default="",
        description="SMTP authentication username.",
    )
    SMTP_PASSWORD: str = Field(
        default="",
        description="SMTP authentication password.",
    )
    SMTP_USE_TLS: bool = Field(
        default=True,
        description="Upgrade connection with STARTTLS.",
    )
    SMTP_USE_SSL: bool = Field(
        default=False,
        description="Use direct SSL/TLS connection.",
    )
    SENDER_EMAIL: str = Field(
        default="editor@morninggazette.internal",
        description="Sender email address appearing in the From header.",
    )
    RECIPIENT_EMAILS: Union[List[str], str] = Field(
        default_factory=lambda: ["reader@example.com"],
        description="List of recipient email addresses.",
    )

    # Network & Resilience Parameters
    REQUEST_TIMEOUT: float = Field(
        default=10.0,
        description="External HTTP request timeout in seconds (maximum 10.0s).",
    )
    MAX_RETRIES: int = Field(
        default=3,
        description="Exponential backoff retry count for LLM API calls.",
    )

    # Logging and Output
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Application logging verbosity.",
    )
    DIST_DIR: Path = Field(
        default=Path("dist"),
        description="Directory for generated preview HTML files.",
    )

    @field_validator("RECIPIENT_EMAILS", mode="before")
    @classmethod
    def parse_recipient_emails(cls, value: object) -> List[str]:
        """Convert comma-separated string to list of trimmed strings."""
        if isinstance(value, str):
            return [email.strip() for email in value.split(",") if email.strip()]
        if isinstance(value, (list, tuple)):
            return [str(email).strip() for email in value if str(email).strip()]
        return []

    @field_validator("REQUEST_TIMEOUT")
    @classmethod
    def validate_request_timeout(cls, value: float) -> float:
        """Enforce maximum timeout limit of 10.0 seconds according to specifications."""
        if value > 10.0:
            return 10.0
        if value <= 0:
            return 1.0
        return value


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structured logging across the application."""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


# Singleton getter
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Retrieve or instantiate cached application settings."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
