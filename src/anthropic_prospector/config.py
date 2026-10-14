"""Runtime configuration: API keys, model choice and network tunables.

Every value is optional. With nothing set, the CLI runs end-to-end on mock data. Values
come from the environment or a `.env` file in the working directory. Empty values count
as unset, so a copied `.env.example` behaves exactly like no configuration at all.

Domain rules (territory, MEDDPICC weights) are not configuration; they live in models.py.
"""

import os
from pathlib import Path
from typing import Any, Final

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from anthropic_prospector import __version__

DEFAULT_MODEL: Final = "claude-sonnet-5-5"
USER_AGENT: Final = f"anthropic-prospector/{__version__}"


def default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "anthropic-prospector"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PROSPECTOR_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # Third-party variable names are read verbatim, without the PROSPECTOR_ prefix.
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(
        default=DEFAULT_MODEL, min_length=1, validation_alias="ANTHROPIC_MODEL"
    )
    builtwith_api_key: SecretStr | None = Field(default=None, validation_alias="BUILTWITH_API_KEY")
    github_token: SecretStr | None = Field(default=None, validation_alias="GITHUB_TOKEN")

    cache_dir: Path = Field(default_factory=default_cache_dir)
    cache_ttl_hours: float = Field(default=24.0, ge=0)
    http_concurrency: int = Field(default=5, ge=1, le=32)
    per_host_concurrency: int = Field(default=2, ge=1, le=8)
    http_connect_timeout_s: float = Field(default=5.0, gt=0)
    http_read_timeout_s: float = Field(default=15.0, gt=0)

    @field_validator("anthropic_api_key", "builtwith_api_key", "github_token", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: Any) -> Any:
        # A whitespace-only key would otherwise switch the tool into live mode and fail.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("cache_dir")
    @classmethod
    def _expand_home(cls, value: Path) -> Path:
        return value.expanduser()

    @property
    def has_anthropic_key(self) -> bool:
        return self.anthropic_api_key is not None


def env_var_names() -> tuple[str, ...]:
    """Every environment variable Settings reads, in declaration order."""
    prefix = Settings.model_config.get("env_prefix", "")
    names = []
    for name, field in Settings.model_fields.items():
        alias = field.validation_alias
        names.append(alias if isinstance(alias, str) else f"{prefix}{name}".upper())
    return tuple(names)
