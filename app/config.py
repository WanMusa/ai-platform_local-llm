"""Environment-driven settings.

Every setting can be overridden with an environment variable (see .env.example).
"""

import os
from dataclasses import dataclass
from functools import lru_cache


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    # API auth
    api_token: str

    # Model backend (OpenAI-compatible /chat/completions)
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_timeout_seconds: float
    llm_json_mode: bool

    # Input limits
    max_input_chars: int

    # Profile tuning
    extract_job_temperature: float
    extract_job_max_tokens: int
    hermes_helper_temperature: float
    hermes_helper_max_tokens: int


def load_settings() -> Settings:
    return Settings(
        api_token=os.getenv("LOCAL_LLM_API_TOKEN", ""),
        llm_base_url=os.getenv("LLM_BASE_URL", "http://ollama:11434/v1").rstrip("/"),
        llm_model=os.getenv("LLM_MODEL", "gemma3:4b"),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_timeout_seconds=_env_float("LLM_TIMEOUT_SECONDS", 120.0),
        llm_json_mode=_env_bool("LLM_JSON_MODE", False),
        max_input_chars=_env_int("MAX_INPUT_CHARS", 24000),
        extract_job_temperature=_env_float("EXTRACT_JOB_TEMPERATURE", 0.1),
        extract_job_max_tokens=_env_int("EXTRACT_JOB_MAX_TOKENS", 1500),
        hermes_helper_temperature=_env_float("HERMES_HELPER_TEMPERATURE", 0.5),
        hermes_helper_max_tokens=_env_int("HERMES_HELPER_MAX_TOKENS", 1024),
    )


@lru_cache
def get_settings() -> Settings:
    return load_settings()
