# ai-platform_local-llm

Shared VPS-hosted Gemma inference service for job extraction and Hermes helper tasks, with authenticated APIs, Docker deployment, and local tests.

One model backend (any OpenAI-compatible `/chat/completions` endpoint serving Gemma — Ollama, llama.cpp server, vLLM, ...) is shared by separate logical **profiles**, each with its own prompt and generation settings:

| Endpoint | Profile | Purpose | Default temperature |
|---|---|---|---|
| `GET /health` | – | Liveness check (no auth) | – |
| `POST /extract-job` | `extract_job` | Structured job extraction for the Chrome extension | `0.1` |
| `POST /hermes-helper` | `hermes_helper` | Lightweight helper tasks for Hermes | `0.5` |

## Project layout

```
app/
  main.py        FastAPI routes
  config.py      Env-var settings
  auth.py        API token check (LOCAL_LLM_API_TOKEN)
  llm_client.py  ModelClient protocol + OpenAI-compatible implementation
  profiles.py    Per-use-case prompts, generation settings, JSON parsing
  schemas.py     Pydantic request/response models
tests/test_api.py  Local tests (model client is faked)
```

To add a new use case: add a profile + prompt builder in `app/profiles.py`, schemas in `app/schemas.py`, and a route in `app/main.py`.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Tests — no model backend needed
pytest -q

# Dev server (point LLM_BASE_URL at a running Gemma server, e.g. local Ollama)
cp .env.example .env   # edit values
set -a; source .env; set +a
uvicorn app.main:app --reload --port 8000
```

## Configuration

All settings come from environment variables; see [`.env.example`](.env.example).

| Variable | Default | Notes |
|---|---|---|
| `LOCAL_LLM_API_TOKEN` | – | **Required.** Protected endpoints return 503 if unset. |
| `LLM_BASE_URL` | `http://ollama:11434/v1` | OpenAI-compatible base URL |
| `LLM_MODEL` | `gemma3:4b` | Model name sent to the backend |
| `LLM_API_KEY` | empty | Sent as a bearer token to the backend if set |
| `LLM_TIMEOUT_SECONDS` | `120` | |
| `LLM_JSON_MODE` | `false` | Send `response_format={"type":"json_object"}` |
| `MAX_INPUT_CHARS` | `24000` | Longer input is truncated with a warning |
| `EXTRACT_JOB_TEMPERATURE` / `EXTRACT_JOB_MAX_TOKENS` | `0.1` / `1500` | |
| `HERMES_HELPER_TEMPERATURE` / `HERMES_HELPER_MAX_TOKENS` | `0.5` / `1024` | |

## API

All non-health endpoints require the header `Authorization: Bearer <LOCAL_LLM_API_TOKEN>`.
Interactive docs are at `/docs`.

### `POST /extract-job`

```json
{
  "source_url": "https://www.seek.com.au/job/123",
  "site": "seek",
  "page_title": "Senior Data Engineer",
  "cleaned_text": "…visible job posting text…",
  "system_prompt_override": null,
  "extra_instructions": null
}
```

Response:

```json
{
  "title": "Senior Data Engineer",
  "company": "Acme",
  "location": "Sydney NSW",
  "salary_text": "$150k - $170k",
  "employment_type": "full-time",
  "responsibilities": ["…"],
  "requirements": ["…"],
  "skills": ["Python", "Spark"],
  "notes": "Hybrid",
  "profile": "extract_job",
  "model": "gemma3:4b",
  "source_url": "…",
  "site": "seek",
  "warnings": [],
  "raw_model_output": "{…}"
}
```

The model is guided by the prompt to return JSON; the service parses it (tolerating code fences / surrounding text), coerces field types, and reports problems in `warnings` rather than failing. Backend errors return HTTP 502.

### `POST /hermes-helper`

```json
{ "task": "summarize", "text": "…", "context": {"audience": "me"}, "instructions": null }
```

Response:

```json
{ "profile": "hermes_helper", "model": "gemma3:4b", "task": "summarize",
  "output": "…", "data": {"…": "…"}, "warnings": [], "raw_model_output": "…" }
```

If the model doesn't return JSON, the raw text is returned as `output` with a warning.

## Deployment (Oracle VPS)

`.github/workflows/deploy.yml` runs on every push to `main` (and manually), following the `ai-platform_infra` pattern:
SSH in → clone to `~/projects/ai-platform_local-llm` on first deploy, otherwise `git reset --hard origin/main` → ensure the `ai_platform` Docker network exists → `docker compose up -d --build --remove-orphans`.

Add these GitHub Actions secrets: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`.

One-time VPS setup — create the `.env` (git-ignored, survives deploys); the workflow fails fast if it is missing:

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/WanMusa/ai-platform_local-llm.git
cd ai-platform_local-llm && cp .env.example .env && nano .env
```

### Networking

- The API is internal only: other containers on `ai_platform` reach it at `http://local-llm-api:8000`.
- For host-only access, uncomment the `127.0.0.1:8010:8000` port mapping in `docker-compose.yml`.
- To publish it via the `ai-platform_infra` nginx-proxy, set `APP_DOMAIN` / `LETSENCRYPT_EMAIL` in `.env` and uncomment the `VIRTUAL_HOST` / `LETSENCRYPT_*` block in `docker-compose.yml`.
- If you don't already run a Gemma server, uncomment the optional `ollama` service in `docker-compose.yml`, then `docker exec -it ollama ollama pull gemma3:4b`.

## Not in scope yet

No persistent storage, queues/background jobs, multi-provider backends, or reverse-proxy/domain setup beyond the hints above.
