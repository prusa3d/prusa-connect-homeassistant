"""scripts/next_version.py: the version a release cut moves to."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "next_version", Path(__file__).resolve().parent.parent / "scripts" / "next_version.py"
)
assert _SPEC is not None
assert _SPEC.loader is not None
next_version_module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(next_version_module)
next_version = next_version_module.next_version


@pytest.mark.parametrize(
    ("current", "kind", "bump", "expected"),
    [
        ("0.1.1", "stable", "patch", "0.1.2"),
        ("0.1.1", "stable", "minor", "0.2.0"),
        ("0.1.1", "stable", "major", "1.0.0"),
        ("0.1.1", "beta", "minor", "0.2.0-beta.1"),
        ("0.2.0-beta.1", "beta", "major", "0.2.0-beta.2"),
        ("0.2.0-alpha.3", "beta", "patch", "0.2.0-beta.1"),
        ("0.2.0-alpha.3", "alpha", "patch", "0.2.0-alpha.4"),
        ("0.2.0-beta.2", "stable", "patch", "0.2.0"),
    ],
)
def test_next_version(current: str, kind: str, bump: str, expected: str) -> None:
    assert next_version(current, kind, bump) == expected


@pytest.mark.parametrize(
    ("current", "kind", "reason"),
    [
        ("0.2.0-beta.1", "alpha", "past alpha"),
        ("0.1", "stable", "not a version"),
        ("v0.1.1", "stable", "not a version"),
    ],
)
def test_refused(current: str, kind: str, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        next_version(current, kind, "patch")
