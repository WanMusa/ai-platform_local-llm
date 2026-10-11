"""Local API tests. No real model backend needed: the model client is faked.

Run with:  pytest -q
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.llm_client import ModelClientError, OpenAICompatibleClient, get_model_client
from app.main import app
from app.profiles import parse_json_object

TOKEN = "test-token"
AUTH = {"Authorization": "Bearer " + TOKEN}


class FakeModelClient:
    model_name = "fake-gemma"

    def __init__(self, response: str = "", error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    def chat(self, messages, *, temperature, max_tokens, json_mode=False):
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "json_mode": json_mode,
            }
        )
        if self.error:
            raise self.error
        return self.response


def make_settings(**overrides) -> Settings:
    values = dict(
        api_token=TOKEN,
        llm_base_url="http://fake:1234/v1",
        llm_model="fake-gemma",
        llm_api_key="",
        llm_timeout_seconds=5.0,
        llm_json_mode=False,
        max_input_chars=24000,
        extract_job_temperature=0.1,
        extract_job_max_tokens=1500,
        hermes_helper_temperature=0.5,
        hermes_helper_max_tokens=1024,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def fake_model():
    return FakeModelClient()


@pytest.fixture
def client(fake_model):
    settings = make_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_model_client] = lambda: fake_model
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_no_auth_required(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["model"] == "fake-gemma"
    assert body["profiles"] == ["extract_job", "hermes_helper"]


def test_extract_job_happy_path(client, fake_model):
    fake_model.response = "```json\n" + json.dumps(
        {
            "title": "Senior Data Engineer",
            "company": "Acme Pty Ltd",
            "location": "Sydney NSW",
            "salary_text": "$150k - $170k + super",
            "employment_type": "full-time",
            "responsibilities": ["Build data pipelines"],
            "requirements": ["5+ years Python"],
            "skills": ["Python", "Spark"],
            "notes": "Hybrid",
        }
    ) + "\n```"

    resp = client.post(
        "/extract-job",
        headers=AUTH,
        json={
            "source_url": "https://www.seek.com.au/job/123",
            "site": "seek",
            "page_title": "Senior Data Engineer job",
            "cleaned_text": "Acme is hiring a Senior Data Engineer in Sydney...",
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "Senior Data Engineer"
    assert body["company"] == "Acme Pty Ltd"
    assert body["skills"] == ["Python", "Spark"]
    assert body["responsibilities"] == ["Build data pipelines"]
    assert body["profile"] == "extract_job"
    assert body["model"] == "fake-gemma"
    assert body["site"] == "seek"
    assert body["warnings"] == []
    assert "Senior Data Engineer" in body["raw_model_output"]

    call = fake_model.calls[0]
    assert call["temperature"] == 0.1
    assert call["json_mode"] is True
    assert "Acme is hiring" in call["messages"][1]["content"]


def test_extract_job_invalid_json_returns_warning(client, fake_model):
    fake_model.response = "Sorry, I cannot help with that."
    resp = client.post("/extract-job", headers=AUTH, json={"cleaned_text": "some job"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] is None
    assert body["skills"] == []
    assert any("not valid JSON" in w for w in body["warnings"])
    assert body["raw_model_output"] == "Sorry, I cannot help with that."


def test_extract_job_prompt_overrides(client, fake_model):
    fake_model.response = '{"title": "X", "company": "Y", "skills": "Go"}'
    resp = client.post(
        "/extract-job",
        headers=AUTH,
        json={
            "cleaned_text": "posting",
            "system_prompt_override": "CUSTOM SYSTEM",
            "extra_instructions": "Focus on skills",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["skills"] == ["Go"]
    messages = fake_model.calls[0]["messages"]
    assert messages[0]["content"] == "CUSTOM SYSTEM"
    assert "Focus on skills" in messages[1]["content"]


def test_hermes_helper_happy_path(client, fake_model):
    fake_model.response = json.dumps(
        {"output": "Short summary.", "data": {"sentiment": "positive"}}
    )
    resp = client.post(
        "/hermes-helper",
        headers=AUTH,
        json={
            "task": "summarize",
            "text": "A long piece of text to summarize.",
            "context": {"audience": "me"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["task"] == "summarize"
    assert body["output"] == "Short summary."
    assert body["data"] == {"sentiment": "positive"}
    assert body["profile"] == "hermes_helper"
    assert body["warnings"] == []

    call = fake_model.calls[0]
    assert call["temperature"] == 0.5
    assert "Task: summarize" in call["messages"][1]["content"]
    assert '"audience": "me"' in call["messages"][1]["content"]


def test_hermes_helper_plain_text_fallback(client, fake_model):
    fake_model.response = "Just plain text."
    resp = client.post("/hermes-helper", headers=AUTH, json={"task": "t", "text": "x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["output"] == "Just plain text."
    assert body["data"] is None
    assert body["warnings"]


@pytest.mark.parametrize("path", ["/extract-job", "/hermes-helper"])
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer " + "wrong"}])
def test_auth_required(client, path, headers):
    payload = {"cleaned_text": "x", "task": "t", "text": "x"}
    resp = client.post(path, headers=headers, json=payload)
    assert resp.status_code == 401


def test_auth_fails_closed_when_token_not_configured(client):
    app.dependency_overrides[get_settings] = lambda: make_settings(api_token="")
    resp = client.post("/extract-job", headers=AUTH, json={"cleaned_text": "x"})
    assert resp.status_code == 503


def test_model_backend_error_returns_502(client, fake_model):
    fake_model.error = ModelClientError("backend down")
    resp = client.post("/extract-job", headers=AUTH, json={"cleaned_text": "x"})
    assert resp.status_code == 502


def test_input_truncation_warning(client, fake_model):
    app.dependency_overrides[get_settings] = lambda: make_settings(max_input_chars=10)
    fake_model.response = '{"title": "T", "company": "C"}'
    resp = client.post("/extract-job", headers=AUTH, json={"cleaned_text": "x" * 50})
    assert resp.status_code == 200
    assert any("truncated" in w for w in resp.json()["warnings"])


def test_parse_json_object_handles_chatter():
    assert parse_json_object('Here you go: {"a": 1} thanks') == {"a": 1}
    assert parse_json_object("[1, 2]") is None
    assert parse_json_object("") is None
    assert parse_json_object('Sure! {"a": {"b": 2}} Hope this helps {}') == {"a": {"b": 2}}


def _fake_post(captured, response):
    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json, headers=headers)
        return httpx.Response(
            response["status"], json=response["body"], request=httpx.Request("POST", url)
        )

    return fake_post


def test_openai_client_sends_expected_request(monkeypatch):
    captured: dict = {}
    body = {"choices": [{"message": {"content": "hi"}}]}
    monkeypatch.setattr(httpx, "post", _fake_post(captured, {"status": 200, "body": body}))
    client = OpenAICompatibleClient(make_settings(llm_api_key="k", llm_json_mode=True))

    out = client.chat([{"role": "user", "content": "x"}], temperature=0.2, max_tokens=10, json_mode=True)

    assert out == "hi"
    assert captured["url"] == "http://fake:1234/v1/chat/completions"
    assert captured["json"]["model"] == "fake-gemma"
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert captured["headers"]["Authorization"].endswith(" k")


def test_openai_client_maps_http_errors(monkeypatch):
    monkeypatch.setattr(httpx, "post", _fake_post({}, {"status": 500, "body": {}}))
    client = OpenAICompatibleClient(make_settings())
    with pytest.raises(ModelClientError):
        client.chat([], temperature=0, max_tokens=1)
