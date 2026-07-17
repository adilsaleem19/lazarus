from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # populate_by_name: fields with a validation_alias (the API keys) must still be
    # settable as Settings(groq_api_key=...) — tests rely on it, and without this
    # pydantic silently drops the kwarg (masked locally by .env, exposed on CI).
    model_config = SettingsConfigDict(
        env_prefix="LAZARUS_", env_file=".env", extra="ignore", populate_by_name=True
    )

    environment: str = "dev"
    database_url: str = "postgresql+asyncpg://lazarus:lazarus@localhost:5432/lazarus"
    redis_url: str = "redis://localhost:6379/0"

    # Honest identity sent to every target site; override with a real contact in .env.
    user_agent: str = "LazarusBot/0.1 (+contact not configured)"

    page_load_timeout_ms: int = 15_000
    network_quiet_ms: int = 1_500
    max_skeleton_tokens: int = 8_000
    max_html_bytes: int = 2_000_000
    max_xhr_responses: int = 30
    max_xhr_body_bytes: int = 200_000

    # --- Phase 2: agent / LLM ---
    llm_provider: str = "groq"  # groq | gemini (the other is fallback if its key is set)
    # API keys use their conventional unprefixed names as well as LAZARUS_GROQ_API_KEY.
    groq_api_key: str = Field(
        default="", validation_alias=AliasChoices("LAZARUS_GROQ_API_KEY", "GROQ_API_KEY")
    )
    gemini_api_key: str = Field(
        default="", validation_alias=AliasChoices("LAZARUS_GEMINI_API_KEY", "GEMINI_API_KEY")
    )
    # Free-tier models churn: llama-4-scout was decommissioned 2026-07. gpt-oss-120b
    # is the strongest coder currently free on Groq (1K req/day, 8K tokens/min) and
    # keeps its reasoning out of `content`, so responses stay parseable JSON.
    groq_model: str = "openai/gpt-oss-120b"
    gemini_model: str = "gemini-2.0-flash"
    job_token_budget: int = 60_000
    max_repairs: int = 4
    sandbox_timeout_s: int = 10
    # Virtual-address-space ceiling (RLIMIT_AS). Kept generous: a tighter cap can
    # stop CPython+selectolax from even booting, and there is no mem-exhaustion path
    # that needs a tight bound — the real backstop is the wall-clock timeout.
    sandbox_memory_mb: int = 1024

    @property
    def llm_configured(self) -> bool:
        return bool(self.groq_api_key or self.gemini_api_key)

    # --- Phase 3: live API fabric ---
    max_active_extractors: int = 20
    jobs_per_hour_per_ip: int = 3
    jobs_per_hour_global: int = 30
    # Comma-separated hostnames/IPs that must never be scrape targets
    # (put your own VPS hostname and public IP here in production).
    deny_hosts: str = ""

    @property
    def deny_hosts_set(self) -> frozenset[str]:
        return frozenset(h.strip().lower() for h in self.deny_hosts.split(",") if h.strip())
