import pytest
from app.money import round_div, vat


@pytest.mark.parametrize("a,b,want", [(1, 2, 1), (5, 2, 3), (3, 2, 2), (1, 3, 0),
                                      (2, 3, 1), (0, 7, 0), (328900, 3000, 110)])
def test_round_div_half_up(a, b, want):
    assert round_div(a, b) == want


def test_vat_rates():
    assert vat(10963, "SA") == 1644      # 1644.45
    assert vat(21948, "AE") == 1097      # 1097.4
    assert vat(5790, "BH") == 579        # exact, fils
    assert vat(10, "AE") == 1            # 0.5 rounds up
    assert vat(10, "BH") == 1            # 1.0
    assert vat(5, "BH") == 1             # 0.5 rounds up
    assert vat(4, "BH") == 0             # 0.4