from __future__ import annotations

from typing import Any

import httpx


class CustomOpenAICompatibleProvider:
    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def generate(self, messages: list[dict[str, Any]], model: str, **kwargs: Any) -> str:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.2),
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=45.0,
            )
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices", [])
        if not choices:
            return ""
        return str(choices[0].get("message", {}).get("content", "")).strip()
