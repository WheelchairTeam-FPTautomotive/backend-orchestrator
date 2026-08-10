"""Automotive STT term repair unit tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.automotive_stt_correct import correct_automotive_stt
from services.text_norm import normalize_for_routing


def _corrected(text: str) -> str:
    out, _ = correct_automotive_stt(text)
    return out.lower()


def test_epp_to_epb():
    assert "epb" in _corrected("epp la gi")
    assert "epb" in _corrected("EPP")


def test_hvec_to_hvac():
    assert _corrected("hvec") == "hvac"
    assert "hvac" in _corrected("bat hvec len")


def test_carsky_hvac_mishears():
    # Phonetic / near-miss only — do NOT map arbitrary garbage (e.g. xvideo)
    assert "hvac" in _corrected("What Is A Sea")
    assert "hvac" in _corrected("what is a see")
    assert "hvac" in _corrected("h v a c")
    assert "xvideo" in _corrected("What is xvideo")  # leave far misses alone


def test_spaced_acronyms():
    assert "epb" in _corrected("e p b la gi")
    assert "tpms" in _corrected("tp ms reset")
    assert "adas" in _corrected("a das phanh khan cap")


def test_non_regression_volume_and_common_words():
    assert correct_automotive_stt("van volume xuong")[0] == "van volume xuong"
    assert correct_automotive_stt("app")[0] == "app"
    assert correct_automotive_stt("map")[0] == "map"
    assert correct_automotive_stt("can")[0] == "can"
    assert correct_automotive_stt("hvac")[0].lower() == "hvac"
    assert correct_automotive_stt("epb")[0].lower() == "epb"
    # Must NOT glue Vietnamese syllables across word boundaries
    assert correct_automotive_stt("Mở cửa xe bên lái.")[0] == "Mở cửa xe bên lái."
    assert correct_automotive_stt("Sấy kính sau xe Tucson")[0] == "Sấy kính sau xe Tucson"


def test_eco_ecu_never_cross_mapped():
    # Google often confuses ECU↔ECO; corrector must leave both alone (no hardcode).
    assert correct_automotive_stt("eco")[0].lower() == "eco"
    assert correct_automotive_stt("ecu")[0].lower() == "ecu"
    assert correct_automotive_stt("what is eco")[0].lower() == "what is eco"
    assert correct_automotive_stt("what is ecu")[0].lower() == "what is ecu"
    assert correct_automotive_stt("eco")[1] == []
    assert correct_automotive_stt("ecu")[1] == []


def test_normalize_for_routing_folds_after_correct():
    corrected, folded, fixes = normalize_for_routing("Bật hvec lên")
    assert "hvac" in corrected.lower()
    assert "hvac" in folded
    assert any(dst == "hvac" for _, dst in fixes)
