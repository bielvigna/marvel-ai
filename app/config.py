from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


WORKSPACE_ENV = Path(__file__).resolve().parents[2] / ".env"
BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    comic_vine_api_key: str = ""
    ai_provider: str = "openai-compatible"
    ai_model: str = ""
    ai_api_key: str = ""
    ai_base_url: str = ""
    mongodb_uri: str = ""
    marvel_backend_host: str = "0.0.0.0"
    marvel_backend_port: int = 8000

    model_config = SettingsConfigDict(env_file=(WORKSPACE_ENV, BACKEND_ENV), extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
