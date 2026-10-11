"""FastAPI entrypoint: shared model backend, separate per-use-case profiles."""

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status

from app.auth import require_token
from app.config import Settings, get_settings
from app.llm_client import ModelClient, ModelClientError, get_model_client
from app.profiles import (
    PROFILE_NAMES,
    build_extract_job_prompt,
    build_hermes_helper_prompt,
    build_messages,
    extract_job_profile,
    hermes_helper_profile,
    parse_json_object,
    truncate,
)
from app.schemas import (
    ExtractedJob,
    ExtractJobRequest,
    ExtractJobResponse,
    HealthResponse,
    HermesHelperRequest,
    HermesHelperResponse,
)

app = FastAPI(title="ai-platform local-llm", version="0.1.0")

_LIST_FIELDS = {"responsibilities", "requirements", "skills"}
_STR_FIELDS = set(ExtractedJob.model_fields) - _LIST_FIELDS


def _run_model(client: ModelClient, messages, profile) -> str:
    try:
        return client.chat(
            messages,
            temperature=profile.temperature,
            max_tokens=profile.max_tokens,
            json_mode=profile.json_mode,
        )
    except ModelClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value if v not in (None, ""))
    text = str(value).strip()
    return text or None


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [str(v).strip() for v in value if v not in (None, "") and str(v).strip()]


def _coerce_job(data: dict[str, Any]) -> ExtractedJob:
    fields: dict[str, Any] = {}
    for name in _STR_FIELDS:
        fields[name] = _as_str(data.get(name))
    for name in _LIST_FIELDS:
        fields[name] = _as_str_list(data.get(name))
    return ExtractedJob(**fields)


@app.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(model=settings.llm_model, profiles=PROFILE_NAMES)


@app.post(
    "/extract-job",
    response_model=ExtractJobResponse,
    dependencies=[Depends(require_token)],
)
def extract_job(
    req: ExtractJobRequest,
    settings: Settings = Depends(get_settings),
    client: ModelClient = Depends(get_model_client),
) -> ExtractJobResponse:
    profile = extract_job_profile(settings)
    text, warnings = truncate(req.cleaned_text, settings.max_input_chars)
    user_prompt = build_extract_job_prompt(
        cleaned_text=text,
        source_url=req.source_url,
        site=req.site,
        page_title=req.page_title,
        extra_instructions=req.extra_instructions,
    )
    messages = build_messages(req.system_prompt_override or profile.system_prompt, user_prompt)
    raw = _run_model(client, messages, profile)

    parsed = parse_json_object(raw)
    if parsed is None:
        warnings.append("Model output was not valid JSON; structured fields are empty")
        job = ExtractedJob()
    else:
        job = _coerce_job(parsed)
        if not job.title:
            warnings.append("No job title extracted")
        if not job.company:
            warnings.append("No company extracted")

    return ExtractJobResponse(
        **job.model_dump(),
        model=client.model_name,
        source_url=req.source_url,
        site=req.site,
        warnings=warnings,
        raw_model_output=raw,
    )


@app.post(
    "/hermes-helper",
    response_model=HermesHelperResponse,
    dependencies=[Depends(require_token)],
)
def hermes_helper(
    req: HermesHelperRequest,
    settings: Settings = Depends(get_settings),
    client: ModelClient = Depends(get_model_client),
) -> HermesHelperResponse:
    profile = hermes_helper_profile(settings)
    text, warnings = truncate(req.text, settings.max_input_chars)
    user_prompt = build_hermes_helper_prompt(
        task=req.task, text=text, context=req.context, instructions=req.instructions
    )
    messages = build_messages(req.system_prompt_override or profile.system_prompt, user_prompt)
    raw = _run_model(client, messages, profile)

    parsed = parse_json_object(raw)
    data: dict[str, Any] | None = None
    if parsed is None:
        warnings.append("Model output was not valid JSON; returning raw text as output")
        output = raw.strip()
    else:
        output = _as_str(parsed.get("output")) or ""
        raw_data = parsed.get("data")
        data = raw_data if isinstance(raw_data, dict) else None
        if not output:
            warnings.append("Model returned an empty output field")

    return HermesHelperResponse(
        model=client.model_name,
        task=req.task,
        output=output,
        data=data,
        warnings=warnings,
        raw_model_output=raw,
    )
