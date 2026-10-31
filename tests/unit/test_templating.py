import pytest

from app.templating import compact_number, format_size_kb


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0"),
        (None, "0"),
        (245, "245"),
        (999, "999"),
        (1000, "1k"),
        (12089, "12.1k"),
        (54641, "54.6k"),
        (999_999, "1M"),
        (1_250_000, "1.3M"),
        (2_000_000_000, "2B"),
    ],
)
def test_compact_number(value, expected):
    assert compact_number(value) == expected


@pytest.mark.parametrize(
    ("size_kb", "expected"),
    [(0, "0 KB"), (980, "980 KB"), (13635, "13.3 MB"), (3 * 1024 * 1024, "3.0 GB")],
)
def test_format_size_kb(size_kb, expected):
    assert format_size_kb(size_kb) == expected
