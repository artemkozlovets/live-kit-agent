from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _cloud_smoke_enabled() -> bool:
    return os.environ.get("RUN_LIVEKIT_CLOUD_SMOKE", "").strip() == "1"


@pytest.mark.skipif(not _cloud_smoke_enabled(), reason="Set RUN_LIVEKIT_CLOUD_SMOKE=1 to run LiveKit Cloud smoke tests.")
def test_livekit_cloud_smoke_text_and_audio() -> None:
    """Optional: validates the deployed agent via lk + session reports (no browser)."""

    if shutil.which("lk") is None:
        pytest.skip("Missing `lk` CLI in PATH.")

    repo_root = Path(__file__).resolve().parents[2]
    runner = repo_root / "scripts" / "livekit_cloud_smoke.py"
    if not runner.exists():
        pytest.fail(f"Missing smoke runner: {runner}")

    cmd = [
        sys.executable,
        str(runner),
        "--scenario",
        "text",
        "--scenario",
        "audio",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )

    if proc.returncode != 0:
        # Reason: pytest should surface the artifacts dir + room name from stdout.
        pytest.fail(f"LiveKit Cloud smoke failed (exit={proc.returncode}). Output:\n{proc.stdout}")

