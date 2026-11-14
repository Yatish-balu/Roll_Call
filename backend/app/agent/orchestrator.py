"""Agent Orchestrator executing the autonomous ReAct cycle.

Integrates:
- LLMProvider (Gemini / Mock)
- ToolRegistry (Dynamic RBAC tool discovery & execution)
- ConversationContext (Multi-turn state & draft memory)
- AgentTaskManager (SSE step streaming & reconnection resilience)
"""

from __future__ import annotations

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

logger = logging.getLogger("rollcall.agent.orchestrator")


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
    ) -> OrchestratorResult:
        """Run an autonomous goal-directed ReAct loop for the given user prompt."""
        # 1. Initialize task in stream manager
        task = self.manager.get_task(task_id) if task_id else None
        if not task:
            task = self.manager.create_task(actor_id=actor_id, prompt=prompt)
        tid = task.task_id

        # 2. Input Security Guardrail: Prompt Injection Detection
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

        # 3. Retrieve conversation context with authoritative teacher snapshot
        ctx: ConversationContext = context_manager.get_or_create(
            actor_id=actor_id,
            role=role,
            assigned_subjects=assigned_subjects,
            actor_name=actor_name,
            actor_email=actor_email,
            today_schedule_summary=today_schedule_summary,
            pending_sessions_summary=pending_sessions_summary,
        )
        ctx.add_user_message(prompt)

        # Update task state to PLANNING
        self.manager.update_status(tid, TaskState.PLANNING, message="Planning resolution strategy.")

        # 4. Available tools filtered by actor role
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

        # Output Sanitization Guardrail: redact secrets & credentials
        sanitized_answer = self.sanitizer.sanitize_output(raw_answer)
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

