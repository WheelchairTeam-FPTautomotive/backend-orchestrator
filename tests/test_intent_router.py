"""Intent router collision / tone-free matrix + #20 ambiguous disambiguation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.car_controller import get_command_id
from services.intent_router import classify_intent_fast, normalize_utterance, _fold_vi
from services.text_norm import normalize_utterance as normalize_alias

FIXTURES = (
    Path(__file__).resolve().parent / "fixtures" / "ambiguous_intent_cases.json"
)


def _load_ambiguous() -> list[dict]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("xin chao", "FREE_TALK"),
        ("Xin chào", "FREE_TALK"),
        ("hello", "FREE_TALK"),
        ("Thời tiết hôm nay ở Hà Nội thế nào?", "FREE_TALK"),
        ("thoi tiet hom nay", "FREE_TALK"),
        ("Nên mua cổ phiếu nào thời điểm này?", "FREE_TALK"),
        ("Viết hộ tui một đoạn code Python sắp xếp mảng", "FREE_TALK"),
        ("Công thức nấu món phở bò truyền thống", "FREE_TALK"),
        ("Ke cho toi 1 joke", "FREE_TALK"),
        ("cach de bao ve xe", "RAG_SEARCH"),
        ("Làm sao để kiểm tra phanh?", "RAG_SEARCH"),
        ("bật điều hòa", "CAR_CONTROL"),
        ("bat dieu hoa", "CAR_CONTROL"),
        ("bat dieu hoa giup tui", "CAR_CONTROL"),
        # Hybrid advice: weather + sưởi kính how-long → RAG (not CAR stub)
        (
            "Thời tiết lạnh thế này thì nên bật sưởi kính bao lâu?",
            "RAG_SEARCH",
        ),
        ("Ma loi P0100", "RAG_SEARCH"),
        ("Ap suat lop", "RAG_SEARCH"),
        ("Hệ thống điều hòa HVAC được điều khiển qua đâu?", "RAG_SEARCH"),
        ("light-control-system hoạt động như thế nào?", "RAG_SEARCH"),
        ("hvac la gi", "RAG_SEARCH"),
    ],
)
def test_classify_intent_fast_matrix(query: str, expected: str) -> None:
    intent, _ms = classify_intent_fast(query)
    assert intent == expected, (
        f"{query!r} -> {intent} (want {expected}); fold={_fold_vi(query)!r}"
    )


def test_fold_vi_maps_d_stroke() -> None:
    assert _fold_vi("đóng đèn") == "dong den"
    assert _fold_vi("Điều hòa") == "dieu hoa"
    assert normalize_utterance("Mở cửa") == "mo cua"
    assert normalize_alias("Mở cửa") == "mo cua"


@pytest.mark.parametrize("case", _load_ambiguous(), ids=lambda c: c["id"])
def test_ambiguous_intent_fixtures(case: dict) -> None:
    """#20 DoD: ambiguous free-talk vs car-control + clean EN door."""
    utterance = case["utterance"]
    expected_intent = case["expected_intent"]
    expected_cmd = case.get("expected_command_id")

    normalized = normalize_utterance(utterance)
    intent, ms = classify_intent_fast(utterance, normalized=normalized)
    assert intent == expected_intent, (
        f"{case['id']}: {utterance!r} -> {intent} (want {expected_intent}); "
        f"fold={normalized!r}"
    )
    assert ms < 50, f"classify too slow: {ms}ms"

    if expected_cmd:
        cmd = get_command_id(utterance, normalized=normalized)
        assert cmd == expected_cmd, (
            f"{case['id']}: command_id={cmd} want {expected_cmd}"
        )


def test_hvac_on_command_id_tone_free() -> None:
    assert get_command_id("bat dieu hoa") == "HVAC_ON"
    assert get_command_id("Bật điều hòa") == "HVAC_ON"
