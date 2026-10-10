"""Guidance registry consistency (exercise information screen, Gate A).

Proves the fixed launch content stays coherent with the seeded catalog and
the bundled frontend artwork: every registry key is a seeded default, every
seeded default has exactly one registry entry, every entry obeys the public
response bounds (step/tip counts, text lengths, HTTPS URLs, animation-key
format), and every animation key has both SVG frames bundled in the frontend
assets. No content-management or JSON parsing layer is involved; the registry
is typed Python data validated through the response schema.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from app.db import connect
from app.guidance import DEFAULT_GUIDANCE
from app.schemas.exercises import ExerciseGuidanceResponse

# frontend/src/assets/exercises relative to this test file (repo layout is
# language-neutral for bundled assets, like tests/fixtures).
ASSETS_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src" / "assets" / "exercises"


def seeded_default_ids(database_path: Path) -> set[str]:
    with connect(database_path) as conn:
        rows = conn.execute(
            "SELECT id FROM exercise_catalog WHERE is_default = 1 AND created_by IS NULL"
        ).fetchall()
    return {str(row["id"]) for row in rows}


def test_registry_keys_are_seeded_defaults(migrated_db: Path) -> None:
    defaults = seeded_default_ids(migrated_db)
    unknown = set(DEFAULT_GUIDANCE) - defaults
    assert unknown == set()


def test_every_seeded_default_has_guidance(migrated_db: Path) -> None:
    defaults = seeded_default_ids(migrated_db)
    missing = defaults - set(DEFAULT_GUIDANCE)
    assert missing == set()


def test_registry_entries_obey_response_bounds() -> None:
    for entry_id, guidance in DEFAULT_GUIDANCE.items():
        payload = {
            "technique_steps": list(guidance.technique_steps),
            "form_tips": list(guidance.form_tips),
            "animation_key": guidance.animation_key,
            "sources": [{"title": source.title, "url": source.url} for source in guidance.sources],
        }
        try:
            validated = ExerciseGuidanceResponse.model_validate(payload)
        except ValidationError as exc:  # pragma: no cover - failure detail
            raise AssertionError(f"invalid guidance for {entry_id}: {exc}") from exc
        # Non-empty bounded text content with no blank entries.
        assert all(step.strip() for step in validated.technique_steps)
        assert all(tip.strip() for tip in validated.form_tips)
        assert all(source.title.strip() for source in validated.sources)
        assert all(source.url.startswith("https://") for source in validated.sources)


def test_animation_keys_have_both_bundled_frames() -> None:
    for entry_id, guidance in DEFAULT_GUIDANCE.items():
        for suffix in ("start", "finish"):
            frame = ASSETS_DIR / f"{guidance.animation_key}-{suffix}.svg"
            assert frame.is_file(), f"missing frame for {entry_id}: {frame}"


def test_animation_keys_are_unique_per_default() -> None:
    keys = [guidance.animation_key for guidance in DEFAULT_GUIDANCE.values()]
    assert len(keys) == len(set(keys))
