from unittest.mock import MagicMock, patch

from core.schemas import ChatMessage
from api.services import openai_service


def _fake_response():
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    return resp


def _call(api_key=None):
    history = [ChatMessage(sender="user", text="hi")]
    with patch.object(openai_service.requests, "post", return_value=_fake_response()) as post:
        text, _ = openai_service.call_openai_api(api_key, "sys", history)
    return text, post


def test_defaults_unchanged(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    _, post = _call("sk-test")
    assert post.call_args.args[0] == "https://api.openai.com/v1/chat/completions"
    assert post.call_args.kwargs["json"]["model"] == "gpt-4o-mini"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-test"


def test_request_goes_to_configured_url_and_model(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "Qwen/Qwen3-8B")
    text, post = _call(api_key=None)
    assert text == "hello"
    assert post.call_args.args[0] == "http://localhost:8000/v1/chat/completions"
    assert post.call_args.kwargs["json"]["model"] == "Qwen/Qwen3-8B"
    assert "Authorization" not in post.call_args.kwargs["headers"]


def test_available_when_base_url_set_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    assert openai_service.openai_configured() is False
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:8000/v1")
    assert openai_service.openai_configured() is True


def test_provider_order(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER_ORDER", raising=False)
    assert openai_service.get_provider_order() == ["gemini", "openai"]
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "openai, gemini")
    assert openai_service.get_provider_order() == ["openai", "gemini"]
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "bogus")
    assert openai_service.get_provider_order() == ["gemini", "openai"]
