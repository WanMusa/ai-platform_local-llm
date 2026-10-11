"""Pydantic request/response schemas."""

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    model: str
    profiles: list[str]


# ---------- extract_job ----------


class ExtractJobRequest(BaseModel):
    source_url: str | None = Field(default=None, max_length=4096)
    site: str | None = Field(default=None, max_length=200, description="e.g. linkedin, seek")
    page_title: str | None = Field(default=None, max_length=1000)
    cleaned_text: str = Field(..., min_length=1, description="Visible job-posting text")
    system_prompt_override: str | None = Field(
        default=None, description="Replaces the default extract_job system prompt"
    )
    extra_instructions: str | None = Field(
        default=None, description="Appended to the user prompt"
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
    text: str = Field(..., min_length=1)
    context: dict[str, Any] | None = None
    instructions: str | None = Field(default=None, description="Optional extra guidance")
    system_prompt_override: str | None = None


class HermesHelperResponse(BaseModel):
    profile: str = "hermes_helper"
    model: str
    task: str
    output: str
    data: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    raw_model_output: str
