from __future__ import annotations

import json
from typing import Any

import httpx


def _message_content(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = str(item.get("text", "")).strip()
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    return str(content).strip()


class GeminiProvider:
    def __init__(self, api_key: str, base_url: str = "https://generativelanguage.googleapis.com/v1beta") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def generate(self, messages: list[dict[str, Any]], model: str, **kwargs: Any) -> str:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")

        system_text = "\n".join(
            _message_content(message)
            for message in messages
            if str(message.get("role", "")).strip().lower() == "system"
        ).strip()

        user_blocks: list[str] = []
        for message in messages:
            role = str(message.get("role", "user")).strip().lower()
            if role == "system":
                continue
            text = _message_content(message)
            if text:
                user_blocks.append(text)

        payload = _build_payload(
            user_blocks=user_blocks,
            system_text=system_text,
            temperature=kwargs.get("temperature", 0.2),
            max_tokens=kwargs.get("max_tokens"),
            use_system_instruction=True,
        )

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/models/{model}:generateContent",
                params={"key": self.api_key},
                json=payload,
                timeout=45.0,
            )
            if response.status_code >= 400:
                detail = _response_error_detail(response)
                if _supports_inline_system_fallback(response.status_code, detail, system_text):
                    retry_payload = _build_payload(
                        user_blocks=user_blocks,
                        system_text=system_text,
                        temperature=kwargs.get("temperature", 0.2),
                        max_tokens=kwargs.get("max_tokens"),
                        use_system_instruction=False,
                    )
                    retry_response = await client.post(
                        f"{self.base_url}/models/{model}:generateContent",
                        params={"key": self.api_key},
                        json=retry_payload,
                        timeout=45.0,
                    )
                    if retry_response.status_code >= 400:
                        raise RuntimeError(
                            f"Gemini API error {retry_response.status_code}: {_response_error_detail(retry_response)}"
                        )
                    data = retry_response.json()
                else:
                    raise RuntimeError(f"Gemini API error {response.status_code}: {detail}")
            else:
                data = response.json()

        for candidate in data.get("candidates", []):
            content = candidate.get("content", {})
            parts = content.get("parts", [])
            if isinstance(parts, list):
                texts = [str(part.get("text", "")).strip() for part in parts if isinstance(part, dict)]
                output = "\n".join(text for text in texts if text).strip()
                if output:
                    return output

        raise RuntimeError("Gemini response did not include text output")


def _build_payload(
    *,
    user_blocks: list[str],
    system_text: str,
    temperature: float,
    max_tokens: Any,
    use_system_instruction: bool,
) -> dict[str, Any]:
    combined_user = "\n\n".join(user_blocks).strip()
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": combined_user}]}],
        "generationConfig": {"temperature": temperature},
    }

    if system_text:
        if use_system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}
        else:
            inline_text = f"Οδηγίες σύνταξης:\n{system_text}\n\n{combined_user}".strip()
            payload["contents"] = [{"role": "user", "parts": [{"text": inline_text}]}]

    if max_tokens:
        payload["generationConfig"]["maxOutputTokens"] = int(max_tokens)
    return payload


def _supports_inline_system_fallback(status_code: int, detail: str, system_text: str) -> bool:
    if status_code != 400:
        return False
    if not system_text:
        return False
    lowered = detail.lower()
    return "developer instruction is not enabled" in lowered


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
            status = str(error.get("status", "")).strip()
            if message and status:
                return f"{status} - {message}"[:600]
            if message:
                return message[:600]
    return text_preview[:600]
