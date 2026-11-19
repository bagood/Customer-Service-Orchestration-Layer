"""Environment-based application configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MCP_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    server_name: str = "Python MCP Template"
    allowed_hosts: list[str] = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    allowed_origins: list[str] = [
        "http://127.0.0.1:*",
        "http://localhost:*",
        "http://[::1]:*",
    ]
