from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    app_name: str = "AI News Intelligence API"
    app_env: Literal["development", "testing", "production"] = "development"
    database_url: str = "postgresql+psycopg://news:news@localhost:5432/news"
    # When postgres_host is set (Docker Compose), it takes precedence over database_url.
    postgres_host: str | None = None
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_user: str = "news"
    postgres_password: str | None = None
    postgres_db: str = "news"
    api_v1_prefix: str = "/api/v1"
    request_timeout_seconds: float = Field(default=15, gt=0)
    max_feed_items: int = Field(default=50, ge=1)
    max_feed_bytes: int = Field(default=2_000_000, ge=1)
    max_article_content_chars: int = Field(default=20_000, ge=1)

    # AI configuration
    embedding_model_name: str = (
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    ai_min_documents: int = Field(default=10, ge=2)
    ai_batch_size: int = Field(default=500, ge=2)
    duplicate_similarity_threshold: float = Field(default=0.92, ge=0, le=1)

    # Article content extraction
    article_max_download_bytes: int = Field(default=5_000_000, ge=1)
    article_max_redirects: int = Field(default=3, ge=0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def build_database_url_from_parts(self) -> "Settings":
        # Compose sets POSTGRES_HOST so the URL is built here with proper escaping;
        # interpolating a raw password into a URL breaks on characters like @ : / # %.
        if self.postgres_host:
            if not self.postgres_password:
                raise ValueError("POSTGRES_PASSWORD is required when POSTGRES_HOST is set")
            self.database_url = URL.create(
                "postgresql+psycopg",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                database=self.postgres_db,
            ).render_as_string(hide_password=False)
        return self

    @model_validator(mode="after")
    def check_ai_limits(self) -> "Settings":
        if self.ai_batch_size < self.ai_min_documents:
            raise ValueError("AI_BATCH_SIZE must be >= AI_MIN_DOCUMENTS")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
