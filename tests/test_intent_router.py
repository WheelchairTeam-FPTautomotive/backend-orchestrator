"""Intent router collision / tone-free matrix for pattern-gate hardening."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.intent_router import classify_intent_fast, _fold_vi


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
