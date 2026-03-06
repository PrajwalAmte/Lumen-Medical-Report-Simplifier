"""
Llama provider — local Ollama or vLLM endpoint via HTTP.

Auto-detects API flavour: endpoints containing "/v1/" are treated as
vLLM (OpenAI-compatible); all others use Ollama's /api/chat format.
"""

import json
import re
from typing import Optional, List

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.services.llm_providers.base import LLMProvider
from app.services.llm_providers.prompts import (
    build_messages,
    parse_or_repair_json,
    validate_schema,
    SYSTEM_PROMPT,
)
from app.services.result_sanitizer import sanitize_result

logger = get_logger("llm.llama")


class LlamaProvider(LLMProvider):
    """LLM provider for local Llama models via Ollama or vLLM."""

    def __init__(self):
        self._endpoint = settings.LLAMA_ENDPOINT
        self._model = settings.LLAMA_MODEL
        self._max_tokens = settings.LLAMA_MAX_TOKENS
        self._is_vllm = "/v1/" in self._endpoint  # vLLM vs Ollama

    def choose_model(self, parsed_data: dict) -> tuple:
        return self._model, self._max_tokens

    async def generate(
        self,
        parsed_data: dict,
        retrieval_context: Optional[list] = None,
    ) -> dict:
        model, max_tokens = self.choose_model(parsed_data)
        messages = build_messages(parsed_data, retrieval_context)

        if self._is_vllm:
            result = await self._call_vllm(model, max_tokens, messages)
        else:
            result = await self._call_ollama(model, max_tokens, messages)

        result["_llm_model_used"] = model
        return result


    async def _call_vllm(
        self, model: str, max_tokens: int, messages: list
    ) -> dict:
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": settings.LLM_TEMPERATURE,
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SEC) as client:
            resp = await client.post(self._endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()

        output_text = data["choices"][0]["message"]["content"].strip()
        return self._postprocess(output_text)

    async def _call_ollama(
        self, model: str, max_tokens: int, messages: list
    ) -> dict:
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": settings.LLM_TEMPERATURE,
            },
        }

        url = self._endpoint.rstrip("/")
        if not url.endswith("/api/chat"):
            url = f"{url}/api/chat"

        logger.info(f"Calling Ollama model={model} at {url}")

        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SEC) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        output_text = data.get("message", {}).get("content", "").strip()
        return self._postprocess(output_text)

    def _postprocess(self, text: str) -> dict:
        """Parse and sanitize raw LLM output (handles markdown fences)."""
        if not text:
            raise RuntimeError("Empty response from Llama")

        logger.info(f"Llama raw output length={len(text)}")

        parsed_json = parse_or_repair_json(text)
        parsed_json = sanitize_result(parsed_json)
        validate_schema(parsed_json)

        return parsed_json
