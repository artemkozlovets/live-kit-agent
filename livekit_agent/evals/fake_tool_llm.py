from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class FakeToolCall:
    call_id: str
    name: str
    arguments: str | None = None


@dataclass(frozen=True)
class FakeDelta:
    tool_calls: list[FakeToolCall] | None = None


@dataclass(frozen=True)
class FakeChunk:
    delta: FakeDelta | None = None


class FakeToolLLMStream:
    def __init__(self, chunks: list[FakeChunk]) -> None:
        self._chunks = list(chunks)
        self._idx = 0

    async def __aenter__(self) -> "FakeToolLLMStream":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    def __aiter__(self) -> "FakeToolLLMStream":
        return self

    async def __anext__(self) -> FakeChunk:
        if self._idx >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._idx]
        self._idx += 1
        return chunk


class FakeToolLLM:
    """Deterministic stand-in for the LiveKit LLM tool-calling interface.

    The agent calls `tool_llm.chat(...)` and expects an async stream of chunks
    where each chunk has `delta.tool_calls` with incremental tool-call content.
    """

    def __init__(self, *, responses: Iterable[list[FakeChunk]] | None = None) -> None:
        self._responses: list[list[FakeChunk]] = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def push_response(self, chunks: list[FakeChunk]) -> None:
        self._responses.append(list(chunks))

    def chat(self, **kwargs: Any) -> FakeToolLLMStream:
        self.calls.append(dict(kwargs))
        if not self._responses:
            raise RuntimeError("FakeToolLLM has no queued responses")
        return FakeToolLLMStream(self._responses.pop(0))

