from __future__ import annotations

from app.config import Settings
from app.llm.providers.anthropic_provider import AnthropicProvider
from app.llm.providers.base import LLMProvider
from app.llm.providers.custom_provider import CustomOpenAICompatibleProvider
from app.llm.providers.gemini_provider import GeminiProvider
from app.llm.providers.groq_provider import GroqProvider
from app.llm.providers.ollama_provider import OllamaProvider
from app.llm.providers.openai_provider import OpenAIProvider


def get_provider(settings: Settings) -> LLMProvider:
    provider = settings.llm_provider.lower().strip()
    if provider == "openai":
        return OpenAIProvider(api_key=settings.openai_api_key or "", base_url=settings.openai_base_url)
    if provider == "anthropic":
        return AnthropicProvider(api_key=settings.anthropic_api_key or "", base_url=settings.anthropic_base_url)
    if provider == "ollama":
        return OllamaProvider(base_url=settings.ollama_base_url)
    if provider == "custom":
        return CustomOpenAICompatibleProvider(base_url=settings.openai_base_url, api_key=settings.openai_api_key)
    if provider in {"gemini", "google"}:
        return GeminiProvider(api_key=settings.gemini_api_key or "", base_url=settings.gemini_base_url)
    if provider == "groq":
        return GroqProvider(api_key=settings.groq_api_key or "", base_url=settings.groq_base_url)
    raise ValueError(f"Unsupported LLM_PROVIDER={settings.llm_provider}")
