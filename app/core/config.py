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
    # Shared secret for write and costly endpoints (X-Admin-Token header).
    # Unset or empty: those endpoints answer 503 instead of running unprotected.
    admin_api_token: str | None = None

    # User sign-in (app/services/auth.py). The cookie holds a random token; the database
    # stores only its SHA-256. Set SESSION_COOKIE_SECURE=true when served over HTTPS.
    session_cookie_name: str = "ainis_session"
    session_ttl_hours: int = Field(default=12, ge=1)
    session_cookie_secure: bool = False
    # scrypt cost; a power of two. Tests lower it so hashing is fast.
    password_scrypt_n: int = Field(default=32768, ge=2)
    # Per username + client address, in memory per process (like the search limiter).
    auth_login_max_failures: int = Field(default=5, ge=1)
    auth_login_window_seconds: int = Field(default=900, ge=1)
    # Registrations per client address per hour (per process).
    auth_register_per_hour: int = Field(default=5, ge=1)

    request_timeout_seconds: float = Field(default=15, gt=0)
    max_feed_items: int = Field(default=50, ge=1)
    max_feed_bytes: int = Field(default=2_000_000, ge=1)
    max_article_content_chars: int = Field(default=20_000, ge=1)

    # AI configuration
    # The model the evaluation snapshot and the search thresholds were made with.
    embedding_model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    ai_min_documents: int = Field(default=10, ge=2)
    ai_batch_size: int = Field(default=500, ge=2)
    duplicate_similarity_threshold: float = Field(default=0.92, ge=0, le=1)
    # Outliers (HDBSCAN's -1 bucket) join the closest topic when at least this similar.
    ai_outlier_min_similarity: float = Field(default=0.75, ge=0, le=1)
    # A new topic reuses a stored topic's label when their centroids are at least this similar.
    ai_topic_match_threshold: float = Field(default=0.9, ge=0, le=1)
    # Editorial categories (JSON list in .env); a topic close enough to one is named after it.
    ai_zeroshot_topics: list[str] = Field(default_factory=list)
    ai_zeroshot_min_similarity: float = Field(default=0.7, ge=0, le=1)

    # A pending/running AI job older than this is treated as dead and no longer blocks new ones.
    ai_job_timeout_seconds: int = Field(default=3600, ge=1)

    # LLM for summaries and answers: any OpenAI-compatible chat API.
    # Default: Gemma on a local Ollama (free). For OpenAI use https://api.openai.com/v1.
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "gemma4"
    llm_api_key: str = "ollama"
    llm_timeout_seconds: float = Field(default=60, gt=0)

    # News search (POST /ai/ask)
    ask_max_sources: int = Field(default=5, ge=1, le=20)
    # Articles less similar than this to the request are not shown at all.
    ask_min_similarity: float = Field(default=0.8, ge=0, le=1)
    # How many of the newest articles are searched.
    ask_max_candidates: int = Field(default=2000, ge=1)
    # Whether /ai/ask accepts a link, which the server then downloads. Turn off for demos
    # where the server must not fetch URLs typed by users.
    ask_allow_links: bool = True

    # Public search (POST /ai/search): requests per client IP per minute (per process),
    # and the largest accepted request body.
    ai_search_rate_per_minute: int = Field(default=30, ge=1)
    # Signed-in users (any role) are counted per user id instead, with this higher limit.
    ai_search_user_rate_per_minute: int = Field(default=120, ge=1)
    ai_search_max_body_bytes: int = Field(default=4096, ge=1)
    # Public search floor, separate from ask_min_similarity (/ai/ask keeps 0.8): an article
    # less similar than this is shown only if it contains a query word. Short queries like
    # "google" reach only about 0.4-0.6 with the embedding model, while random words stay
    # under 0.3 (measured on the 200-article eval set).
    ai_search_min_similarity: float = Field(default=0.5, ge=0, le=1)
    # Load the search code and embedding model in a background thread at startup, so the
    # first search does not wait for it. Off by default (tests, light installs).
    ai_preload_model: bool = False

    # Ingestion downloads the article page when a source only gives a snippet
    # shorter than full_text_min_chars characters.
    ingestion_full_text: bool = True
    full_text_min_chars: int = Field(default=800, ge=0)

    # News API sources (GNews, https://gnews.io). The free plan returns at most 10
    # articles per search and allows about 100 searches a day.
    news_api_key: str | None = None
    news_api_base_url: str = "https://gnews.io/api/v4"
    news_api_max_articles: int = Field(default=10, ge=1, le=100)

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

    @model_validator(mode="after")
    def check_scrypt_cost(self) -> "Settings":
        n = self.password_scrypt_n
        if n & (n - 1) != 0:
            raise ValueError("PASSWORD_SCRYPT_N must be a power of two")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
