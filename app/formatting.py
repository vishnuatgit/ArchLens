"""
Number formatting shared by the web pages and the Markdown export.
"""

from decimal import ROUND_HALF_UP, Decimal

_COMPACT_UNITS = ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "k"))


def _one_decimal(value: Decimal) -> Decimal:
    # Round half up (1.25 -> 1.3); round() would use banker's rounding
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def compact_number(value: float | None) -> str:
    """Shortens large counts for display: 54641 -> '54.6k', 1250000 -> '1.3M'."""
    number = Decimal(str(value or 0))
    for index, (divisor, suffix) in enumerate(_COMPACT_UNITS):
        if abs(number) >= divisor:
            scaled = _one_decimal(number / divisor)
            # 999_999 rounds to 1000.0k; promote it to the next unit instead
            if abs(scaled) >= 1000 and index > 0:
                divisor, suffix = _COMPACT_UNITS[index - 1]
                scaled = _one_decimal(number / divisor)
            return f"{scaled.normalize():f}{suffix}"
    return f"{number.normalize():f}"


def format_size_kb(size_kb: float | None) -> str:
    """Formats a size reported by GitHub in kilobytes: 980 -> '980 KB', 13619 -> '13.3 MB'."""
    size = float(size_kb or 0)
    if size < 1024:
        return f"{size:g} KB"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} MB"
    return f"{size / (1024 * 1024):.1f} GB"
