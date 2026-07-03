from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_",
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(default="sqlite:///./data/agent.db")
    log_level: str = Field(default="INFO")

    # Local data root (datasets + parquet + audit log). Referenced by the
    # dataset store; kept here so all slices share one setting.
    data_dir: str = Field(default="data")

    # LLM provider — this project standardises on Gemini Flash. Left as an
    # explicit default (not blank auto-detect) so that a machine which also
    # has an Anthropic key in .env still resolves to Gemini for the agent.
    llm_provider: str = Field(default="gemini")   # "anthropic" | "gemini"
    llm_model: str = Field(default="")            # uses provider default (gemini-3.5-flash) when blank

    # Provider keys
    anthropic_api_key: str = Field(default="")
    gemini_api_key: str = Field(default="")

    # Dataset / upload limits
    sample_rows: int = Field(default=5)        # AGENT_SAMPLE_ROWS — max rows ever shown to the LLM
    max_upload_mb: int = Field(default=100)    # AGENT_MAX_UPLOAD_MB — reject larger uploads

    # Agent loop bound
    max_steps: int = Field(default=3)          # AGENT_MAX_STEPS — write_code/execute retries

    # Sandbox resource limits
    sandbox_timeout_s: int = Field(default=30)    # AGENT_SANDBOX_TIMEOUT_S
    sandbox_mem_mb: int = Field(default=2048)     # AGENT_SANDBOX_MEM_MB


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
