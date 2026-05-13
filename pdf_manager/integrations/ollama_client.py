"""Local Ollama API client.

The client uses only Python's standard library and talks to a local Ollama
server by default. It does not require Ollama for normal application startup.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


@dataclass(slots=True)
class OllamaClient:
    """Client for local Ollama model operations."""

    base_url: str = "http://localhost:11434"
    timeout_seconds: int = 120

    def list_models(self) -> list[str]:
        """Return locally available model names."""
        payload = self._request("GET", "/api/tags")
        models = payload.get("models", [])
        return sorted(str(item.get("name", "")) for item in models if item.get("name"))

    def generate_summary(self, text: str, model: str) -> str:
        """Generate a local summary using the default prompt style."""
        return self.generate(prompt=text, model=model)

    def generate(self, prompt: str, model: str) -> str:
        """Generate a response from a local model with streaming disabled."""
        payload = self._request(
            "POST",
            "/api/generate",
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
            },
        )
        return str(payload.get("response", "")).strip()

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(url, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except URLError as exc:
            raise ConnectionError(f"Could not connect to local Ollama at {self.base_url}: {exc}") from exc
