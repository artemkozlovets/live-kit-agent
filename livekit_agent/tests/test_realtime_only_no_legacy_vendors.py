from __future__ import annotations

from pathlib import Path


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def test_runtime_code_contains_no_legacy_vendors_or_engines() -> None:
    """Guardrail: this repo is OpenAI Realtime-only.

    We intentionally removed:
    - the legacy agent engine (Deepgram STT + Cartesia TTS + optional Google/Gemini tool-LLM)
    - Gemini network calls in the backend

    This test prevents accidental reintroduction.
    """

    repo_root = Path(__file__).resolve().parents[2]
    runtime_roots = [
        repo_root / "livekit_agent",
        repo_root / "api_server",
    ]

    banned_substrings = [
        # Agent legacy engine / plugins
        "AGENT_ENGINE",
        "deepgram",
        "cartesia",
        "silero",
        "DEEPGRAM_API_KEY",
        "CARTESIA_API_KEY",
        "GOOGLE_API_KEY",
        # Backend Gemini (network)
        "GEMINI_API_KEY",
        "generativelanguage.googleapis.com",
    ]

    offenders: list[str] = []

    for root in runtime_roots:
        for path in root.rglob("*.py"):
            if "tests" in path.parts:
                continue
            text = _read_text(path)
            for needle in banned_substrings:
                if needle in text:
                    offenders.append(f"{path}: contains {needle!r}")

    assert offenders == [], "Found legacy vendor/engine references:\n" + "\n".join(offenders)

