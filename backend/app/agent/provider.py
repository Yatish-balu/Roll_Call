"""LLM Provider abstraction for RollCall Agentic AI.

Supports Gemini 1.5 Flash with structured tool calling and an offline mock provider
for deterministic testing without consuming quota.
"""

from __future__ import annotations

import json
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
    id: Optional[str] = None

    def __post_init__(self):
        if not self.call_id and self.id:
            self.call_id = self.id
        elif not self.id and self.call_id:
            self.id = self.call_id


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
    """Production provider calling Google Gemini via the official google.genai SDK with automatic tool dispatch and quota resilience."""

    FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.5-flash"]

    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-3.5-flash-lite"):
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
        self.model_name = model_name
        self._client = None

        if self.api_key and not self.api_key.startswith("your_"):
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except Exception as exc:
                logger.warning("Could not initialize google.genai client: %s", exc)

    def generate(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[Any] = None,
        system_instruction: Optional[str] = None,
    ) -> ModelResponse:
        if not self._client or not self.api_key:
            return ModelResponse(
                content="Gemini API is not configured on the server. Please check GEMINI_API_KEY in .env.",
                tool_calls=[],
                tokens_used=0,
            )

        # Build prompt or history
        history_prompt = ""
        sys_inst = system_instruction
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system" and not sys_inst:
                sys_inst = content
                continue
            if role == "tool":
                tool_name = m.get("name", "tool")
                history_prompt += f"Observation from {tool_name}: {content}\n"
            elif role == "assistant":
                tc_info = m.get("tool_calls")
                if tc_info:
                    history_prompt += f"Assistant Action: Call tools {json.dumps(tc_info)}\n"
                if content:
                    history_prompt += f"Assistant: {content}\n"
            else:
                if content:
                    history_prompt += f"User: {content}\n"

        # Determine model candidates (primary model first, then fallbacks)
        candidates = [self.model_name] + [m for m in self.FALLBACK_MODELS if m != self.model_name]
        last_error: Optional[Exception] = None

        for model_cand in candidates:
            try:
                from google.genai import types

                config_kwargs: Dict[str, Any] = {}
                if sys_inst:
                    config_kwargs["system_instruction"] = sys_inst
                if tools:
                    # Convert dict schemas into types.Tool
                    func_decls = []
                    for t in tools:
                        if isinstance(t, dict) and "name" in t:
                            fd = types.FunctionDeclaration(
                                name=t["name"],
                                description=t.get("description", ""),
                                parameters=t.get("parameters", {}),
                            )
                            func_decls.append(fd)
                        elif hasattr(t, "__call__"):
                            func_decls.append(t)
                    if func_decls:
                        if all(isinstance(f, types.FunctionDeclaration) for f in func_decls):
                            config_kwargs["tools"] = [types.Tool(function_declarations=func_decls)]
                        else:
                            config_kwargs["tools"] = func_decls

                config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

                start_t = time.time()
                response = self._client.models.generate_content(
                    model=model_cand,
                    contents=history_prompt or "Hello",
                    config=config,
                )
                duration = time.time() - start_t
                logger.info("Gemini (%s) completed in %.2fs", model_cand, duration)

                text_resp = getattr(response, "text", "") or ""
                tool_calls: List[ToolCallRequest] = []

                # Check if unexecuted function calls remain
                fn_calls = getattr(response, "function_calls", None)
                if fn_calls:
                    for idx, fc in enumerate(fn_calls):
                        call_id = f"call_{int(time.time())}_{idx}"
                        tool_calls.append(
                            ToolCallRequest(
                                id=call_id,
                                name=fc.name,
                                arguments=dict(fc.args) if fc.args else {},
                            )
                        )

                return ModelResponse(
                    content=text_resp.strip(),
                    tool_calls=tool_calls,
                    raw_response=response,
                    tokens_used=50,
                )
            except Exception as exc:
                err_str = str(exc)
                last_error = exc
                if "429" in err_str or "503" in err_str or "Quota" in err_str or "high demand" in err_str or "NOT_FOUND" in err_str:
                    logger.warning("Gemini model %s hit rate-limit/outage: %s. Trying fallback candidate...", model_cand, exc)
                    continue
                else:
                    logger.error("Gemini invocation failed with %s: %s", model_cand, exc)
                    break

        # If all candidates exhausted
        logger.error("All Gemini model candidates exhausted. Last error: %s", last_error)
        return ModelResponse(
            content=f"Attendance Assistant is momentarily unable to contact LLM provider: {last_error}",
            tool_calls=[],
        )

