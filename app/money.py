"""Integer-only money helpers (Part 2). No floats anywhere."""

CURRENCY = {"AE": "AED", "SA": "SAR", "BH": "BHD"}
VAT_PERCENT = {"AE": 5, "SA": 15, "BH": 10}


def round_div(a: int, b: int) -> int:
    """a / b rounded half up, for a >= 0 and b > 0, using integers only."""
    return (2 * a + b) // (2 * b)


def vat(net: int, country: str) -> int:
    """VAT on net in minor units, rounded half up once."""
    return round_div(net * VAT_PERCENT[country], 100)