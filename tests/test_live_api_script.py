import io
import json
from urllib.error import HTTPError, URLError

import pytest

from scripts import test_live_api

TOKEN = "unit-test-only-bearer-value-0123456789"


@pytest.fixture
def request_stub(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_LLM_API_TOKEN", TOKEN)
    monkeypatch.delenv("LOCAL_LLM_TEST_URL", raising=False)
    monkeypatch.setattr(test_live_api, "ENV_FILE", tmp_path / ".env")
    captured = {}

    class Opener:
        def open(self, request, timeout):
            captured.update(request=request, timeout=timeout)
            if "error" in captured:
                raise captured["error"]
            return io.StringIO(json.dumps(captured.get("result", {
                "output": "The capital of France is Paris.", "model": "gemma3:4b",
            })))

    monkeypatch.setattr(test_live_api, "build_opener", lambda handler: Opener())
    return captured


def test_live_request_contract(request_stub, capsys):
    assert test_live_api.main() == 0
    request = request_stub["request"]
    assert request.full_url == test_live_api.DEFAULT_URL + "/hermes-helper"
    assert request.get_header("Authorization") == " ".join(("Bearer", TOKEN))
    assert json.loads(request.data)["text"] == "What is the capital of France?"
    assert request_stub["timeout"] == 360
    assert "gemma3:4b" in capsys.readouterr().out


@pytest.mark.parametrize("url", [
    "http://example.org", "https://" + "user:password@" + "example.org",
    "https://example.org/path", "https://example.org?token=x",
    "https://example.org#fragment", "https://[invalid", "",
])
def test_unsafe_url_refused(request_stub, monkeypatch, url):
    monkeypatch.setenv("LOCAL_LLM_TEST_URL", url)
    assert test_live_api.main() == 1
    assert "request" not in request_stub


def test_token_from_dotenv(request_stub, monkeypatch, tmp_path):
    monkeypatch.delenv("LOCAL_LLM_API_TOKEN")
    test_live_api.ENV_FILE.write_text(
        f'export LOCAL_LLM_API_TOKEN="{TOKEN}" # local token\n', encoding="utf-8",
    )
    other_directory = tmp_path / "other"
    other_directory.mkdir()
    monkeypatch.chdir(other_directory)
    assert test_live_api.main() == 0
    assert request_stub["request"].get_header("Authorization") == " ".join(("Bearer", TOKEN))


def test_environment_token_overrides_dotenv(request_stub):
    test_live_api.ENV_FILE.write_text("LOCAL_LLM_API_TOKEN=short\n", encoding="utf-8")
    assert test_live_api.main() == 0
    assert request_stub["request"].get_header("Authorization") == " ".join(("Bearer", TOKEN))


def test_missing_token_fails_without_prompt(request_stub, monkeypatch, capsys):
    monkeypatch.delenv("LOCAL_LLM_API_TOKEN")
    assert test_live_api.main() == 1
    assert "request" not in request_stub
    assert "project-root .env" in capsys.readouterr().err


@pytest.mark.parametrize("token", ["short", "has newline\n" * 3])
def test_invalid_token_refused(request_stub, monkeypatch, token):
    monkeypatch.setenv("LOCAL_LLM_API_TOKEN", token)
    assert test_live_api.main() == 1
    assert "request" not in request_stub


@pytest.mark.parametrize("result", [
    {"output": "", "model": "gemma3:4b"},
    {"output": "London", "model": "gemma3:4b"},
    {"output": "Paris"}, {"output": 1, "model": "gemma3:4b"}, [],
])
def test_bad_answer_fails(request_stub, result):
    request_stub["result"] = result
    assert test_live_api.main() == 1


@pytest.mark.parametrize("error", [
    HTTPError(test_live_api.DEFAULT_URL, code, "", {}, None)
    for code in (301, 401, 502, 503, 504)
] + [URLError("TLS failed"), TimeoutError(), ValueError("invalid JSON")])
def test_readable_failures(request_stub, capsys, error):
    request_stub["error"] = error
    assert test_live_api.main() == 1
    assert "FAIL:" in capsys.readouterr().err


def test_response_redacts_token(request_stub, capsys):
    request_stub["result"] = {"output": "Paris " + TOKEN, "model": "gemma3:4b"}
    assert test_live_api.main() == 0
    assert TOKEN not in capsys.readouterr().out


def test_redirects_refused():
    handler = test_live_api.NoRedirect()
    assert handler.redirect_request(None, None, 302, "", {}, "http://other.test") is None
