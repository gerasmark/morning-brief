from __future__ import annotations

from typing import Any

import httpx


class AnthropicProvider:
    def __init__(self, api_key: str, base_url: str = "https://api.anthropic.com") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def generate(self, messages: list[dict[str, Any]], model: str, **kwargs: Any) -> str:
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured")

        system_parts = [m.get("content", "") for m in messages if m.get("role") == "system"]
        user_parts = [m.get("content", "") for m in messages if m.get("role") in {"user", "assistant"}]

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": kwargs.get("max_tokens", 400),
            "system": "\n".join(str(item) for item in system_parts if item),
            "messages": [{"role": "user", "content": "\n".join(str(item) for item in user_parts if item)}],
            "temperature": kwargs.get("temperature", 0.2),
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=45.0,
            )
            response.raise_for_status()
            data = response.json()

        content = data.get("content", [])
        if isinstance(content, list):
            parts = [part.get("text", "") for part in content if isinstance(part, dict)]
            return "\n".join(parts).strip()
        return str(content).strip()
