from decimal import Decimal as D

import pytest

from trimatch.evaluation import aggregate, calibration, field_key, percentile, score_document
from trimatch.generate.data import build_split, load_seed_data


@pytest.fixture(scope="module")
def inv():
    docs = build_split("e2e", load_seed_data())
    return next(d.label for d in docs if d.kind == "invoice" and d.po_ref == "PO-003")


def test_field_key():
    assert field_key("lines.3.quantity") == "lines.quantity"
    assert field_key("bl_refs.0") == "bl_refs"
    assert field_key("total_ht") == "total_ht"


def test_perfect_prediction(inv):
    s = score_document("x", "clean", inv, inv)
    assert s.doc_right and s.fields_right == s.fields_total and s.lines_right == len(inv.lines)


def test_one_wrong_quantity_breaks_one_line(inv):
    pred = inv.model_copy(deep=True)
    pred.lines[2].quantity.value = D(9)
    s = score_document("x", "blur", pred, inv)
    assert s.fields_total - s.fields_right == 1
    assert s.lines_right == len(inv.lines) - 1
    assert not s.doc_right
    assert s.per_field["lines.quantity"] == (len(inv.lines) - 1, len(inv.lines))
    assert s.wrong == [("lines.2.quantity", D(8), D(9))]


def test_number_normalisation_counts_equal_values_as_right(inv):
    pred = inv.model_copy(deep=True)
    pred.total_ht.value = D(5698)  # same number, other scale
    assert score_document("x", "clean", pred, inv).doc_right


def test_wrong_doc_type_scores_zero(inv):
    s = score_document("x", "rot", None, inv)
    assert s.fields_right == 0 and not s.doc_right


def test_aggregate_by_variant(inv):
    pred = inv.model_copy(deep=True)
    pred.number.value = "FA-WRONG"
    scores = [score_document("a", "clean", inv, inv), score_document("b", "stamp", pred, inv)]
    agg = aggregate(scores, "variant")
    assert agg["all"].docs == 2 and agg["all"].docs_right == 1
    assert agg["clean"].docs_right == 1 and agg["stamp"].docs_right == 0


def test_calibration_buckets(inv):
    s = score_document("a", "clean", inv, inv)
    rows = {label: (n, share) for label, n, share in calibration([s])}
    assert rows["[0.99, 1.00]"] == (s.fields_total, 1.0)


def test_percentile():
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50) == 3.0
    assert percentile([], 50) is None
