from __future__ import annotations

from typing import Any

import httpx


class OpenAIProvider:
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def generate(self, messages: list[dict[str, Any]], model: str, **kwargs: Any) -> str:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.2),
        }
        if kwargs.get("max_tokens"):
            payload["max_tokens"] = kwargs["max_tokens"]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=45.0,
            )
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("OpenAI response did not include choices")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            return "\n".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
        return str(content).strip()
