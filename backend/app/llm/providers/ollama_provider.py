from __future__ import annotations

from typing import Any

import httpx


class OllamaProvider:
    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        self.base_url = base_url.rstrip("/")

    async def generate(self, messages: list[dict[str, Any]], model: str, **kwargs: Any) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": kwargs.get("temperature", 0.2)},
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {})
        return str(message.get("content", "")).strip()
