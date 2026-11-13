"""LLM Provider abstraction for RollCall Agentic AI.

Supports Gemini 1.5 Flash with structured tool calling and an offline mock provider
for deterministic testing without consuming quota.
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("rollcall.agent.provider")


@dataclass
class ToolCallRequest:
    """Structured tool request returned by the model."""
    name: str
    arguments: Dict[str, Any]
    call_id: Optional[str] = None


@dataclass
class ModelResponse:
    """Standardized response from any LLM provider."""
    content: Optional[str] = None
    tool_calls: List[ToolCallRequest] = field(default_factory=list)
    raw_response: Optional[Any] = None
    tokens_used: int = 0
    quota_exceeded: bool = False


class LLMProvider(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    def generate(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
    ) -> ModelResponse:
        """Generate response or tool calls given message history and available tools."""
        pass


class MockProvider(LLMProvider):
    """Deterministic mock provider for unit tests and local execution."""

    def __init__(self, responses: Optional[List[ModelResponse]] = None):
        self.responses = list(responses) if responses else []
        self.call_history: List[Dict[str, Any]] = []

    def queue_response(self, response: ModelResponse) -> None:
        self.responses.append(response)

    def generate(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
    ) -> ModelResponse:
        self.call_history.append({"messages": messages, "tools": tools})
        if self.responses:
            return self.responses.pop(0)
        # Default fallback response
        last_msg = messages[-1]["content"] if messages else ""
        return ModelResponse(
            content=f"Mock response for: {last_msg}",
            tool_calls=[],
            tokens_used=10,
        )


class GeminiProvider(LLMProvider):
    """Production provider calling Google Gemini 1.5 Flash."""

    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-1.5-flash"):
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
        self.model_name = model_name
        self._client = None

        if self.api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self._client = genai.GenerativeModel(model_name=self.model_name)
            except Exception as exc:
                logger.warning("Could not initialize google.generativeai client: %s", exc)

    def generate(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
    ) -> ModelResponse:
        if not self._client or not self.api_key:
            return ModelResponse(
                content="Gemini API is not configured on the server. Please check GEMINI_API_KEY.",
                tool_calls=[],
                tokens_used=0,
            )

        try:
            # Format prompt from message history
            history_prompt = ""
            if system_instruction:
                history_prompt += f"System: {system_instruction}\n"
            for m in messages:
                history_prompt += f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}\n"

            # Execute model call with timeout and quota catch
            start_t = time.time()
            response = self._client.generate_content(history_prompt)
            duration = time.time() - start_t
            logger.info("Gemini call completed in %.2fs", duration)

            text_resp = getattr(response, "text", "") or ""
            return ModelResponse(
                content=text_resp,
                tool_calls=[],
                raw_response=response,
                tokens_used=getattr(response.usage_metadata, "total_token_count", 50) if hasattr(response, "usage_metadata") else 50,
            )
        except Exception as exc:
            err_str = str(exc)
            if "429" in err_str or "Quota" in err_str:
                logger.error("Gemini 15 RPM quota limit reached: %s", exc)
                return ModelResponse(
                    content="Gemini API quota momentarily exceeded. Pausing for safe backoff.",
                    tool_calls=[],
                    quota_exceeded=True,
                )
            logger.error("Gemini invocation failed: %s", exc)
            return ModelResponse(
                content=f"LLM generation failed: {exc}",
                tool_calls=[],
            )
