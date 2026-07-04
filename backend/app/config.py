from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APIFY_", env_file=".env", extra="ignore")

    environment: str = "dev"
    database_url: str = "postgresql+asyncpg://apify:apify@localhost:5432/apify"
    redis_url: str = "redis://localhost:6379/0"

    # Honest identity sent to every target site; override with a real contact in .env.
    user_agent: str = "APIfyBot/0.1 (+contact not configured)"

    page_load_timeout_ms: int = 15_000
    network_quiet_ms: int = 1_500
    max_skeleton_tokens: int = 8_000
    max_html_bytes: int = 2_000_000
    max_xhr_responses: int = 30
    max_xhr_body_bytes: int = 200_000
