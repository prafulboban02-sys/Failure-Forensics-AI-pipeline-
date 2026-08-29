"""
Math check for line items - quantity times unit price should equal the
total. Doing this in plain Python instead of asking the LLM to check it.

Tried the prompt-only version first and it didn't work reliably (a small
local model just isn't consistent at multiplication inside free text
generation, even when you tell it exactly what to check). This is the
actual fix.

One gotcha I found after running this against a bigger batch: credit
memos/refunds correctly show a NEGATIVE total for a normal positive
quantity x price (e.g. 50 x $42 = $2,100, refunded as -$2,100). That's
not a math error, so a sign flip with the same magnitude gets a pass
instead of getting flagged.
"""

from src.pipeline.schemas import ExtractedEntities

TOLERANCE = 1.0  # a dollar of rounding drift is fine, don't flag that


def check_line_item_arithmetic(entities: ExtractedEntities) -> list[str]:
    flags = []
    for item in entities.line_items:
        if item.quantity is None or item.unit_price is None or item.line_total is None:
            continue  # nothing to verify without all three numbers
        expected = item.quantity * item.unit_price
        actual = item.line_total

        if abs(expected - actual) <= TOLERANCE:
            continue  # matches exactly (within rounding) -- fine

        if abs(expected - abs(actual)) <= TOLERANCE and actual < 0:
            continue  # magnitude matches, sign flipped -- a legitimate credit/refund, not an error

        label = item.description or "line item"
        flags.append(
            f"Arithmetic mismatch on '{label}': {item.quantity} x "
            f"{item.unit_price} = {expected:,.2f}, but stated total is "
            f"{actual:,.2f}"
        )
    return flags
