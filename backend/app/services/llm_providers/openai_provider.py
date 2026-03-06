"""
OpenAI provider — direct OpenAI API (GPT-4o / GPT-4-turbo).
Switch to this by setting LLM_PROVIDER=openai + OPENAI_API_KEY.
"""

from typing import Optional, List

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.logging import get_logger
from app.services.llm_providers.base import LLMProvider
from app.services.llm_providers.prompts import (
    build_messages,
    parse_or_repair_json,
    validate_schema,
)
from app.services.result_sanitizer import sanitize_result

logger = get_logger("llm.openai")

_async_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    """Lazily create and return the shared OpenAI async client."""
    global _async_client
    if _async_client is None:
        _async_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        logger.info("OpenAI client initialised")
    return _async_client


class OpenAIProvider(LLMProvider):
    """LLM provider backed by the official OpenAI API."""

    def choose_model(self, parsed_data: dict) -> tuple:
        tests = parsed_data.get("tests", [])
        medicines = parsed_data.get("medicines", [])
        raw_text = parsed_data.get("raw_text", "")

        has_tests = len(tests) > 0
        long_text = len(raw_text) > 500

        if has_tests or long_text:
            return settings.LLM_MODEL_HEAVY, settings.LLM_MAX_TOKENS_HEAVY
        if medicines:
            return settings.LLM_MODEL_LIGHT, settings.LLM_MAX_TOKENS_LIGHT
        return settings.LLM_MODEL_HEAVY, settings.LLM_MAX_TOKENS_HEAVY

    async def generate(
        self,
        parsed_data: dict,
        retrieval_context: Optional[list] = None,
    ) -> dict:
        client = _get_client()
        model, max_tokens = self.choose_model(parsed_data)
        messages = build_messages(parsed_data, retrieval_context)

        logger.info(f"Calling OpenAI model={model}, max_tokens={max_tokens}")

        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=settings.LLM_TEMPERATURE,
            timeout=settings.LLM_TIMEOUT_SEC,
            response_format={"type": "json_object"},
        )

        output_text = (response.choices[0].message.content or "").strip()
        logger.info(f"OpenAI output length={len(output_text)}")

        usage = getattr(response, "usage", None)
        if usage:
            logger.info(
                f"OpenAI tokens — model={model}, prompt={usage.prompt_tokens}, "
                f"completion={usage.completion_tokens}, total={usage.total_tokens}"
            )

        if not output_text:
            raise RuntimeError("Empty response from OpenAI")

        parsed_json = parse_or_repair_json(output_text)
        parsed_json = sanitize_result(parsed_json)
        validate_schema(parsed_json)

        parsed_json["_llm_model_used"] = model
        return parsed_json
