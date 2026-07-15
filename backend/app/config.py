from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LAZARUS_", env_file=".env", extra="ignore")

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
    # llama-4-scout: 30K TPM / 500K TPD / 1K RPD free — far roomier than 70b's 100K TPD.
    groq_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
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
