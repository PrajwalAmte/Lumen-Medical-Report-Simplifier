"""
Abstract base class for all LLM providers.
Each concrete provider must implement `generate` and `choose_model`.
"""

from abc import ABC, abstractmethod
from typing import Optional


class LLMProvider(ABC):

    @abstractmethod
    async def generate(
        self,
        parsed_data: dict,
        retrieval_context: Optional[list] = None,
    ) -> dict:
        """
        Analyse parsed medical data and return a dict matching ResultResponse schema.
        Implementors must also set the internal ``_llm_model_used`` key.
        """
        ...

    @abstractmethod
    def choose_model(self, parsed_data: dict) -> tuple:
        """Return (model_id, max_tokens) for this request."""
        ...
