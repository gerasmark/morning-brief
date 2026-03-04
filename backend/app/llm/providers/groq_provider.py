from __future__ import annotations

import json
from typing import Any

import httpx


class GroqProvider:
    def __init__(self, api_key: str, base_url: str = "https://api.groq.com/openai/v1") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def generate(self, messages: list[dict[str, Any]], model: str, **kwargs: Any) -> str:
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not configured")

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 1),
            "top_p": kwargs.get("top_p", 1),
            "stream": False,
        }
        if kwargs.get("max_tokens"):
            payload["max_completion_tokens"] = kwargs["max_tokens"]
        reasoning_effort = kwargs.get("reasoning_effort")
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if kwargs.get("tools") is not None:
            payload["tools"] = kwargs["tools"]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=60.0,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"Groq API error {response.status_code}: {_response_error_detail(response)}")
            data = response.json()

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("Groq response did not include choices")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            return "\n".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
        return str(content).strip()


def _response_error_detail(response: httpx.Response) -> str:
    text_preview = response.text.strip().replace("\n", " ")
    if not text_preview:
        return "No error body"

    try:
        payload = response.json()
    except json.JSONDecodeError:
        return text_preview[:600]

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message", "")).strip()
            code = str(error.get("code", "")).strip()
            if message and code:
                return f"{code} - {message}"[:600]
            if message:
                return message[:600]
    return text_preview[:600]
