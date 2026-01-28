from __future__ import annotations

from pathlib import Path


def test_repo_contains_no_vapi_path_references() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    excluded_dirnames = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".codex",
        "docs",
        "local-observability",
        "console-recordings",
        "vapi_export",
    }

    needle = b"/" + b"vapi" + b"/"
    offenders: list[str] = []

    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue

        relative_parts = path.relative_to(repo_root).parts

        if any(part in excluded_dirnames for part in relative_parts):
            continue

        if len(relative_parts) >= 2 and relative_parts[0] in {"api_server", "livekit_agent"} and relative_parts[1] == "tests":
            continue

        try:
            contents = path.read_bytes()
        except OSError:
            continue

        if needle in contents:
            offenders.append(str(path.relative_to(repo_root)))

    assert offenders == [], "Found legacy /vapi/ references:\n" + "\n".join(offenders)
