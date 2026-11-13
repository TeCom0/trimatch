from decimal import Decimal as D

from trimatch.money import fr_amount, fr_qty, line_total, q2, totals, vat_breakdown


def test_q2_rounds_half_up():
    assert q2(D("0.005")) == D("0.01")
    assert q2(D("2.675")) == D("2.68")  # float would give 2.67
    assert q2(D("-0.005")) == D("-0.01")


def test_line_total():
    assert line_total(D("12.5"), D("52.00")) == D("650.00")
    assert line_total(D(3), D("23.335")) == D("70.01")


def test_vat_rounded_once_per_rate():
    # three 0.025 VAT lines would round to 0.03 each (0.09) if done per line; per rate it is 0.08
    lines = [(D(20), D("0.125")), (D(20), D("0.125")), (D(20), D("0.125"))]
    assert vat_breakdown(lines) == [(D(20), D("0.38"), D("0.08"))]


def test_totals_with_exempt_and_two_rates():
    lines = [(D(0), D("432.00")), (D(20), D("1710.50")), (D(10), D("100.00"))]
    total_ht, vat, ttc = totals(lines)
    assert total_ht == D("2242.50")
    assert vat == [
        (D(0), D("432.00"), D("0.00")),
        (D(10), D("100.00"), D("10.00")),
        (D(20), D("1710.50"), D("342.10")),
    ]
    assert ttc == D("2594.60")


def test_french_formats():
    assert fr_amount(D("2484.6")) == "2 484,60"
    assert fr_qty(D(10)) == "10"
    assert fr_qty(D("12.50")) == "12,5"
