"""Pydantic Settings — single source of truth for runtime configuration.

All env-driven config flows through this module. No scattered os.getenv calls.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database — async DSN for the runtime, sync DSN for Alembic.
    database_url: str = "postgresql+asyncpg://aiinfra:aiinfra@postgres:5432/aiinfra"
    database_url_sync: str = (
        "postgresql+psycopg://aiinfra:aiinfra@postgres:5432/aiinfra"
    )
    # Test DB — used only by the integration suite. Defaults to a separate
    # database on the host-mapped Postgres (port 55432, see the compose
    # override) so tests never touch dev data. CI overrides this to its service.
    test_database_url: str = (
        "postgresql+asyncpg://aiinfra:aiinfra@localhost:55432/aiinfra_test"
    )

    # vLLM
    vllm_base_url: str = "http://vllm:8000"
    vllm_model_name: str = "Qwen/Qwen2.5-1.5B-Instruct"
    vllm_timeout_ms: int = 30000

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    # Worker
    worker_poll_interval_ms: int = 500
    worker_batch_claim_size: int = 1

    # Metrics — separate Prometheus scrape ports for gateway and worker.
    metrics_port_gateway: int = 9100
    metrics_port_worker: int = 9101


@lru_cache
def get_settings() -> Settings:
    return Settings()
