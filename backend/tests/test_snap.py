"""Box snapping (extract/snap.py) on hand-built text layers: no PDF, no Gemini."""

from trimatch.extract.snap import Item, PageText, Rect, occurrences, snap

LINE_H = 0.02


def layer(rows: list[tuple[float, str]]) -> PageText:
    """A page with one text run per (y, text); each char 0.01 wide from x = 0.1."""
    chars, rects, starts, ends = [], [], [], []
    for y, text in rows:
        for i, ch in enumerate(text):
            if ch == " ":
                continue
            prev = i == 0 or text[i - 1] == " " or not ch.isalnum() or not text[i - 1].isalnum()
            nxt = (
                i == len(text) - 1
                or text[i + 1] == " "
                or not ch.isalnum()
                or not text[i + 1].isalnum()
            )
            chars.append(ch.casefold())
            rects.append(Rect(0.1 + i * 0.01, y, 0.11 + i * 0.01, y + LINE_H))
            starts.append(prev)
            ends.append(nxt)
    return PageText("".join(chars), rects, starts, ends)


PAGE = layer(
    [
        (0.10, "FACTURE FA-DA-2026-0162"),
        (0.40, "ANF-HT05 Huile 12 bidon 92,00 10 % 1 104,00"),
        (0.43, "ANF-RZ05 Riz 20 sac 55,00 10 % 1 100,00"),
        (0.50, "TVA 10 % (base 2 204,00) 220,40"),
    ]
)


def at(rect: Rect, dy: float) -> Rect:
    return rect.shifted(0, dy)


def test_occurrences_ignore_spaces_and_respect_word_boundaries():
    assert len(occurrences(PAGE, "2 204,00")) == 1
    assert len(occurrences(PAGE, "2204,00")) == 1
    assert len(occurrences(PAGE, "10 %")) == 3
    assert occurrences(PAGE, "04") == []  # inside "1 104,00", not a word of its own
    assert occurrences(PAGE, "fa-da-2026-0162")  # case-insensitive


def test_unique_value_snaps_exactly_even_when_the_model_box_is_far_off():
    [true] = occurrences(PAGE, "FA-DA-2026-0162")
    out = snap([Item("n", "FA-DA-2026-0162", at(true, 0.2))], PAGE)
    b = out["n"]
    assert not b.approximate and (b.x0, b.y0) == (round(true.x0, 4), round(true.y0, 4))


def test_repeated_value_takes_the_row_of_its_line():
    """Gemini put line 0's '10 %' one row low; the line's unique ref anchors the row."""
    [ref0] = occurrences(PAGE, "ANF-HT05")
    [ref1] = occurrences(PAGE, "ANF-RZ05")
    rates = occurrences(PAGE, "10 %")
    row0 = next(r for r in rates if abs(r.cy - ref0.cy) < 0.005)
    items = [
        Item("ref0", "ANF-HT05", ref0, line=0),
        Item("ref1", "ANF-RZ05", ref1, line=1),
        Item("rate0", "10 %", at(row0, 0.03), line=0),  # model box on line 1's row
    ]
    out = snap(items, PAGE)
    assert abs((out["rate0"].y0 + out["rate0"].y1) / 2 - row0.cy) < 1e-3


def test_systematic_shift_is_estimated_from_unique_values():
    dy = 0.03  # the model boxes are all one row low
    names = ["FA-DA-2026-0162", "ANF-HT05", "ANF-RZ05", "220,40"]
    items = [Item(n, n, at(occurrences(PAGE, n)[0], dy)) for n in names]
    [base_row] = [r for r in occurrences(PAGE, "10 %") if r.cy > 0.5]
    items.append(Item("vat_rate", "10 %", at(base_row, dy)))  # outside any table line
    out = snap(items, PAGE)
    assert abs((out["vat_rate"].y0 + out["vat_rate"].y1) / 2 - base_row.cy) < 1e-3


def test_misread_value_keeps_a_shifted_approximate_box():
    names = ["FA-DA-2026-0162", "ANF-HT05", "ANF-RZ05"]
    dy = 0.03
    items = [Item(n, n, at(occurrences(PAGE, n)[0], dy)) for n in names]
    [true] = occurrences(PAGE, "2 204,00")
    items.append(Item("base", "2 204,04", at(true, dy)))  # misread: not on the page
    b = snap(items, PAGE)["base"]
    assert b.approximate and abs(b.y0 - true.y0) < 1e-3  # shift removed


def test_no_text_layer_keeps_model_boxes_marked_approximate():
    r = Rect(0.1, 0.2, 0.3, 0.25)
    out = snap([Item("x", "abc", r), Item("y", "def", None)], None)
    assert out["x"].approximate and (out["x"].x0, out["x"].y1) == (0.1, 0.25)
    assert "y" not in out


def test_far_occurrence_is_not_taken():
    rates = occurrences(PAGE, "10 %")
    far = Rect(0.9, 0.9, 0.95, 0.92)
    b = snap([Item("r", "10 %", far)], PAGE)["r"]
    assert b.approximate and b.x0 == 0.9 and rates
