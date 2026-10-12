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

## Local VS Code: unit tests / development

Run these in the repository root on your **laptop**, not on the VPS:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Tests — no model backend needed
pytest -q

# Optional laptop dev server: set env vars for a separately running local model.
# Bind only to localhost; this is NOT the public VPS test.
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Configuration

All settings come from environment variables; see [`.env.example`](.env.example).

| Variable | Default | Notes |
|---|---|---|
| `LOCAL_LLM_API_TOKEN` | – | **Required external API credential.** Generate with `secrets.token_urlsafe(32)`; at least 32 URL-safe characters, varied characters, no placeholder. Missing/weak tokens fail closed with 503. |
| `LLM_BASE_URL` | `http://ollama:11434/v1` | OpenAI-compatible base URL |
| `LLM_MODEL` | `gemma3:4b` | Model name sent to the backend |
| `LLM_API_KEY` | empty | Optional **upstream** credential, not the API token. Keep empty for internal Ollama. |
| `LLM_TIMEOUT_SECONDS` | `120` (example: `300`) | Backend timeout; coordinate with proxy and live test timeouts |
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

This repository configures the app to use your existing `WanMusa/ai-platform_infra`
`nginxproxy/nginx-proxy:1.7` and `nginxproxy/acme-companion:2.4`.
**This PR does not configure or verify your DNS, VPS runtime, firewall, or certificates.**
No Compose lines need uncommenting after merging.

### 1. Local VS Code / GitHub: commit and merge

Review and merge this PR into `main`. Do not commit your `.env` or private keys.
For later edits, commit/push from the laptop and merge to `main`; do not edit
tracked deployment files on the VPS. Pushes to `main` trigger deployment, so the
first run may fail until the one-time VPS steps below are complete; rerun it then.

You already added these **repository Actions secrets**:

| Secret | Connection |
|---|---|
| `VPS_HOST` | VPS address for SSH |
| `VPS_USER` | VPS login user |
| `VPS_SSH_KEY` | Private login key for **Actions → VPS**; public half belongs in that user's `authorized_keys` |

Application settings come only from the **existing VPS `.env`**. Actions does
not transfer `LOCAL_LLM_API_TOKEN` or other application secrets to that file.

### 2. Local VS Code terminal: verify the exact DNS name

```bash
nslookup localgemma.wanagents.duckdns.org
```

Compare the returned A record with your VPS public IPv4 address. If AAAA exists,
it must also reach the correct VPS over IPv6, or remove/fix it before ACME issuance.
`localgemma.wanagents.duckdns.org` is a **nested** DuckDNS hostname: do not assume
arbitrary nested names can be separately registered or have their own A record.
Verify how your `wanagents.duckdns.org` registration resolves this exact name.
If it does not resolve correctly, fix DNS through your provider before continuing;
setting `APP_DOMAIN` alone creates no DNS records.

### 3. VPS terminal: update your existing `.env`

SSH into your VPS as `VPS_USER` using your normal terminal. Use the exact
lowercase directory name (Linux is case-sensitive):

```bash
mkdir -p "$HOME/projects/ai-platform_local-llm"
chmod 600 "$HOME/projects/ai-platform_local-llm/.env"
nano "$HOME/projects/ai-platform_local-llm/.env"
```

**Do not copy `.env.example` over your existing `.env`.** Manually add/update:

```dotenv
APP_DOMAIN=localgemma.wanagents.duckdns.org
LETSENCRYPT_EMAIL=
LOCAL_LLM_API_TOKEN=
LLM_BASE_URL=http://ollama:11434/v1
LLM_MODEL=gemma3:4b
LLM_API_KEY=
LLM_TIMEOUT_SECONDS=300
LLM_JSON_MODE=false
```

The two blank required values above **must be filled before deploying**:

- **`LETSENCRYPT_EMAIL`:** your existing certificate-registration email.
  Open the infra `.env` in an editor on the VPS (verify its directory first,
  commonly `$HOME/projects/ai-platform_infra/.env`). Copy **only** the existing
  `LETSENCRYPT_EMAIL` value manually into this app's `.env`. It is your contact
  email, not an API key. Never `cat`, `source`, print, or paste the whole secret
  file into logs/chat. No real email is provided by this repository.
- **`LOCAL_LLM_API_TOKEN`:** the strong secret clients send to this API.
  If your existing “API key” was intended for callers, put it here, not in
  `LLM_API_KEY`. Generate a new token if it is short or a placeholder.
  Generate on your laptop in a private terminal with
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`,
  save it securely, and manually paste it into the VPS editor.
  Do not place its value in commands/history, source code, or Actions logs.
- **`LLM_API_KEY`:** leave empty for this internal Ollama deployment.

Compose rejects empty domain/email/token. Generation also rejects weak or
placeholder server tokens even if the API health check succeeds.

### 4. VPS terminal: public repository access

The repository is public. The workflow fetches it over HTTPS without a GitHub
deploy key, token, or GitHub SSH `known_hosts` entry on the VPS. Keep
`VPS_SSH_KEY` configured: it is still required for Actions to connect to the VPS.

To check repository access on the VPS without an interactive login prompt:

```bash
GIT_TERMINAL_PROMPT=0 git ls-remote https://github.com/WanMusa/ai-platform_local-llm.git HEAD
```

**Your folder already has `.env` but no Git clone:** leave it there. The workflow
uses `git init` + public HTTPS fetch + checkout, not `git clone` into a nonempty
directory. It refuses bootstrap if anything other than `.env` is present: back
up/move those files manually first. A failed fetch can be retried without deleting
`.env`.

**If it is already a clone:** the workflow accepts the documented HTTPS origin,
or converts the exact old GitHub SSH origin to HTTPS. It rejects other origins
without printing them. To explicitly fix a different origin, after verifying
this is the right clone, run on the VPS:

```bash
git -C "$HOME/projects/ai-platform_local-llm" remote set-url origin \
  https://github.com/WanMusa/ai-platform_local-llm.git
```

No GitHub tokens belong in remotes. Existing checkouts must be clean `main`;
deployments fast-forward and refuse divergent history or tracked local edits
instead of silently overwriting them. Back up edits and resolve them manually.
The workflow does not run `git clean` or delete `.env`.

### 5. VPS terminal: check infra and allow HTTPS

Allow inbound TCP **80 and 443** in the VPS firewall and cloud security rules.
Do not open ports 8000, 8010, or 11434 for this app.

```bash
docker ps --filter name=reverse-proxy
docker network inspect ai_platform
```

Both `reverse-proxy` and `reverse-proxy-acme` must be running and the proxy must
be connected to `ai_platform`. If infra is stopped, start it using its own
documented deployment procedure. The app's startup script ensures the external
`ai_platform` network exists but does **not** start or configure infra.

The API joins `ai_platform` for the proxy and `model_private` for Ollama.
Ollama joins only the separate app model bridge; it has outbound access for
downloads but no public host ports. The API also has no published host ports.
Trusted containers on `ai_platform` can call `http://local-llm-api:8000`,
but generation still requires the bearer token.

### 6. GitHub Actions: deploy and provision

After the above steps, use **Actions → Deploy to Oracle VPS → Run workflow → main**.
Future pushes to `main` deploy automatically. Deployments are serial (an active
deployment is not cancelled); the SSH command has 55 minutes and the job 60.

The workflow fetches the private repository, preserves `.env`, and runs
`scripts/start_services.sh`:

1. Validate Compose quietly, without printing resolved secrets.
2. Ensure the external network, start Ollama, and wait up to 180 seconds for it.
3. Check the configured model; pull it only if missing, with a 30-minute limit.
   **The first download can take minutes and needs disk space/internet.**
4. Build/start the API and wait for container health.

The named `ollama_data` volume stores weights across deployments. Do not run
`docker compose down -v` or delete the volume unless you intend to erase models.
If provisioning times out/fails, the script stops Ollama (10-second shutdown
grace) to cancel work inside the container before a retry. This also interrupts
any current inference; inspect logs and rerun. Downloaded weights remain on disk.

**VPS terminal**, after bootstrap, for diagnostics or a manual retry (do not run
concurrently with an Actions deployment):

```bash
cd "$HOME/projects/ai-platform_local-llm"
bash "$HOME/projects/ai-platform_local-llm/scripts/start_services.sh"
docker compose ps
docker compose exec -T ollama ollama list
docker compose logs --tail=100 ollama local-llm-api
```

This is CPU-compatible: no GPU runtime is required. `gemma3:4b` is a starting
choice, **not a guaranteed fit for your VPS**. RAM use exceeds downloaded weight
size due to context/KV cache, runtime overhead, and other VPS services. Check
available RAM/disk, OOM logs, and latency before increasing context/concurrency.
Ollama is limited to one parallel request and one loaded model initially.
To change models, edit `LLM_MODEL` in the VPS `.env` and rerun deployment; the
script provisions that model and the API uses the same name. Previously downloaded
models remain on disk. An alternative compatible backend can be selected through
`LLM_BASE_URL`, but this deployment script still provisions its configured Ollama.

Gemma does **not** auto-learn or retain memories from requests. Profiles/context
travel per request; durable memory belongs in a separate app/store, not model weights.

### 7. VPS terminal: certificate and slow-CPU diagnostics

```bash
docker logs --tail=100 reverse-proxy
docker logs --tail=100 reverse-proxy-acme
```

Check exact DNS, IPv6, 80/443 reachability, the API's network membership, routing
variables, and ACME errors. Do not share logs publicly without reviewing/redacting
them. Certificate issuance is performed by **existing infra**, not by this repo.

Slow CPU generation can exceed nginx's default read timeout. In current infra,
the named `vhost` volume is mounted at **`/etc/nginx/vhost.d`** in `reverse-proxy`;
the per-host file is:
**`/etc/nginx/vhost.d/localgemma.wanagents.duckdns.org`** (no extension).
Verify this on your VPS before editing:

```bash
docker inspect reverse-proxy --format '{{range .Mounts}}{{println .Type .Name .Destination}}{{end}}'
```

Manage this override as part of **ai-platform_infra**, not this repository.
If that host file already exists, back it up and edit its existing timeout
directive; do not overwrite other host settings or add duplicate directives.
For a new, absent file only, run on the VPS:

```bash
docker exec reverse-proxy sh -c 'test ! -e /etc/nginx/vhost.d/localgemma.wanagents.duckdns.org && printf "proxy_read_timeout 330s;\n" > /etc/nginx/vhost.d/localgemma.wanagents.duckdns.org'
docker exec reverse-proxy nginx -t
# Only reload if nginx -t succeeded:
docker exec reverse-proxy nginx -s reload
```

The named volume keeps the override across container recreation. Inspect the
effective host block with `docker exec reverse-proxy nginx -T` locally if needed;
do not paste the entire configuration into public logs. Confirm the override
applies to this host, then retest. The example timeout chain is backend **300s**,
proxy **330s**, client **360s**; adjust together if real CPU latency requires it.
A model that cannot fit in RAM is not fixed by longer timeouts.

### 8. Local VS Code terminal: real generic HTTPS test (NO SSH tunnel)

Update your local checkout to merged `main`, open the repository root in VS Code,
then run using Python 3:

```bash
python "$PWD/scripts/test_live_api.py"
```

The script defaults to **`https://localgemma.wanagents.duckdns.org`** and reads
`LOCAL_LLM_API_TOKEN` from the project-root `.env` file, regardless of your working
directory. An existing environment variable takes precedence. There is no token
prompt; a missing or invalid token produces an error. Keep `.env` out of Git.
`LOCAL_LLM_TEST_URL` optionally selects another
HTTPS origin. It submits **“What is the capital of France?”** to `/hermes-helper`,
prints response/model, and exits nonzero unless nonempty output contains **Paris**.
TLS certificate/hostname verification is enabled; redirects are refused so the
bearer token cannot be forwarded elsewhere. No SSH tunnel or model installed on
the laptop is needed.

**Never send bearer credentials to an unencrypted public VPS-IP URL.** Do not use
the earlier public-port HTTP advice, disable certificate verification, or open
raw model/API ports to make this test pass.

- Public `GET /health` confirms only the API is alive, **not inference**, model
  readiness, or valid auth configuration.
- Ordinary `pytest -q` fakes model calls; the new script tests are also mocked
  or use temporary local Git fixtures. They make **no live inference calls**.
- This explicit laptop script tests the real HTTPS → API → Ollama → model path.
  401 means check the API token; 503 means check auth/readiness; 502 means check
  model/backend/proxy; 504 means inspect CPU latency and proxy timeout.
  TLS/connection failure means check DNS, certificate, firewall, and connectivity.
