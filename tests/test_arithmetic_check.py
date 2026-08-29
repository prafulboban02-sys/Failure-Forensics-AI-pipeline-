from src.pipeline.schemas import ExtractedEntities, LineItem
from src.pipeline.arithmetic_check import check_line_item_arithmetic


def test_no_line_items_returns_no_flags():
    entities = ExtractedEntities()
    assert check_line_item_arithmetic(entities) == []


def test_correct_arithmetic_returns_no_flags():
    entities = ExtractedEntities(line_items=[
        LineItem(description="widgets", quantity=10, unit_price=5.0, line_total=50.0)
    ])
    assert check_line_item_arithmetic(entities) == []


def test_mismatched_arithmetic_is_flagged():
    """Mirrors the real bug: 400 x 3.75 = 1500, but document states 2200."""
    entities = ExtractedEntities(line_items=[
        LineItem(description="precision bearings", quantity=400, unit_price=3.75, line_total=2200.0)
    ])
    flags = check_line_item_arithmetic(entities)
    assert len(flags) == 1
    assert "precision bearings" in flags[0]
    assert "1,500.00" in flags[0]
    assert "2,200.00" in flags[0]


def test_small_rounding_drift_is_tolerated():
    entities = ExtractedEntities(line_items=[
        LineItem(description="x", quantity=3, unit_price=10.33, line_total=31.0)  # 30.99 vs 31.0
    ])
    assert check_line_item_arithmetic(entities) == []


def test_incomplete_line_item_is_skipped_not_flagged():
    """Can't verify arithmetic without all three numbers -- shouldn't crash
    or produce a false positive."""
    entities = ExtractedEntities(line_items=[
        LineItem(description="partial", quantity=5, unit_price=None, line_total=100.0)
    ])
    assert check_line_item_arithmetic(entities) == []


def test_multiple_line_items_flags_only_the_wrong_one():
    entities = ExtractedEntities(line_items=[
        LineItem(description="correct item", quantity=2, unit_price=10.0, line_total=20.0),
        LineItem(description="wrong item", quantity=2, unit_price=10.0, line_total=999.0),
    ])
    flags = check_line_item_arithmetic(entities)
    assert len(flags) == 1
    assert "wrong item" in flags[0]


def test_credit_memo_negative_total_is_not_flagged():
    """Mirrors the real batch-run finding: 50 x $42.00 = $2,100, refunded
    as -$2,100. Matching magnitude with a flipped sign is a legitimate
    credit/refund, not an arithmetic error."""
    entities = ExtractedEntities(line_items=[
        LineItem(description="return credit", quantity=50, unit_price=42.0, line_total=-2100.0)
    ])
    assert check_line_item_arithmetic(entities) == []


def test_negative_total_with_wrong_magnitude_is_still_flagged():
    """A negative total doesn't get a free pass -- it still has to match
    in magnitude to be treated as a legitimate credit."""
    entities = ExtractedEntities(line_items=[
        LineItem(description="bad credit", quantity=50, unit_price=42.0, line_total=-500.0)
    ])
    flags = check_line_item_arithmetic(entities)
    assert len(flags) == 1
    assert "bad credit" in flags[0]
