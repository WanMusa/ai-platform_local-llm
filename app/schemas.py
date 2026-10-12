"""Pydantic request/response schemas."""

from typing import Any, Literal

from pydantic import BaseModel, Field

# Hard cap on request text size; MAX_INPUT_CHARS further truncates what reaches the model.
MAX_TEXT_LENGTH = 200_000
MAX_PROMPT_LENGTH = 20_000


class HealthResponse(BaseModel):
    status: str = "ok"
    model: str
    profiles: list[str]


class LLMStatusResponse(BaseModel):
    state: Literal["ready", "sleeping", "warming", "unavailable"]
    model: str
    error: str | None = None


# ---------- extract_job ----------


class ExtractJobRequest(BaseModel):
    source_url: str | None = Field(default=None, max_length=4096)
    site: str | None = Field(default=None, max_length=200, description="e.g. linkedin, seek")
    page_title: str | None = Field(default=None, max_length=1000)
    cleaned_text: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH, description="Visible job-posting text")
    system_prompt_override: str | None = Field(
        default=None,
        max_length=MAX_PROMPT_LENGTH,
        description="Replaces the default extract_job system prompt",
    )
    extra_instructions: str | None = Field(
        default=None, max_length=MAX_PROMPT_LENGTH, description="Appended to the user prompt"
    )


class ExtractedJob(BaseModel):
    """Fields the model is asked to return. Used to validate model JSON."""

    title: str | None = None
    company: str | None = None
    location: str | None = None
    salary_text: str | None = None
    employment_type: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    notes: str | None = None


class ExtractJobResponse(ExtractedJob):
    profile: str = "extract_job"
    model: str
    source_url: str | None = None
    site: str | None = None
    warnings: list[str] = Field(default_factory=list)
    raw_model_output: str


# ---------- hermes_helper ----------


class HermesHelperRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=200, description="e.g. summarize, classify")
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    context: dict[str, Any] | None = None
    instructions: str | None = Field(
        default=None, max_length=MAX_PROMPT_LENGTH, description="Optional extra guidance"
    )
    system_prompt_override: str | None = Field(default=None, max_length=MAX_PROMPT_LENGTH)


class HermesHelperResponse(BaseModel):
    profile: str = "hermes_helper"
    model: str
    task: str
    output: str
    data: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    raw_model_output: str
