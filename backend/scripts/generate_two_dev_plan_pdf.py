"""Generate RollCall_AI_Two_Person_Agentic_Execution_Plan.pdf using ReportLab.
Produces a publication-quality, comprehensive document for the two AI developers.
"""

import sys
import os
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    KeepTogether,
    HRFlowable,
)
from reportlab.pdfgen import canvas


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and print 'Page X of Y' on all pages."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, total_pages):
        if self._pageNumber > 1:
            self.saveState()
            self.setFont("Helvetica-Bold", 8)
            self.setFillColor(colors.HexColor("#1E293B"))
            self.drawString(54, A4[1] - 36, "ROLLCALL AI — Two-Developer Agentic AI Execution Plan")
            self.setFont("Helvetica", 8)
            self.setFillColor(colors.HexColor("#64748B"))
            self.drawRightString(A4[0] - 54, A4[1] - 36, "Phases • Sessions • Contracts • Integration")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.6)
            self.line(54, A4[1] - 42, A4[0] - 54, A4[1] - 42)

            page_text = f"Page {self._pageNumber} of {total_pages}"
            self.drawRightString(A4[0] - 54, 32, page_text)
            self.drawString(54, 32, "Confidential — Internal Team Engineering Blueprint")
            self.line(54, 44, A4[0] - 54, 44)
            self.restoreState()


def build_pdf(output_pdf_path: str):
    doc = SimpleDocTemplate(
        output_pdf_path,
        pagesize=A4,
        leftMargin=48,
        rightMargin=48,
        topMargin=54,
        bottomMargin=54,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    primary_color = colors.HexColor("#0F172A")
    accent_color = colors.HexColor("#1E3A8A")
    text_dark = colors.HexColor("#1E293B")
    text_muted = colors.HexColor("#475569")
    card_bg = colors.HexColor("#F8FAFC")
    border_color = colors.HexColor("#E2E8F0")

    title_style = ParagraphStyle(
        "CoverTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=26,
        leading=32,
        textColor=primary_color,
        alignment=1,
    )

    subtitle_style = ParagraphStyle(
        "CoverSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=13,
        leading=18,
        textColor=accent_color,
        alignment=1,
    )

    h1_style = ParagraphStyle(
        "Heading1_Custom",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=20,
        textColor=primary_color,
        spaceBefore=14,
        spaceAfter=8,
        keepWithNext=True,
    )

    h2_style = ParagraphStyle(
        "Heading2_Custom",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=accent_color,
        spaceBefore=10,
        spaceAfter=6,
        keepWithNext=True,
    )

    body_style = ParagraphStyle(
        "Body_Custom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=text_dark,
        spaceAfter=6,
    )

    body_bold = ParagraphStyle(
        "Body_Bold",
        parent=body_style,
        fontName="Helvetica-Bold",
    )

    callout_style = ParagraphStyle(
        "CalloutText",
        parent=body_style,
        fontSize=8.5,
        leading=12.5,
        textColor=colors.HexColor("#0F172A"),
    )

    code_style = ParagraphStyle(
        "CodeStyle",
        parent=styles["Normal"],
        fontName="Courier",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#0F172A"),
    )

    table_header_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=colors.white,
    )

    table_cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=text_dark,
    )

    table_cell_bold = ParagraphStyle(
        "TableCellBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=11,
        textColor=text_dark,
    )

    story = []

    # =========================================================================
    # COVER / HEADER BLOCK
    # =========================================================================
    story.append(Spacer(1, 20))
    story.append(Paragraph("ROLLCALL AI", title_style))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Two-Developer Agentic AI Blueprint & Step-by-Step Execution Plan", subtitle_style))
    story.append(Spacer(1, 14))

    meta_table_data = [
        [Paragraph("<b>Team Structure:</b>", table_cell_bold), Paragraph("3 Developers: Dev 1 (You - AI Lead) & Dev 2 (Friend 1 - AI Capabilities) + Dev 3 (Friend 2 - QA & Bugfix)", table_cell_style)],
        [Paragraph("<b>Focus:</b>", table_cell_bold), Paragraph("Complete Agentic AI implementation (Foundation -> Capabilities -> Streaming -> E2E Verification)", table_cell_style)],
        [Paragraph("<b>Base Git State:</b>", table_cell_bold), Paragraph("Branch: <code>kk</code> (Verified clean baseline at commit <code>c7c09f7</code>, 779/779 tests passing)", table_cell_style)],
        [Paragraph("<b>Target Branch:</b>", table_cell_bold), Paragraph("Shared feature branch: <code>feature/agentic-ai</code> (isolated sub-branches for Dev 1 and Dev 2)", table_cell_style)],
        [Paragraph("<b>Key Paradigm:</b>", table_cell_bold), Paragraph("True Antigravity-style Agent: Auto-discovery, Multi-turn memory, SSE stream, 60s Undo, Zero hallucination", table_cell_style)],
    ]
    meta_table = Table(meta_table_data, colWidths=[120, 380])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), card_bg),
        ("BOX", (0, 0), (-1, -1), 0.8, border_color),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, border_color),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 16))

    # =========================================================================
    # SECTION 1: TEAM ROLES & DIVISION OF RESPONSIBILITY
    # =========================================================================
    story.append(Paragraph("1. Team Roles & Division of Ownership", h1_style))
    story.append(Paragraph(
        "To guarantee zero merge conflicts and seamless integration, ownership is strictly divided by architectural layer and file paths. Neither developer edits the other's owned files.",
        body_style
    ))

    roles_data = [
        [Paragraph("Developer", table_header_style), Paragraph("Role Title", table_header_style), Paragraph("Core Ownership & File Boundaries", table_header_style), Paragraph("Must Not Touch", table_header_style)],
        [
            Paragraph("<b>Dev 1<br/>(You)</b>", table_cell_bold),
            Paragraph("AI Lead & Foundation Architect", table_cell_style),
            Paragraph("• Builds the Foundation first (Branch, Gemini Adapter, SSE Pipeline, Base Registry)<br/>• Owns: Orchestrator loop, Multi-turn context memory, Fast-path router, Dynamic tool subsetting, SSE event endpoints.<br/>• Owns Frontend: <code>frontend-react/src/features/assistant/</code> & <code>services/api/agent.ts</code>.", table_cell_style),
            Paragraph("• Direct database migrations<br/>• Domain-specific business logic in backend services<br/>• Core app views outside assistant", table_cell_style),
        ],
        [
            Paragraph("<b>Dev 2<br/>(Friend 1)</b>", table_cell_bold),
            Paragraph("AI Capabilities & Tools Engineer", table_cell_style),
            Paragraph("• Builds on top of Dev 1's foundation.<br/>• Owns: Application Tool Catalogue (Timetable, Sessions, Attendance, Profile, Analytics).<br/>• Owns: Proposal snapshot/hash persistence & 60s Undo transaction engine.<br/>• Owns: Mobile photo intake / OCR pipeline.", table_cell_style),
            Paragraph("• Core orchestration loop<br/>• SSE streaming protocol<br/>• LLM provider configuration<br/>• React chat UI components", table_cell_style),
        ],
        [
            Paragraph("<b>Dev 3<br/>(Friend 2)</b>", table_cell_bold),
            Paragraph("QA, Security & Bugfix Lead", table_cell_style),
            Paragraph("• Shift-left security testing: writes pytest suites for prompt injection, IDOR, and rate limits upfront.<br/>• Fixes core application bugs & ensures 100% CI pass rate.<br/>• Independent release acceptance gate auditor.", table_cell_style),
            Paragraph("• Feature implementation in AI branches<br/>• Modifying production DB credentials", table_cell_style),
        ],
    ]
    roles_table = Table(roles_data, colWidths=[65, 95, 230, 110])
    roles_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), primary_color),
        ("BOX", (0, 0), (-1, -1), 0.8, border_color),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, border_color),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, card_bg]),
    ]))
    story.append(roles_table)
    story.append(Spacer(1, 14))

    # =========================================================================
    # SECTION 2: END-TO-END AGENTIC ARCHITECTURE WORKFLOW
    # =========================================================================
    story.append(Paragraph("2. End-to-End Agentic Architecture & Connection Flow", h1_style))
    story.append(Paragraph(
        "RollCall AI operates on the <b>Antigravity Agentic Model</b>: the user communicates naturally; the agent automatically discovers context, inspects registered tools, checks permissions, executes through backend services, streams real-time progress, and returns verified state.",
        body_style
    ))

    arch_box_data = [[
        Paragraph(
            "<b>Request & Data Flow Lifecycle:</b><br/>"
            "<b>1. Natural Prompt:</b> Teacher says <i>\"Create a session for 3rd sem CSE tomorrow at 10 AM in Lab 1\"</i> via React Assistant.<br/>"
            "<b>2. Fast-Path Check:</b> Dev 1's Router checks if query is a simple deterministic read (e.g. <i>\"Show my timetable\"</i>). If yes, routes directly to backend without burning Gemini API quota.<br/>"
            "<b>3. Context & Auto-Discovery:</b> If complex, Dev 1's Context Engine attaches teacher's authenticated identity, assigned subjects, and active draft facts. (Never asks <i>\"What is your ID?\"</i>).<br/>"
            "<b>4. Tool Planning & Subsetting:</b> Gemini Flash receives prompt + dynamic tool subset (only session/timetable tools). Gemini returns structured tool call <code>create_session(...)</code>.<br/>"
            "<b>5. Real-Time Streaming:</b> SSE stream emits <code>event: step.started</code> (<i>\"Checking timetable conflicts for tomorrow at 10:00...\"</i>) to React UI.<br/>"
            "<b>6. Tool Adapter Execution:</b> Dev 2's Tool Adapter validates arguments, verifies teacher ownership, checks room/section conflicts, and calls authoritative backend service.<br/>"
            "<b>7. Risk-Tiered Result:</b><br/>"
            "&nbsp;&nbsp;&nbsp;&nbsp;• <i>Low-risk / conflict-free write:</i> Persists to Supabase DB, returns verified session ID, generates 60s Undo token.<br/>"
            "&nbsp;&nbsp;&nbsp;&nbsp;• <i>Sensitive write (e.g. marking 60 attendance records):</i> Prepares immutable Proposal Card with matched/unmatched student counts and waits for explicit approval.<br/>"
            "<b>8. Verification:</b> Backend re-reads persisted record from Supabase and streams final verified status to user.",
            callout_style
        )
    ]]
    arch_box = Table(arch_box_data, colWidths=[500])
    arch_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#93C5FD")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(arch_box)
    story.append(Spacer(1, 14))

    # =========================================================================
    # SECTION 3: SYSTEMATIC PHASE & SESSION BREAKDOWN
    # =========================================================================
    story.append(Paragraph("3. Systematic Phase & Session-Wise Implementation", h1_style))
    story.append(Paragraph(
        "The project is structured into 4 sequential phases and 10 focused sessions. <b>Phase 0 is completed by Dev 1 first</b> to establish a stable foundation before Dev 2 joins.",
        body_style
    ))

    # PHASE 0
    story.append(Paragraph("Phase 0 — The Foundation (Owner: Dev 1 / You)", h2_style))
    story.append(Paragraph("<i>Goal: Establish git branches, provider abstraction, tool interfaces, and SSE pipeline before parallel coding begins.</i>", body_style))

    p0_data = [
        [Paragraph("Session", table_header_style), Paragraph("Focus & Concrete Objectives", table_header_style), Paragraph("Deliverables & Output", table_header_style)],
        [
            Paragraph("<b>Session 0.1</b><br/>Git Setup & Contracts", table_cell_bold),
            Paragraph("• Checkout <code>kk</code> at verified commit <code>c7c09f7</code>.<br/>• Create parent feature branch: <code>feature/agentic-ai</code>.<br/>• Branch off <code>ai-orchestrator-core</code> (Dev 1) and <code>ai-tools-capabilities</code> (Dev 2).<br/>• Define JSON schemas for Task, SSE Events, and Tool contracts.", table_cell_style),
            Paragraph("• 3 Git branches ready<br/>• <code>docs/agent_contracts_v1.json</code><br/>• Both devs can pull cleanly.", table_cell_style),
        ],
        [
            Paragraph("<b>Session 0.2</b><br/>Provider Abstraction", table_cell_bold),
            Paragraph("• Create <code>backend/app/agent/provider.py</code> with <code>LLMProvider</code> interface.<br/>• Implement Gemini 1.5 Flash adapter using Google Generative AI SDK.<br/>• Add Mock / Offline fallback adapter for local testing without API keys.<br/>• Server-side API key loading from <code>GEMINI_API_KEY</code>.", table_cell_style),
            Paragraph("• <code>LLMProvider</code> abstract class<br/>• <code>GeminiProvider</code> class<br/>• <code>MockProvider</code> for tests<br/>• Unit tests passing.", table_cell_style),
        ],
        [
            Paragraph("<b>Session 0.3</b><br/>SSE Streaming Pipeline", table_cell_bold),
            Paragraph("• Implement <code>POST /api/v1/agent/tasks</code> (create task & return ID).<br/>• Implement <code>GET /api/v1/agent/tasks/{id}/events</code> (Server-Sent Events).<br/>• Event formatting: <code>step.started</code>, <code>tool.started</code>, <code>tool.completed</code>, <code>task.completed</code>.<br/>• Heartbeat comments (15s) and reconnect support via <code>Last-Event-ID</code>.", table_cell_style),
            Paragraph("• Working SSE endpoint<br/>• Replay queue in memory/DB<br/>• <code>curl -N</code> streaming test passing.", table_cell_style),
        ],
        [
            Paragraph("<b>Session 0.4</b><br/>Tool Registry Interface", table_cell_bold),
            Paragraph("• Refactor <code>ToolDefinition</code> class in <code>backend/app/agent/registry.py</code>.<br/>• Tools declare: <code>name</code>, <code>description</code>, <code>parameters</code> (JSONSchema), <code>risk_tier</code> (READ, LOW_RISK_WRITE, SENSITIVE_WRITE), <code>handler</code>.<br/>• Tool dispatcher checks actor role & permissions before invoking handler.", table_cell_style),
            Paragraph("• <code>ToolRegistry</code> class<br/>• Built-in allowlist & scope validator<br/>• Clean plug-in interface for Dev 2.", table_cell_style),
        ],
    ]
    p0_table = Table(p0_data, colWidths=[90, 260, 150])
    p0_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), primary_color),
        ("BOX", (0, 0), (-1, -1), 0.8, border_color),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, border_color),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, card_bg]),
    ]))
    story.append(p0_table)
    story.append(Spacer(1, 14))

    # PHASE 1
    story.append(Paragraph("Phase 1 — Parallel Implementation (Dev 1 & Dev 2 Together)", h1_style))
    story.append(Paragraph("<i>Goal: Dev 1 builds the intelligent brain and UI; Dev 2 builds the application capabilities and tools. Both work concurrently on their own branches.</i>", body_style))

    p1_data = [
        [Paragraph("Session", table_header_style), Paragraph("Dev 1 (You) — Orchestration & UI", table_header_style), Paragraph("Dev 2 (Friend 1) — Tools & Data Engine", table_header_style)],
        [
            Paragraph("<b>Session 1.1</b><br/>Context & Core Tools", table_cell_bold),
            Paragraph("<b>Multi-Turn Context & Draft Memory:</b><br/>• Rolling 5–8 message memory window.<br/>• Structured task facts (date, subject, section).<br/>• Active draft patching: <i>\"Actually make it 11 AM\"</i> updates existing draft without spawning duplicate sessions.", table_cell_style),
            Paragraph("<b>Academic Setup & Timetable Tools:</b><br/>• <code>get_my_timetable</code> & <code>get_day_schedule</code>.<br/>• <code>create_session</code> supporting multi-room & multi-time allocations (Lab A + Lab B).<br/>• Timetable and room conflict detection logic.", table_cell_style),
        ],
        [
            Paragraph("<b>Session 1.2</b><br/>Routing & Documents", table_cell_bold),
            Paragraph("<b>Fast-Path Router & Quota Shield:</b><br/>• Deterministic regex router for simple reads (0 Gemini API calls consumed).<br/>• Dynamic tool subsetting: only load timetable tools if intent is schedule.<br/>• Shared 15 RPM rate-limiter and graceful 429 retry backoff.", table_cell_style),
            Paragraph("<b>Attendance & Document Intake Tools:</b><br/>• Wrap existing 6 tools (<code>read_csv</code>, <code>read_photo</code>, etc.).<br/>• Mobile image preprocessing: max-1600px downscale, EXIF rotation, JPEG 85 compression.<br/>• Proposal generator with matched/unmatched student counts.", table_cell_style),
        ],
        [
            Paragraph("<b>Session 1.3</b><br/>Assistant UX & Undo", table_cell_bold),
            Paragraph("<b>React Assistant Interface:</b><br/>• Build <code>frontend-react/src/features/assistant/</code>.<br/>• SSE EventSource listener with live progress badges (<i>\"Checking room LH-101 availability...\"</i>).<br/>• Multi-turn chat message timeline and file attachment drag-and-drop.", table_cell_style),
            Paragraph("<b>Risk-Tiered Execution & 60s Undo Engine:</b><br/>• Instant execution for authorized single-student edits.<br/>• Opaque, cryptographically signed 60s Undo token.<br/>• <code>POST /api/v1/attendance/{id}/undo</code> endpoint with audit log rollback.", table_cell_style),
        ],
    ]
    p1_table = Table(p1_data, colWidths=[90, 205, 205])
    p1_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), primary_color),
        ("BOX", (0, 0), (-1, -1), 0.8, border_color),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, border_color),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, card_bg]),
    ]))
    story.append(p1_table)
    story.append(Spacer(1, 14))

    # PHASE 2 & 3
    story.append(Paragraph("Phase 2 — Integration & Contract Hookup", h1_style))
    story.append(Paragraph(
        "Merge Dev 1's branch and Dev 2's branch into <code>feature/agentic-ai</code>. Connect Dev 2's tools into Dev 1's registry and wire the React UI to the SSE backend.",
        body_style
    ))

    p2_data = [
        [Paragraph("Step", table_header_style), Paragraph("Action", table_header_style), Paragraph("Integration Verification Check", table_header_style)],
        [
            Paragraph("<b>2.1 Tool Binding</b>", table_cell_bold),
            Paragraph("Register Dev 2's tools (Timetable, Sessions, Attendance, Undo) into Dev 1's <code>ToolRegistry</code>.", table_cell_style),
            Paragraph("Orchestrator can list, validate, and invoke all tools on demand without runtime exceptions.", table_cell_style),
        ],
        [
            Paragraph("<b>2.2 Proposal & Undo UI</b>", table_cell_bold),
            Paragraph("Connect proposal cards and 60-second undo countdown timer in React Assistant to backend endpoints.", table_cell_style),
            Paragraph("Clicking 'Approve' commits attendance; clicking 'Undo' within 60s rolls back attendance in Supabase DB.", table_cell_style),
        ],
        [
            Paragraph("<b>2.3 Reconnect & State</b>", table_cell_bold),
            Paragraph("Test browser refresh while agent is processing a multi-step task.", table_cell_style),
            Paragraph("UI reconnects via SSE, restores message history from backend, and displays final completed state.", table_cell_style),
        ],
    ]
    p2_table = Table(p2_data, colWidths=[90, 210, 200])
    p2_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), primary_color),
        ("BOX", (0, 0), (-1, -1), 0.8, border_color),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, border_color),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, card_bg]),
    ]))
    story.append(p2_table)
    story.append(Spacer(1, 14))

    # PHASE 3: TESTING & MERGE
    story.append(Paragraph("Phase 3 — Shift-Left Security & Live Acceptance Testing", h1_style))
    story.append(Paragraph(
        "Dev 3 (QA Lead) runs automated attack suites. You and Dev 1 test the 5 core Agentic AI user stories on live Supabase.",
        body_style
    ))

    p3_data = [
        [Paragraph("Scenario", table_header_style), Paragraph("Natural Language Input", table_header_style), Paragraph("Expected Agentic Behavior", table_header_style), Paragraph("Status", table_header_style)],
        [
            Paragraph("<b>1. Multi-Turn Session</b>", table_cell_bold),
            Paragraph("<i>\"Create a session for tomorrow at 10 AM.\"</i><br/>Follow-up: <i>\"Actually, make it 11 AM in Lab 2.\"</i>", table_cell_style),
            Paragraph("Asks for subject/section without guessing. Follow-up updates the pending draft time/room rather than creating duplicate classes.", table_cell_style),
            Paragraph("VERIFY", table_cell_bold),
        ],
        [
            Paragraph("<b>2. Instant Undo Edit</b>", table_cell_bold),
            Paragraph("<i>\"Mark Alice (1MS21CS001) present for today's CN class.\"</i>", table_cell_style),
            Paragraph("Executes immediately through fast-path. Shows success card with 60s Undo button. Clicking Undo reverts status in Supabase.", table_cell_style),
            Paragraph("VERIFY", table_cell_bold),
        ],
        [
            Paragraph("<b>3. Photo / CSV Attendance</b>", table_cell_bold),
            Paragraph("Upload attendance sheet photo or CSV: <i>\"Mark attendance from this sheet.\"</i>", table_cell_style),
            Paragraph("Processes sheet, matches roster, displays Proposal Review Card (matched vs unreviewed). Commits only on explicit approval.", table_cell_style),
            Paragraph("VERIFY", table_cell_bold),
        ],
        [
            Paragraph("<b>4. Scope & RBAC Guard</b>", table_cell_bold),
            Paragraph("Teacher logged in as <code>faculty_cn</code> asks: <i>\"Delete attendance for ML class.\"</i>", table_cell_style),
            Paragraph("Backend denies request: teacher does not own ML subject. Agent politely explains authorization boundary.", table_cell_style),
            Paragraph("VERIFY", table_cell_bold),
        ],
        [
            Paragraph("<b>5. Free-Tier Quota Resilience</b>", table_cell_bold),
            Paragraph("10 rapid user requests or Gemini 429 rate limit trigger.", table_cell_style),
            Paragraph("Deterministic queries bypass LLM; throttled requests pause gracefully with retry notice. Zero paid fallback.", table_cell_style),
            Paragraph("VERIFY", table_cell_bold),
        ],
    ]
    p3_table = Table(p3_data, colWidths=[95, 145, 210, 50])
    p3_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), primary_color),
        ("BOX", (0, 0), (-1, -1), 0.8, border_color),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, border_color),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, card_bg]),
    ]))
    story.append(p3_table)
    story.append(Spacer(1, 14))

    # =========================================================================
    # SECTION 4: GIT WORKFLOW & STEP-BY-STEP COMMAND RUNBOOK
    # =========================================================================
    story.append(Paragraph("4. Git Workflow & Step-by-Step Command Runbook", h1_style))
    story.append(Paragraph(
        "Copy and run these exact terminal commands to initialize the branches, conduct daily syncs, and perform the final safe merge into <code>kk</code>.",
        body_style
    ))

    git_box_data = [[
        Paragraph(
            "<b>Step 1: Dev 1 (You) Initializes the AI Feature Branch</b><br/>"
            "<code>git checkout kk<br/>"
            "git pull origin kk<br/>"
            "git checkout -b feature/agentic-ai<br/>"
            "git push -u origin feature/agentic-ai<br/>"
            "git checkout -b ai-orchestrator-core</code><br/><br/>"
            "<b>Step 2: Dev 2 (Friend 1) Checks Out Their Capabilities Branch</b><br/>"
            "<code>git fetch origin<br/>"
            "git checkout feature/agentic-ai<br/>"
            "git checkout -b ai-tools-capabilities</code><br/><br/>"
            "<b>Step 3: Daily Handoff & Intermediate Integration</b><br/>"
            "When a session is completed and tested:<br/>"
            "<code>git commit -m \"feat(agent): complete session 1.1 timetable tools\"<br/>"
            "git push origin ai-tools-capabilities<br/>"
            "# Merge cleanly into shared feature branch:<br/>"
            "git checkout feature/agentic-ai<br/>"
            "git pull origin feature/agentic-ai<br/>"
            "git merge ai-tools-capabilities</code><br/><br/>"
            "<b>Step 4: Final Test & Merge into kk (With Dev 3 Approval)</b><br/>"
            "<code># 1. Run full backend suite (must pass 100%):<br/>"
            "python -m pytest tests -q --timeout=600<br/>"
            "# 2. Run frontend build:<br/>"
            "cd frontend-react && npm run build<br/>"
            "# 3. Merge to kk and push:<br/>"
            "git checkout kk<br/>"
            "git merge --no-ff feature/agentic-ai -m \"feat: complete agentic AI integration with SSE and multi-turn\"<br/>"
            "git push origin kk</code>",
            code_style
        )
    ]]
    git_box = Table(git_box_data, colWidths=[500])
    git_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(git_box)
    story.append(Spacer(1, 14))

    # =========================================================================
    # SECTION 5: NON-NEGOTIABLE SAFETY RULES
    # =========================================================================
    story.append(Paragraph("5. Non-Negotiable Safety & Quality Rules", h1_style))
    story.append(Paragraph(
        "• <b>Never write raw SQL from LLM:</b> All database writes must go through validated SQLAlchemy CRUD services.<br/>"
        "• <b>Never push .env:</b> Production and Supabase credentials stay local and in server environment variables.<br/>"
        "• <b>Preserve the 6 Core Tools:</b> <code>read_csv</code>, <code>read_photo</code>, <code>validate</code>, <code>summary</code>, <code>query</code>, <code>export</code> are wrapped, never deleted.<br/>"
        "• <b>Single Migration Owner:</b> If new tables are needed (e.g. <code>agent_tasks</code>), Dev 2/Dev 3 creates the Alembic migration atomically with updates to <code>security.yml</code>.<br/>"
        "• <b>Zero Hallucinations:</b> If student records or schedule facts are not found in the database, the agent responds <i>\"I do not have that data\"</i> or asks for clarification.",
        body_style
    ))

    # Build the document
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Successfully generated PDF at: {output_pdf_path}")


if __name__ == "__main__":
    target_path = r"c:\kali sharing\RollCall_AI_Two_Person_Agentic_Execution_Plan.pdf"
    build_pdf(target_path)

