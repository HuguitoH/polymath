from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application configuration, loaded from the project-root .env."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        extra="ignore",
    )

    db_password: str
    db_user: str = "polymath"
    db_name: str = "polymath"
    db_host: str = "localhost"
    db_port: int = 5432

    ollama_base_url: str = "http://localhost:11434"
    model: str = "deepseek/deepseek-chat"
    model_is_local: bool = False
    local_model: str = "qwen3:4b-instruct"
    reasoning_model: str = "qwen3:4b"
    embedding_model: str = "bge-m3"
    tts_voice: str = "af_bella"

    audio_dir: Path = Path("/srv/fast/audio")
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    frontier_model: str = "anthropic/claude-sonnet-4-5"

    @property
    def database_url(self) -> str:
        """Postgres DSN. The password is percent-encoded, not concatenated raw."""
        pwd = quote_plus(self.db_password)
        return f"postgresql://{self.db_user}:{pwd}@{self.db_host}:{self.db_port}/{self.db_name}"
