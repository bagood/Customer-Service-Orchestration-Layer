"""Environment-based application configuration."""

from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    server_name: str = "Python MCP Template"
    allowed_hosts: list[str] = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    allowed_origins: list[str] = [
        "http://127.0.0.1:*",
        "http://localhost:*",
        "http://[::1]:*",
    ]
    llm_base_url: AnyHttpUrl | None = None
    llm_model: str | None = Field(default=None, min_length=1)
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=20, gt=0, le=120)
    llm_response_format: Literal["json_object", "json_schema"] = "json_object"
