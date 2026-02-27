from __future__ import annotations

from typing import Any, Protocol


class LLMProvider(Protocol):
    async def generate(self, messages: list[dict[str, Any]], model: str, **kwargs: Any) -> str:
        ...
