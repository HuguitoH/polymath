from typing import Protocol

import httpx

from polymath.config import Settings


class EmbeddingError(RuntimeError):
    """Raised when the embedding provider fails or returns malformed output."""


class Embedder(Protocol):
    """What the kernel needs from any embedding provider."""

    model_name: str
    dimensions: int

    async def embed(self, text: str) -> list[float]: ...


class OllamaEmbedder:
    """Embedder backed by a local Ollama instance."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._client = client
        self._base_url = settings.ollama_base_url
        self.model_name = settings.embedding_model
        self.dimensions = 1024

    async def embed(self, text: str) -> list[float]:
        if not text.strip():
            raise EmbeddingError("cannot embed empty text")

        try:
            response = await self._client.post(
                f"{self._base_url}/api/embed",
                json={"model": self.model_name, "input": text},
                timeout=30.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"embedding request failed: {exc}") from exc

        vectors = response.json().get("embeddings")
        if not vectors:
            raise EmbeddingError("provider returned no embeddings")

        vector = vectors[0]
        if len(vector) != self.dimensions:
            raise EmbeddingError(f"expected {self.dimensions} dimensions, got {len(vector)}")
        return [float(v) for v in vector]
