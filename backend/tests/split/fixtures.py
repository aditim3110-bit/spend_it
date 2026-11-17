"""Loads the shared split fixtures from <repo>/fixtures/split/."""

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPO_ROOT / "fixtures" / "split"
SCHEMA_PATH = REPO_ROOT / "fixtures" / "schema" / "split.schema.json"


def fixture_files() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("*.json"))


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
