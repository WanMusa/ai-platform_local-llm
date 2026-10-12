"""Model backend abstraction.

`ModelClient` is the only interface the API layer depends on. The default
implementation talks to any OpenAI-compatible `/chat/completions` endpoint
(Ollama, llama.cpp server, vLLM, LM Studio, ...), so pointing the service at a
different Gemma runtime is just a matter of changing LLM_BASE_URL / LLM_MODEL.
"""

import logging
from typing import Protocol

import httpx
from fastapi import Depends

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class ModelClientError(RuntimeError):
    """Raised when the model backend fails or returns an unusable response."""


class ModelClient(Protocol):
    model_name: str

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> str:
        """Send chat messages and return the assistant message content."""
        ...


class OpenAICompatibleClient:
    def __init__(self, settings: Settings):
        self.base_url = settings.llm_base_url
        self.model_name = settings.llm_model
        self.api_key = settings.llm_api_key
        self.timeout = settings.llm_timeout_seconds
        self.json_mode_supported = settings.llm_json_mode

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> str:
        payload: dict = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_mode and self.json_mode_supported:
            payload["response_format"] = {"type": "json_object"}

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = " ".join(("Bearer", self.api_key))

        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"] or ""
        except httpx.HTTPStatusError as exc:
            raise ModelClientError(
                f"Model backend returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("Model backend request failed: %r", exc)
            raise ModelClientError("Model backend request failed") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelClientError("Unexpected response shape from model backend") from exc


def get_model_client(settings: Settings = Depends(get_settings)) -> ModelClient:
    """FastAPI dependency. Tests override this via app.dependency_overrides."""
    return OpenAICompatibleClient(settings)
