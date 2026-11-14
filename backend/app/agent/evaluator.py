"""Goal-evaluation heuristics for the RollCall AI Agent.

Deterministically assesses whether an agent's final answer actually fulfilled
the user's stated goal, without requiring an LLM call. The verdict combines:

* keyword coverage of the goal in the final answer,
* relevance of the executed tools to the goal's domain,
* absence of evasive / refusal language in the answer.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


class GoalEvaluator:
    """Evaluates whether a final answer achieved the user's goal."""

    EVASIVE_PHRASES: List[str] = [
        "i cannot",
        "i can't",
        "i am unable",
        "i'm unable",
        "unable to",
        "as an ai",
        "as an ai language model",
        "i do not have access",
        "i don't have access",
        "i do not have the ability",
        "i'm not able to",
        "sorry, i can't",
        "apologize",
    ]

    # Goal keyword domains -> tool names that would satisfy them.
    GOAL_TOOL_MAP: Dict[str, List[str]] = {
        "attendance": [
            "mark_attendance",
            "update_attendance",
            "bulk_update_attendance",
            "get_attendance",
        ],
        "session": [
            "create_session",
            "edit_session",
            "update_session",
            "delete_session",
            "get_sessions",
        ],
        "timetable": ["get_my_timetable", "get_timetable", "view_timetable"],
        "schedule": ["get_schedule", "get_my_timetable", "view_schedule"],
        "student": ["get_students", "list_students", "get_student"],
        "report": ["generate_report", "export_report", "download_report"],
        "profile": ["get_profile", "update_profile"],
    }

    _STOPWORDS = {
        "the", "and", "for", "with", "from", "this", "that", "have", "has",
        "had", "was", "were", "you", "your", "my", "me", "i", "can", "could",
        "would", "should", "please", "show", "get", "list", "find",
    }

    def evaluate_response(
        self,
        user_goal: str,
        final_answer: str,
        tools_executed: list[str],
    ) -> Dict[str, Any]:
        """Return ``{"goal_achieved", "confidence", "feedback"}``.

        * ``goal_achieved`` (bool): whether the evidence indicates the goal was met.
        * ``confidence`` (float): heuristic confidence in the verdict, 0.0-1.0.
        * ``feedback`` (str): human-readable explanation of the verdict.
        """
        goal = (user_goal or "").strip()
        answer = (final_answer or "").strip()
        tools = [str(t).lower() for t in (tools_executed or [])]

        if not goal:
            return {"goal_achieved": False, "confidence": 0.0, "feedback": "No user goal was provided."}
        if not answer:
            return {"goal_achieved": False, "confidence": 0.0, "feedback": "No final answer was provided."}

        goal_l = goal.lower()
        answer_l = answer.lower()

        goal_words = {w for w in re.findall(r"[a-z0-9]+", goal_l) if len(w) > 2}
        key_words = {w for w in goal_words if w not in self._STOPWORDS}
        answer_words = set(re.findall(r"[a-z0-9]+", answer_l))

        if key_words:
            matched = key_words & answer_words
            coverage = len(matched) / len(key_words)
        else:
            coverage = 1.0
            matched = set()

        # Evasive / refusal language penalty.
        evasive_hits = [phrase for phrase in self.EVASIVE_PHRASES if phrase in answer_l]
        is_evasive = bool(evasive_hits)

        # Tool relevance: if the goal hints at a domain, a matching tool should
        # have been executed.
        domain_tools: set = set()
        for domain, tlist in self.GOAL_TOOL_MAP.items():
            if domain in goal_l:
                domain_tools.update(tlist)
        tool_hits = [t for t in tools if any(dt in t for dt in domain_tools)] if domain_tools else []
        tool_ok = len(tool_hits) > 0 if domain_tools else True

        score = (
            0.5 * coverage
            + 0.3 * (1.0 if tool_ok else 0.0)
            + 0.2 * (0.0 if is_evasive else 1.0)
        )
        confidence = max(0.0, min(1.0, round(score, 4)))

        goal_achieved = bool(confidence >= 0.6 and not (is_evasive and not tools))

        if goal_achieved:
            feedback = (
                f"Goal appears achieved: {len(matched)} key goal term(s) "
                f"reflected in the answer."
            )
            if tool_hits:
                feedback += f" Relevant tool(s) executed: {', '.join(tool_hits)}."
        else:
            parts: List[str] = []
            if is_evasive:
                parts.append("answer contains evasive/refusal language")
            if key_words and coverage < 1.0:
                missing = sorted(key_words - answer_words)
                parts.append(f"uncovered goal term(s): {', '.join(missing[:5])}")
            if domain_tools and not tool_hits:
                parts.append("no relevant tool was executed")
            if not parts:
                parts.append("insufficient evidence in the answer")
            feedback = "Goal not fully achieved: " + "; ".join(parts) + "."

        return {"goal_achieved": goal_achieved, "confidence": confidence, "feedback": feedback}
