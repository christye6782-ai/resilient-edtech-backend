"""Pydantic request/response models shared across the API.

HYBRID + MERGED-AGENT build. This is a superset of the original schemas:
everything the original defined is here unchanged, plus the models for the
merged "Pedagogy Architect" agent (Auditor + Differentiation Strategist in one
pass): ``DifferentiationTier``, ``Differentiation``, ``DesignRequest`` and
``DesignResult``.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


# ---------- Computer-vision / extraction ----------

class ExtractionResult(BaseModel):
    text: str = Field(default="", description="Extracted lesson-plan text.")
    source_type: str = Field(default="", description="image | pdf | docx | text")
    method: str = Field(default="", description="How the text was obtained, e.g. 'OCR (Tesseract)'.")
    confidence: Optional[float] = Field(default=None, description="Mean OCR confidence 0-100, if applicable.")
    word_count: int = 0
    preview_image: Optional[str] = Field(default=None, description="base64 PNG of the CV-preprocessed page, if any.")
    warnings: List[str] = Field(default_factory=list)


# ---------- Agent 1: The Analyst ----------

class AlignmentItem(BaseModel):
    dimension: str  # e.g. "DSKP", "Scheme of Work", "Textbook"
    status: str     # "aligned" | "partial" | "not_aligned"
    notes: str

class AnalystRequest(BaseModel):
    lesson_text: str
    subject: Optional[str] = None
    form: Optional[str] = None
    topic: Optional[str] = None
    lang: Optional[str] = "en"   # "en" | "ms" — drives model directive + fallback strings

class AnalystResult(BaseModel):
    summary: str
    overall_alignment_score: int = Field(ge=0, le=100)
    alignments: List[AlignmentItem] = Field(default_factory=list)
    content_standards_detected: List[str] = Field(default_factory=list)
    learning_standards_detected: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    powered_by: str = "rule-based"


# ---------- Agent 2: The Auditor ----------

class LessonPhase(BaseModel):
    phase: str            # e.g. "Set Induction", "Development", "Closure"
    duration: str         # e.g. "10 min"
    activity: str
    technology: str       # tech used + how it works around the constraint

class AuditorRequest(BaseModel):
    lesson_text: str
    constraints: List[str]
    subject: Optional[str] = None
    form: Optional[str] = None
    topic: Optional[str] = None
    analyst_summary: Optional[str] = None
    lang: Optional[str] = "en"

class ConstraintSolution(BaseModel):
    constraint: str
    strategy: str

class RevisedLessonPlan(BaseModel):
    title: str
    subject: str = ""
    form: str = ""
    topic: str = ""
    duration: str = ""
    objectives: List[str] = Field(default_factory=list)
    success_criteria: List[str] = Field(default_factory=list)
    recommended_tools: List[str] = Field(default_factory=list)
    constraint_solutions: List[ConstraintSolution] = Field(default_factory=list)
    phases: List[LessonPhase] = Field(default_factory=list)
    assessment: str = ""
    materials: List[str] = Field(default_factory=list)
    alignment_note: str = ""
    # KBAT / HOTS — a required element of a Malaysian RPH. The Bloom's band the
    # lesson targets, plus a couple of higher-order questions the teacher can
    # actually ask in class.
    kbat_level: str = ""
    kbat: List[str] = Field(default_factory=list)

class AuditorResult(BaseModel):
    revised_plan: RevisedLessonPlan
    powered_by: str = "rule-based"


# ---------- Agent D: The Differentiation Strategist ----------

class DifferentiationTier(BaseModel):
    tier: str                 # "Remedial" | "Core" | "Enrichment"
    malay: str = ""           # "Pemulihan" | "Teras" | "Pengayaan"
    tp: str = ""              # KSSR performance level, e.g. "TP1–2"
    items: List[str] = Field(default_factory=list)

class Differentiation(BaseModel):
    intro: str = ""
    note: str = ""
    tiers: List[DifferentiationTier] = Field(default_factory=list)


# ---------- Merged agent: The Pedagogy Architect (Auditor + Differentiation) ----------

class DesignRequest(BaseModel):
    """Same inputs as the Auditor — one request now yields plan + tiers."""
    lesson_text: str
    constraints: List[str]
    subject: Optional[str] = None
    form: Optional[str] = None
    topic: Optional[str] = None
    lang: Optional[str] = "en"   # "en" | "ms"
    analyst_summary: Optional[str] = None
    # Level-2 memory: a compact, human-readable digest of THIS teacher's recent
    # lessons (common constraints, reused tools, recent subjects). Folded into the
    # design prompt as PRIORS the model may override. Optional + off by default;
    # the analyst never receives it, so evaluation stays unbiased.
    teacher_context: Optional[str] = None
    # Level-3 (P2) lesson recall: which teacher's history to retrieve similar past
    # lessons from. Gated behind a minimum number of saved lessons in rag.py; the
    # Architect folds the retrieved lessons into its design prompt, never the Analyst.
    teacher_id: Optional[int] = None

class CurriculumSource(BaseModel):
    """One DSKP passage retrieved by RAG that grounded this plan (P3)."""
    year: Optional[int] = None
    section: str = ""
    codes: List[str] = Field(default_factory=list)
    snippet: str = ""
    score: Optional[float] = None

class DesignResult(BaseModel):
    revised_plan: RevisedLessonPlan
    differentiation: Differentiation
    powered_by: str = "rule-based"
    # Which parts came from the model vs. the rule-based playbook. Useful when
    # the model produced a good plan but the tiers had to be synthesised.
    plan_source: str = "rule-based"        # "model" | "rule-based"
    differentiation_source: str = "rule-based"
    # P3: the real DSKP standards RAG surfaced to ground this design. Empty when
    # RAG is unavailable or nothing relevant was retrieved.
    curriculum_sources: List[CurriculumSource] = Field(default_factory=list)


# ---------- Level 4: reflective feedback ----------

class FeedbackRequest(BaseModel):
    teacher_id: Optional[int] = None
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    tools_worked: List[str] = Field(default_factory=list)
    tools_flopped: List[str] = Field(default_factory=list)
    notes: str = ""
    taught_on: str = ""

class FeedbackResult(BaseModel):
    plan_id: int
    rating: Optional[int] = None
    tools_worked: List[str] = Field(default_factory=list)
    tools_flopped: List[str] = Field(default_factory=list)
    notes: str = ""
    taught_on: str = ""
    updated_at: Optional[str] = None


# ---------- Agent 3: FAQ ----------

class FaqRequest(BaseModel):
    question: str
    context: Optional[str] = None  # e.g. the suggested lesson plan, for grounding
    lang: Optional[str] = "en"   # "en" | "ms"

class FaqResult(BaseModel):
    term: str
    explanation: str
    how_to_execute: List[str] = Field(default_factory=list)
    low_resource_notes: str = ""
    alternatives: List[str] = Field(default_factory=list)
    powered_by: str = "rule-based"
