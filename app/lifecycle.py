"""On-demand Ollama warmup and read-only model residency checks."""

import asyncio
import logging

import httpx
from fastapi import Request

from app.config import Settings
from app.schemas import LLMStatusResponse

logger = logging.getLogger(__name__)


class OllamaLifecycle:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport
        self.lock = asyncio.Lock()
        self.task: asyncio.Task[None] | None = None
        self.error: str | None = None

    async def _probe(self, settings: Settings) -> LLMStatusResponse:
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=5.0) as client:
                response = await client.get(f"{settings.ollama_base_url}/api/ps")
                response.raise_for_status()
                data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("models"), list):
                raise ValueError("Invalid model list")
            models = data["models"]
            if any(not isinstance(model, dict) for model in models):
                raise ValueError("Invalid model entry")
            loaded = any(
                settings.llm_model in (model.get("name"), model.get("model"))
                for model in models
            )
            return LLMStatusResponse(
                state="ready" if loaded else "sleeping", model=settings.llm_model,
            )
        except (httpx.HTTPError, ValueError, TypeError):
            return LLMStatusResponse(
                state="unavailable", model=settings.llm_model,
                error="Ollama status unavailable. Check backend connectivity and configuration.",
            )

    async def status(self, settings: Settings) -> LLMStatusResponse:
        if self.task is not None and not self.task.done():
            return LLMStatusResponse(state="warming", model=settings.llm_model)
        result = await self._probe(settings)
        if self.error is not None and result.state == "sleeping":
            return LLMStatusResponse(
                state="unavailable", model=settings.llm_model, error=self.error,
            )
        return result

    async def wake(self, settings: Settings) -> LLMStatusResponse:
        async with self.lock:
            if self.task is not None and not self.task.done():
                return LLMStatusResponse(state="warming", model=settings.llm_model)
            result = await self._probe(settings)
            if result.state != "sleeping":
                return result
            self.error = None
            self.task = asyncio.create_task(self._warm(settings))
            return LLMStatusResponse(state="warming", model=settings.llm_model)

    async def _warm(self, settings: Settings) -> None:
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=httpx.Timeout(settings.llm_warmup_timeout_seconds, connect=5.0),
            ) as client:
                response = await client.post(
                    f"{settings.ollama_base_url}/api/generate",
                    json={
                        "model": settings.llm_model,
                        "prompt": "Reply with OK.",
                        "stream": False,
                        "keep_alive": settings.llm_keep_alive,
                        "options": {"num_predict": 1, "temperature": 0},
                    },
                )
                response.raise_for_status()
                data = response.json()
            if (
                not isinstance(data, dict) or data.get("done") is not True
                or not isinstance(data.get("response"), str) or not data["response"].strip()
            ):
                raise ValueError("Warmup did not produce a completed answer")
        except Exception as exc:
            self.error = "Model warmup failed. Check Ollama logs and configured model."
            logger.warning("Model warmup failed (%s)", type(exc).__name__)

    async def close(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass


def get_lifecycle(request: Request) -> OllamaLifecycle:
    return request.app.state.llm_lifecycle