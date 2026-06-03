#!/usr/bin/env python3
"""Unit tests for simplified US/UK voice registry."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_BACKEND = Path(__file__).resolve().parents[1]
if str(REPO_BACKEND) not in sys.path:
    sys.path.insert(0, str(REPO_BACKEND))

from modules.tts import voice_registry as vr


def test_accents_only_us_uk() -> None:
    assert vr.ALL_ACCENTS == ("US", "UK")
    assert "Australian" not in vr.ALL_ACCENTS
    assert "Indian" not in vr.ALL_ACCENTS
    print("OK test_accents_only_us_uk")


def test_us_male_voices() -> None:
    names = sorted(v.name for v in vr.list_voices(gender="male", accent="US"))
    assert names == ["Adam", "Daniel", "Josh"]
    print("OK test_us_male_voices")


def test_us_female_voices() -> None:
    names = sorted(v.name for v in vr.list_voices(gender="female", accent="US"))
    assert names == ["Bella", "Rachel", "Sarah"]
    print("OK test_us_female_voices")


def test_uk_male_voices() -> None:
    names = sorted(v.name for v in vr.list_voices(gender="male", accent="UK"))
    assert names == ["Arthur", "Callum", "George"]
    print("OK test_uk_male_voices")


def test_uk_female_voices() -> None:
    names = sorted(v.name for v in vr.list_voices(gender="female", accent="UK"))
    assert names == ["Charlotte", "Emma", "Sophie"]
    print("OK test_uk_female_voices")


def test_no_voices_for_invalid_combo() -> None:
    # No voices should match a non-existent accent.
    assert vr.list_voices(gender="male", accent="Australian") == []
    print("OK test_no_voices_for_invalid_combo")


def test_get_voice_by_id() -> None:
    rachel = vr.get_voice("elevenlabs", "lcMyyd2HUfFzxdCaC4Ta")
    assert rachel is not None
    assert rachel.name == "Rachel"
    assert rachel.accent == "US"
    george = vr.get_voice("elevenlabs", "JBFqnCBsd6RMkjVDRZzb")
    assert george is not None
    assert george.name == "George"
    assert george.accent == "UK"
    print("OK test_get_voice_by_id")


def main() -> int:
    tests = [
        test_accents_only_us_uk,
        test_us_male_voices,
        test_us_female_voices,
        test_uk_male_voices,
        test_uk_female_voices,
        test_no_voices_for_invalid_combo,
        test_get_voice_by_id,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as exc:
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
