"""Pluggable embedding providers for the USER-TRIGGERED semantic search path.

Nothing in the automatic path (hooks, reflection, SessionStart injection) computes
embeddings. Only `huh search --semantic` does. Model + API route are configurable
via the store config so the mock can be swapped for a real local model later:

    embedding_provider : "mock" | "ollama"
    embedding_model    : e.g. "qllama/bge-large-en-v1.5:latest"
    embedding_api_url  : e.g. "http://localhost:11434/api/embeddings"
    embedding_dim      : e.g. 1024

Default provider is "mock" (deterministic, no network). Providers raise on failure;
callers fall back to keyword/rg search.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import urllib.request
from typing import List, Protocol


class EmbeddingProvider(Protocol):
    dim: int

    def embed(self, text: str) -> List[float]: ...


class MockEmbeddingProvider:
    """Deterministic pseudo-embedding derived from a hash.

    Stable across runs (so dedup/tests behave) and dependency-free, but NOT
    semantically meaningful — a placeholder until a real provider is enabled.
    """

    def __init__(self, dim: int = 1024):
        self.dim = dim

    def embed(self, text: str) -> List[float]:
        vec: List[float] = []
        counter = 0
        while len(vec) < self.dim:
            digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
            for off in range(0, len(digest), 4):
                if len(vec) >= self.dim:
                    break
                n = struct.unpack(">I", digest[off : off + 4])[0]
                vec.append((n / 2**32) * 2.0 - 1.0)  # -> [-1, 1)
            counter += 1
        return _l2_normalize(vec)


class OllamaEmbeddingProvider:
    """Calls a local Ollama-compatible /api/embeddings route. Model + URL configurable."""

    def __init__(self, model: str, api_url: str, dim: int = 0, timeout: float = 10.0):
        self.model = model
        self.api_url = api_url
        self.dim = dim
        self.timeout = timeout

    def embed(self, text: str) -> List[float]:
        payload = json.dumps({"model": self.model, "prompt": text}).encode()
        req = urllib.request.Request(
            self.api_url, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        vec = data.get("embedding")
        if not vec and isinstance(data.get("data"), list) and data["data"]:
            vec = data["data"][0].get("embedding")
        if not vec:
            raise ValueError(f"no embedding in response from {self.api_url}")
        return _l2_normalize([float(x) for x in vec])


def _l2_normalize(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def cosine(a: List[float], b: List[float]) -> float:
    """Cosine similarity. Assumes inputs are L2-normalized (providers normalize)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def get_provider(config: dict) -> EmbeddingProvider:
    """Build an embedding provider from store config. Defaults to the mock."""
    provider = str(config.get("embedding_provider") or "mock").lower()
    dim = int(config.get("embedding_dim", 1024))
    if provider == "ollama":
        return OllamaEmbeddingProvider(
            model=config.get("embedding_model", "qllama/bge-large-en-v1.5:latest"),
            api_url=config.get(
                "embedding_api_url", "http://localhost:11434/api/embeddings"
            ),
            dim=dim,
        )
    return MockEmbeddingProvider(dim=dim)
