from __future__ import annotations

import io
import json

import pytest

from pdf_manager.integrations.ollama_client import OllamaClient


pytestmark = pytest.mark.unit


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_ollama_client_lists_local_models(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse({"models": [{"name": "llama3.1:8b"}, {"name": "mistral:latest"}]})

    monkeypatch.setattr("pdf_manager.integrations.ollama_client.urlopen", fake_urlopen)

    models = OllamaClient().list_models()

    assert models == ["llama3.1:8b", "mistral:latest"]


def test_ollama_client_generates_with_streaming_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_body = io.BytesIO()

    def fake_urlopen(request, timeout):
        captured_body.write(request.data)
        return FakeResponse({"response": "structured extraction"})

    monkeypatch.setattr("pdf_manager.integrations.ollama_client.urlopen", fake_urlopen)

    response = OllamaClient().generate(prompt="Extract this", model="llama3.1:8b")

    body = json.loads(captured_body.getvalue().decode("utf-8"))
    assert response == "structured extraction"
    assert body["model"] == "llama3.1:8b"
    assert body["prompt"] == "Extract this"
    assert body["stream"] is False


def test_ollama_client_generates_with_options(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_body = io.BytesIO()

    def fake_urlopen(request, timeout):
        captured_body.write(request.data)
        return FakeResponse({"response": "structured extraction"})

    monkeypatch.setattr("pdf_manager.integrations.ollama_client.urlopen", fake_urlopen)

    OllamaClient().generate(
        prompt="Extract this",
        model="llama3.1:8b",
        options={"temperature": 0.2, "top_p": 0.9, "num_predict": 1024},
    )

    body = json.loads(captured_body.getvalue().decode("utf-8"))
    assert body["options"] == {"temperature": 0.2, "top_p": 0.9, "num_predict": 1024}
