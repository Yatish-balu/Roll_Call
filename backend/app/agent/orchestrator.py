"""Agent Orchestrator executing the autonomous ReAct cycle.

Integrates:
- LLMProvider (Gemini / Mock)
- ToolRegistry (Dynamic RBAC tool discovery & execution)
- ConversationContext (Multi-turn state & draft memory)
- AgentTaskManager (SSE step streaming & reconnection resilience)
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.agent.audit import AgentAuditLogger
from app.agent.context import ConversationContext, context_manager
from app.agent.evaluator import GoalEvaluator
from app.agent.guardrails import OutputSanitizer, PromptInjectionGuard, ScopeGuard
from app.agent.provider import LLMProvider, MockProvider, ModelResponse, ToolCallRequest
from app.agent.registry import RiskTier, ToolRegistry, tool_registry
from app.agent.stream import AgentTaskManager, TaskState, task_manager

try:
    from app.agent.gatekeeper import (
        GATEKEEPER_DOMAIN_REFUSAL,
        GATEKEEPER_SECURITY_REFUSAL,
        GatekeeperDecision,
        evaluate_user_intent,
    )
except ImportError:  # pragma: no cover - defensive fallback
    GATEKEEPER_DOMAIN_REFUSAL = (
        "I am RollCall AI, specialized exclusively for institutional attendance, classroom scheduling, "
        "and student roster management. I cannot assist with topics outside of attendance and class operations. "
        "How can I help you with your attendance or schedule today?"
    )
    GATEKEEPER_SECURITY_REFUSAL = (
        "I can't help with requests that try to change my instructions, reveal internal prompts, "
        "or bypass RollCall's security controls. Ask me about attendance, schedules, sessions, "
        "or student records instead."
    )

    class GatekeeperDecision:  # type: ignore
        def __init__(
            self,
            decision: str = "IN_SCOPE",
            normalized_intent: str = "",
            needs_clarification: bool = False,
            clarification_question: Optional[str] = None,
            refusal_message: Optional[str] = None,
            reason: str = "",
        ):
            self.decision = decision
            self.normalized_intent = normalized_intent
            self.needs_clarification = needs_clarification
            self.clarification_question = clarification_question
            self.refusal_message = refusal_message
            self.reason = reason

    async def evaluate_user_intent(message: str, **kwargs: Any) -> GatekeeperDecision:  # type: ignore
        return GatekeeperDecision(decision="IN_SCOPE", normalized_intent=message)

try:
    from app.agent.guardrails import validate_agent_output, OutputCheckResult
except ImportError:  # pragma: no cover - defensive fallback
    class OutputCheckResult:  # type: ignore
        def __init__(self, allowed: bool = True, sanitized_response: str = "", blocked_reason: Optional[str] = None):
            self.allowed = allowed
            self.sanitized_response = sanitized_response
            self.blocked_reason = blocked_reason

    def validate_agent_output(response_text: str, **kwargs: Any) -> OutputCheckResult:  # type: ignore
        return OutputCheckResult(allowed=True, sanitized_response=response_text)

try:
    from app.security.ai_input import wrap_untrusted_content
except ImportError:  # pragma: no cover - defensive fallback
    def wrap_untrusted_content(text: str, tag: str = "untrusted") -> str:
        return f"<{tag}>\n{text}\n</{tag}>"

logger = logging.getLogger("rollcall.agent.orchestrator")


def _run_coroutine_sync(coro: Any) -> Any:
    """Run an async coroutine synchronously whether or not an event loop is running."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


@dataclass
class OrchestratorResult:
    task_id: str
    final_response: str
    steps_executed: int
    draft_created: Optional[Dict[str, Any]] = None
    status: str = "COMPLETED"
    evaluation: Optional[Dict[str, Any]] = None


class AgentOrchestrator:
    """Core autonomous agent executor with multi-step reasoning, tool dispatch, guardrails, and SSE streaming."""

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        registry: Optional[ToolRegistry] = None,
        manager: Optional[AgentTaskManager] = None,
        audit_logger: Optional[AgentAuditLogger] = None,
        max_steps: int = 8,
    ):
        if provider:
            self.provider = provider
        else:
            api_key = os.getenv("GEMINI_API_KEY", "").strip()
            if api_key and not api_key.startswith("your_"):
                from app.agent.provider import GeminiProvider
                self.provider = GeminiProvider(api_key=api_key)
            else:
                self.provider = MockProvider()

        self.registry = registry or tool_registry
        self.manager = manager or task_manager
        self.audit_logger = audit_logger or AgentAuditLogger()
        self.max_steps = max_steps
        self.injection_guard = PromptInjectionGuard()
        self.scope_guard = ScopeGuard()
        self.sanitizer = OutputSanitizer()
        self.evaluator = GoalEvaluator()

    def execute_prompt(
        self,
        actor_id: str,
        role: str,
        prompt: str,
        assigned_subjects: Optional[List[str]] = None,
        actor_name: Optional[str] = None,
        actor_email: Optional[str] = None,
        today_schedule_summary: Optional[str] = None,
        pending_sessions_summary: Optional[str] = None,
        task_id: Optional[str] = None,
        db: Optional[Any] = None,
        document_extraction: Optional[Dict[str, Any]] = None,
        has_attachments: bool = False,
        recent_context: Optional[str] = None,
    ) -> OrchestratorResult:
        """Run an autonomous goal-directed ReAct loop for the given user prompt."""
        # 1. Initialize task in stream manager
        task = self.manager.get_task(task_id) if task_id else None
        if not task:
            task = self.manager.create_task(actor_id=actor_id, prompt=prompt)
        tid = task.task_id

        # 2. Check uploaded document extraction if provided
        if document_extraction:
            has_attachments = True
            ext_status = str(document_extraction.get("extraction_status", "")).lower()
            allow_llm = document_extraction.get("allow_llm_inference", True)
            if ext_status == "unreadable" or allow_llm is False:
                failure_msg = (
                    document_extraction.get("honest_failure_message")
                    or "Uploaded document is unreadable or malformed. Please upload a clear photo or CSV sheet."
                )
                self.manager.emit_event(
                    tid,
                    event_type="task.failed",
                    message=failure_msg,
                    data={"extraction_status": ext_status},
                )
                self.manager.update_status(tid, TaskState.FAILED, message=failure_msg)
                return OrchestratorResult(
                    task_id=tid,
                    final_response=failure_msg,
                    steps_executed=0,
                    status="FAILED",
                )

        # 3. Intent Gatekeeper & Input Guardrail
        gk_decision = _run_coroutine_sync(
            evaluate_user_intent(
                prompt,
                user_role=role.lower(),
                has_attachments=has_attachments,
                recent_context=recent_context,
            )
        )

        decision_val = getattr(gk_decision, "decision", "IN_SCOPE")

        if decision_val == "PROMPT_INJECTION":
            refusal_msg = getattr(gk_decision, "refusal_message", None) or GATEKEEPER_SECURITY_REFUSAL
            reason = getattr(gk_decision, "reason", "Prompt injection pattern detected.")
            logger.warning("Prompt injection blocked by gatekeeper for actor %s: %s", actor_id, reason)
            self.audit_logger.log_security_threat(
                task_id=tid,
                actor_id=actor_id,
                role=role,
                threat_type="PROMPT_INJECTION",
                reason=reason,
                raw_payload=prompt,
                db=db,
            )
            self.manager.emit_event(
                tid,
                event_type="task.failed",
                message=refusal_msg,
                data={"reason": reason},
            )
            self.manager.update_status(tid, TaskState.FAILED, message=refusal_msg)
            return OrchestratorResult(
                task_id=tid,
                final_response=refusal_msg,
                steps_executed=0,
                status="FAILED",
            )

        if decision_val == "OUT_OF_SCOPE":
            refusal_msg = getattr(gk_decision, "refusal_message", None) or GATEKEEPER_DOMAIN_REFUSAL
            self.manager.emit_event(
                tid,
                event_type="task.completed",
                message=refusal_msg,
                data={"final_response": refusal_msg, "out_of_scope": True},
            )
            self.manager.update_status(tid, TaskState.COMPLETED, message=refusal_msg)
            return OrchestratorResult(
                task_id=tid,
                final_response=refusal_msg,
                steps_executed=0,
                status="COMPLETED",
            )

        if getattr(gk_decision, "needs_clarification", False) and getattr(gk_decision, "clarification_question", None):
            clarify_msg = gk_decision.clarification_question
            self.manager.emit_event(
                tid,
                event_type="task.completed",
                message=clarify_msg,
                data={"final_response": clarify_msg, "needs_clarification": True},
            )
            self.manager.update_status(tid, TaskState.COMPLETED, message=clarify_msg)
            return OrchestratorResult(
                task_id=tid,
                final_response=clarify_msg,
                steps_executed=0,
                status="COMPLETED",
            )

        # Also run secondary PromptInjectionGuard just in case
        is_safe, injection_reason = self.injection_guard.validate_input(prompt)
        if not is_safe:
            block_msg = f"Security Policy Violation: {injection_reason}"
            logger.warning("Prompt injection blocked for actor %s: %s", actor_id, injection_reason)
            self.audit_logger.log_security_threat(
                task_id=tid,
                actor_id=actor_id,
                role=role,
                threat_type="PROMPT_INJECTION",
                reason=injection_reason,
                raw_payload=prompt,
                db=db,
            )
            self.manager.emit_event(
                tid,
                event_type="task.failed",
                message=block_msg,
                data={"reason": injection_reason},
            )
            self.manager.update_status(tid, TaskState.FAILED, message=block_msg)
            return OrchestratorResult(
                task_id=tid,
                final_response=f"Security Alert: Request blocked ({injection_reason}).",
                steps_executed=0,
                status="FAILED",
            )

        # 4. Normalize intent & wrap untrusted user input
        normalized_intent = getattr(gk_decision, "normalized_intent", "").strip() or prompt
        wrapped_user_query = wrap_untrusted_content(normalized_intent, tag="user_query")

        if document_extraction and document_extraction.get("clean_markdown"):
            doc_md = str(document_extraction["clean_markdown"])
            wrapped_doc = wrap_untrusted_content(doc_md, tag="uploaded_document")
            wrapped_user_query = f"{wrapped_user_query}\n\n{wrapped_doc}"

        # 5. Retrieve conversation context with authoritative teacher snapshot
        ctx: ConversationContext = context_manager.get_or_create(
            actor_id=actor_id,
            role=role,
            assigned_subjects=assigned_subjects,
            actor_name=actor_name,
            actor_email=actor_email,
            today_schedule_summary=today_schedule_summary,
            pending_sessions_summary=pending_sessions_summary,
        )
        ctx.add_user_message(wrapped_user_query)

        # Update task state to PLANNING
        self.manager.update_status(tid, TaskState.PLANNING, message="Planning resolution strategy.")

        # 6. Available tools filtered by actor role
        available_tools = self.registry.get_tools_schema_for_role(role)

        steps_executed = 0
        final_answer = ""
        pending_draft: Optional[Dict[str, Any]] = None
        executed_tool_names: List[str] = []

        self.manager.update_status(tid, TaskState.RUNNING, message="Executing reasoning steps.")

        while steps_executed < self.max_steps:
            steps_executed += 1
            messages = ctx.build_prompt_messages()

            self.manager.emit_event(
                tid,
                event_type="step.started",
                message=f"Agent reasoning step {steps_executed}.",
                data={"step": steps_executed},
            )

            # Call LLM Provider
            try:
                response: ModelResponse = self.provider.generate(
                    messages=messages,
                    tools=available_tools if available_tools else None,
                )
            except Exception as exc:
                err_msg = f"LLM generation failed: {exc}"
                logger.error(err_msg)
                self.manager.update_status(tid, TaskState.FAILED, message=err_msg)
                return OrchestratorResult(
                    task_id=tid,
                    final_response=err_msg,
                    steps_executed=steps_executed,
                    status="FAILED",
                )

            # Case A: Model wants to call tools
            if response.tool_calls:
                ctx.add_assistant_message(
                    content=response.content,
                    tool_calls=[
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in response.tool_calls
                    ],
                )

                for tc in response.tool_calls:
                    tool_def = self.registry.get_tool(tc.name)
                    if not tool_def:
                        err_res = {"error": f"Tool '{tc.name}' is not registered."}
                        ctx.add_tool_response(tc.id, tc.name, err_res)
                        continue

                    # Tool Scope Guardrail: Verify role & subject assignment
                    scope_ok, scope_reason = self.scope_guard.validate_tool_scope(
                        tool_name=tc.name,
                        args=tc.arguments,
                        actor_id=actor_id,
                        role=role,
                        assigned_subjects=assigned_subjects or [],
                    )
                    if not scope_ok:
                        logger.warning("Tool scope blocked for actor %s: %s", actor_id, scope_reason)
                        self.audit_logger.log_security_threat(
                            task_id=tid,
                            actor_id=actor_id,
                            role=role,
                            threat_type="SCOPE_VIOLATION",
                            reason=scope_reason,
                            raw_payload=json.dumps(tc.arguments),
                            db=db,
                        )
                        self.manager.emit_event(
                            tid,
                            event_type="tool.blocked",
                            message=f"Action blocked by policy: {scope_reason}",
                            data={"tool": tc.name, "reason": scope_reason},
                        )
                        ctx.add_tool_response(tc.id, tc.name, {"error": f"Policy Violation: {scope_reason}"})
                        continue

                    # If tool requires explicit approval, draft it and suspend execution
                    if tool_def.risk_tier == RiskTier.CONFIRM_REQUIRED:
                        draft_id = f"draft_{tid}_{steps_executed}"
                        draft = ctx.create_draft(
                            draft_id=draft_id,
                            action_type=tc.name,
                            payload=tc.arguments,
                        )
                        pending_draft = {
                            "draft_id": draft.draft_id,
                            "action_type": draft.action_type,
                            "payload": draft.payload,
                            "status": "WAITING_APPROVAL",
                        }
                        self.manager.emit_event(
                            tid,
                            event_type="approval.required",
                            message=f"Action '{tc.name}' requires confirmation before proceeding.",
                            data=pending_draft,
                        )
                        self.manager.update_status(
                            tid,
                            TaskState.WAITING_FOR_APPROVAL,
                            message=f"Waiting for confirmation of {tc.name}.",
                        )
                        return OrchestratorResult(
                            task_id=tid,
                            final_response=f"I have prepared a draft for '{tc.name}'. Please confirm to proceed.",
                            steps_executed=steps_executed,
                            draft_created=pending_draft,
                            status="WAITING_FOR_APPROVAL",
                        )

                    # Execute tool
                    self.manager.emit_event(
                        tid,
                        event_type="tool.started",
                        message=f"Executing tool '{tc.name}'.",
                        data={"tool": tc.name, "args": tc.arguments},
                    )

                    t_start = time.time()
                    exec_res = self.registry.execute(
                        tool_name=tc.name,
                        arguments=tc.arguments,
                        actor_id=actor_id,
                        role=role,
                        db=db,
                    )
                    t_duration = time.time() - t_start
                    executed_tool_names.append(tc.name)

                    self.audit_logger.log_tool_execution(
                        task_id=tid,
                        actor_id=actor_id,
                        role=role,
                        tool_name=tc.name,
                        arguments=tc.arguments,
                        success=exec_res.get("error") is None,
                        duration_seconds=t_duration,
                        db=db,
                    )

                    self.manager.emit_event(
                        tid,
                        event_type="tool.completed",
                        message=f"Tool '{tc.name}' completed.",
                        data={"tool": tc.name, "success": exec_res.get("error") is None},
                    )

                    ctx.add_tool_response(tc.id, tc.name, exec_res)

                # Next iteration in while loop to let LLM observe tool output
                continue

            # Case B: Model returned text response without tool calls (Final Answer)
            raw_answer = response.content or ""
            break

        # Output Validation & Sanitization Guardrail:
        # Enforce validate_agent_output (prompt-leak prevention, off-topic drift check, secret redaction)
        out_check = validate_agent_output(
            raw_answer,
            tool_called=bool(executed_tool_names),
            gatekeeper_decision=gk_decision,
        )
        sanitized_answer = getattr(out_check, "sanitized_response", None) or self.sanitizer.sanitize_output(raw_answer)

        ctx.add_assistant_message(content=sanitized_answer)

        # Goal Evaluation
        evaluation = self.evaluator.evaluate_response(
            user_goal=prompt,
            final_answer=sanitized_answer,
            tools_executed=executed_tool_names,
        )

        # Finished loop
        self.manager.update_status(tid, TaskState.COMPLETED, message="Task completed successfully.")
        self.manager.emit_event(
            tid,
            event_type="task.completed",
            message=sanitized_answer,
            data={"final_response": sanitized_answer, "evaluation": evaluation},
        )

        return OrchestratorResult(
            task_id=tid,
            final_response=sanitized_answer,
            steps_executed=steps_executed,
            draft_created=pending_draft,
            status="COMPLETED",
            evaluation=evaluation,
        )

