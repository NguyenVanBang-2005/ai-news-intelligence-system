"""Minimal client for any OpenAI-compatible chat API (Ollama, OpenAI, ...)."""

import httpx

from app.core.config import settings


class LLMError(RuntimeError):
    """The model could not be reached or gave an unusable reply."""


class LLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ):
        self.url = f"{base_url.rstrip('/')}/chat/completions"
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        # Injectable so tests can answer without a real model.
        self.transport = transport

    @classmethod
    def from_settings(cls) -> "LLMClient":
        return cls(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            timeout_seconds=settings.llm_timeout_seconds,
        )

    def complete(self, *, system: str, user: str) -> str:
        """Send one system + user message and return the reply text."""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }

        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = client.post(
                    self.url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                response.raise_for_status()
                reply = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"LLM request failed: {type(exc).__name__}") from exc

        if not isinstance(reply, str) or not reply.strip():
            raise LLMError("LLM returned an empty reply")

        return reply.strip()
