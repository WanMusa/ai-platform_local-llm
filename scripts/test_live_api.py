"""Opt-in HTTPS inference check; run directly from your laptop, not via pytest."""

import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from dotenv import dotenv_values

DEFAULT_URL = "https://localgemma.wanagents.duckdns.org"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the bearer token to a redirect target (including HTTP).
        return None


def main() -> int:
    base_url = os.getenv("LOCAL_LLM_TEST_URL", DEFAULT_URL).strip().rstrip("/")
    try:
        url = urlsplit(base_url)
    except ValueError:
        print("FAIL: Invalid HTTPS URL.", file=sys.stderr)
        return 1
    if (
        url.scheme != "https" or not url.hostname or url.username is not None
        or url.password is not None or url.query or url.fragment or url.path
    ):
        print("FAIL: Use an HTTPS origin only (no credentials, path, query, or fragment).", file=sys.stderr)
        return 1

    token = os.getenv("LOCAL_LLM_API_TOKEN") or dotenv_values(
        ENV_FILE, interpolate=False,
    ).get("LOCAL_LLM_API_TOKEN")
    if not token or re.fullmatch(r"[A-Za-z0-9_-]{32,}", token) is None:
        print("FAIL: Set LOCAL_LLM_API_TOKEN in the project-root .env file or environment to a URL-safe token of at least 32 characters.", file=sys.stderr)
        return 1

    payload = {
        "task": "answer_question",
        "text": "What is the capital of France?",
        "instructions": 'Answer in one short sentence. Return JSON with keys "output" and "data".',
    }
    request = Request(
        f"{base_url}/hermes-helper",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": " ".join(("Bearer", token)), "Content-Type": "application/json"},
        method="POST",
    )
    try:
        # Default HTTPSHandler verifies certificates/hostname. Redirects are refused.
        with build_opener(NoRedirect()).open(request, timeout=360) as response:
            result = json.load(response)
    except HTTPError as exc:
        hints = {
            401: "Check the API bearer token.",
            503: "Check server token configuration and proxy/API readiness.",
            502: "Check Ollama, the downloaded model, and API/proxy logs.",
            504: "Check CPU latency and the per-host nginx proxy_read_timeout.",
        }
        print(f"FAIL: HTTP {exc.code}. {hints.get(exc.code, 'Check API/proxy logs; redirects are not followed.')}", file=sys.stderr)
        return 1
    except (URLError, TimeoutError, OSError):
        print("FAIL: Connection/TLS/timeout error. Check exact DNS, certificate, firewall, and latency.", file=sys.stderr)
        return 1
    except (ValueError, UnicodeError):
        print("FAIL: API returned invalid JSON.", file=sys.stderr)
        return 1

    if not isinstance(result, dict):
        print("FAIL: API response must be a JSON object.", file=sys.stderr)
        return 1
    # Redact even if a misconfigured server echoes the credential.
    print(json.dumps(result, indent=2, ensure_ascii=False).replace(token, "[REDACTED]"))
    answer = result.get("output")
    model = result.get("model")
    if not isinstance(answer, str) or not answer.strip() or "paris" not in answer.lower():
        print("FAIL: Expected nonempty output containing Paris.", file=sys.stderr)
        return 1
    if not isinstance(model, str) or not model.strip():
        print("FAIL: Response is missing a model name.", file=sys.stderr)
        return 1
    print("PASS: Authenticated HTTPS API returned the expected generic model answer.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit("FAIL: Request cancelled.")
