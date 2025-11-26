"""
Main entry point for validating and fixing Ominimo motor insurance prices.

The goal of this module is to take a raw price table (flat string keys) and
return a version that satisfies the core business monotonicity rules, together
with a log of all corrections applied.

Public API:
    validate_and_fix_prices(raw_prices: Dict[str, float]) -> Tuple[Dict[str, float], List[str]]
"""

from __future__ import annotations

from typing import Dict, List, Tuple, Literal

from pricing_model import PriceKey, price_key_rank
from pricing_rules import build_constraints


# ---------------------------------------------------------------------------
# Business guard-rails (also explained in the README)
#
# We do NOT build a full actuarial model here. We only encode a few simple
# relative rules that a realistic price table should respect.
#
# 1) PRODUCT_MARGIN: minimum gap between product levels
#    (MTPL < Limited Casco < Casco).
#
#    Intuition (toy example):
#      - Let MTPL pure premium = 100 units (only third-party liability).
#      - Limited Casco adds theft / fire / some own-damage. Expected cost grows to roughly ~130 units (~30% more).
#      - Full Casco adds almost all own-damage, e.g. ~170 units (~70–80% above MTPL).
#
#    Market prices are usually “compressed” by competition, expenses and
#    commissions, so we do NOT force 30–80% gaps in code.
#    Instead we require only a very small floor of +10% between levels:
#
#        Limited Casco >= (1 + PRODUCT_MARGIN) * MTPL
#        Casco >= (1 + PRODUCT_MARGIN) * Limited Casco
#
#    Anything above that is kept as-is. We only repair obviously wrong
#    situations (e.g. Casco cheaper than Limited Casco).
PRODUCT_MARGIN: float = 0.10

#
# 2) VARIANT_MARGIN: minimum gap between variants inside a product
#    (Basic/Compact < Comfort < Premium).
#
#    Intuition (again a toy example):
#      - Basic has pure premium 100.
#      - Comfort adds a bit of expected cost (glass cover, assistance, etc.), e.g. +5 units.
#      - Premium adds a bit more (replacement car, higher limits, ...), e.g. another +10 units.
#
#    So Premium ends ~15% above Basic in that small example. In code we use
#    only a gentle floor of +5% between consecutive variants:
#
#        Comfort >= (1 + VARIANT_MARGIN) * Basic/Compact
#        Premium >= (1 + VARIANT_MARGIN) * Comfort
#
#    This guarantees the ladder is monotone (Premium is not cheaper than
#    Comfort, Comfort is not cheaper than Basic/Compact), but it still lets
#    the business choose larger gaps if they want.
VARIANT_MARGIN: float = 0.05

# Prices are rounded to a simple commercial grid to keep tables readable.
PRICE_ROUNDING_STEP: float = 10.0  # round to nearest 10 EUR


# Base deductible relativities (country-level, before any city fine-tuning):
#   100 EUR: no discount (reference)
#   200 EUR: ~10% discount
#   500 EUR: ~20% discount
#
# apply_deductible_structure() uses these factors to rebuild a clean ladder
# from the 100 EUR anchor for each (product, variant).
DEDUCTIBLE_DISCOUNTS: Dict[int, float] = {
    100: 1.00,
    200: 0.90,
    500: 0.80,
}


ConstraintKind = Literal["product", "variant"]


def round_to_step(value: float, step: float = PRICE_ROUNDING_STEP) -> float:
    """
    Round a numeric value to the nearest multiple of ``step``.

    This keeps all repaired prices on a simple commercial grid.

    Example with step=10:
        184.0 -> 180.0
        185.0 -> 190.0
        187.9 -> 190.0
    """
    return step * round(value / step)


def apply_deductible_structure(prices: Dict[PriceKey, float]) -> List[str]:
    """
    For each (product, variant), enforce a consistent discount structure
    across deductibles.

    We treat the 100 EUR deductible as the base price and derive:
        price_200 ≈ 10% cheaper, price_500 ≈ 20% cheaper
    rounded to the nearest PRICE_ROUNDING_STEP.

    This produces realistic price ladders like:
        500€ ded: 640, 200€ ded: 720, 100€ ded: 800
    instead of ad-hoc values like 750, 820, 821.

    The function mutates the `prices` dict in-place and returns a list of
    log-style messages describing any changes it made.
    """
    change_log: List[str] = []

    products_with_variants = ("limited_casco", "casco")
    variants = ("compact", "basic", "comfort", "premium")
    deductibles = (100, 200, 500)

    for product in products_with_variants:
        for variant in variants:
            base_key = PriceKey(product=product, variant=variant, deductible=100)
            if base_key not in prices:
                # No clean anchor for this (product, variant) – skip.
                continue

            base_price = prices[base_key]

            for deductible in deductibles:
                key = PriceKey(product=product, variant=variant, deductible=deductible)
                if key not in prices:
                    # Input table does not contain this particular combination – skip.
                    continue

                factor = DEDUCTIBLE_DISCOUNTS[deductible]
                old_price = prices[key]
                new_price = round_to_step(base_price * factor)

                # Only log if we actually changed something.
                if abs(new_price - old_price) > 1e-6:
                    prices[key] = new_price
                    change_log.append(
                        (
                            f"Aligned {key.to_str()} from {old_price:.2f} to {new_price:.2f} "
                            f"to enforce deductible ladder (100=base, 200≈-10%, 500≈-20%) "
                            f"using base {base_key.to_str()}={base_price:.2f}."
                        )
                    )

    return change_log


def classify_constraint(description: str) -> ConstraintKind:
    """
    Classify a constraint as 'product' or 'variant' based on its description.

    The classifier relies on the fixed description strings produced in
    pricing_rules.build_constraints(). If the message says that MTPL must be
    cheaper, or that Casco must be more expensive than Limited Casco, we treat
    it as a product-level rule; everything else is treated as a variant-level
    rule.
    """
    desc = description.lower()

    if (
        "mtpl must be cheaper" in desc
        or "casco must be more expensive than limited casco" in desc
    ):
        return "product"

    return "variant"


def validate_and_fix_prices(
    raw_prices: Dict[str, float],
) -> Tuple[Dict[str, float], List[str]]:
    """
    Validate and repair an insurance pricing table.

    Parameters
    ----------
    raw_prices:
        Dictionary where each key encodes a (product, variant, deductible)
        combination, e.g.:

            {
                "mtpl": 400,
                "limited_casco_basic_100": 800,
                "limited_casco_comfort_200": 750,
                "casco_premium_100": 1200,
            }

        The helper class PriceKey.from_str(...) parses these keys into
        structured objects.

    Business rules
    --------------
    The function enforces three types of monotonicity:

      1) Product level:
             MTPL < Limited Casco < Casco

      2) Variant level (per product & deductible):
             Basic/Compact < Comfort < Premium

         The relationship between Compact and Basic is intentionally not
         forced, as stated in the assignment.

      3) Deductible level (per product & variant):
             price(500) < price(200) < price(100)

         This is implemented by a fixed discount ladder defined in
         DEDUCTIBLE_DISCOUNTS.

    Behaviour
    ---------
    * If the input already satisfies all the rules, prices are returned
      unchanged and the issues list is empty.
    * If some entries break the rules, the function increases the “too cheap”
      prices to the minimum level that satisfies the corresponding rule,
      rounding to the nearest PRICE_ROUNDING_STEP.

    Returns
    -------
    fixed_prices:
        A new dictionary with the same string keys as the input, but with all
        monotonicity rules enforced.

    issues:
        A list of messages describing each correction applied. Each message
        contains:
          * which key was changed,
          * old and new price,
          * which rule was enforced,
          * and the minimal margin used.
    """
    # Step 1: parse raw string keys into structured PriceKey objects.
    prices_by_key: Dict[PriceKey, float] = {
        PriceKey.from_str(key): float(value) for key, value in raw_prices.items()
    }

    issues: List[str] = []

    # Step 2: normalise the deductible structure first (cheapest with 500,
    # then 200, then 100) so that all further rules build on a clean ladder.
    deductible_issues = apply_deductible_structure(prices_by_key)
    issues.extend(deductible_issues)

    # Step 3: build and sort all deterministic constraints.
    constraints = build_constraints(prices_by_key)
    constraints_sorted = sorted(constraints, key=lambda c: price_key_rank(c.left))

    # Step 4: walk through constraints in a stable order and lift prices
    # that violate their rule.
    for left_key, right_key, description in constraints_sorted:
        left_price = prices_by_key[left_key]
        right_price = prices_by_key[right_key]

        kind = classify_constraint(description)
        margin = PRODUCT_MARGIN if kind == "product" else VARIANT_MARGIN

        required_min_price = left_price * (1.0 + margin)

        # If the "more expensive" side is too low, move it up to the minimum
        # acceptable value and round it on the commercial grid.
        if right_price < required_min_price - 1e-6:
            new_price = round_to_step(required_min_price)
            issues.append(
                (
                    f"Adjusted {right_key.to_str()} from {right_price:.2f} to "
                    f"{new_price:.2f} to satisfy rule: {description} "
                    f"with at least {margin * 100:.0f}% premium over "
                    f"{left_key.to_str()} (={left_price:.2f})"
                )
            )
            prices_by_key[right_key] = new_price

    # Step 5: convert PriceKey objects back to the original string format.
    fixed_prices: Dict[str, float] = {
        key.to_str(): value for key, value in prices_by_key.items()
    }

    return fixed_prices, issues


if __name__ == "__main__":
    # Small self-check / demo.
    example_prices = {
        "mtpl": 400,
        "limited_casco_basic_100": 800,
        "limited_casco_basic_200": 820,
        "limited_casco_basic_500": 750,
        "casco_basic_100": 780,
    }

    fixed, change_log = validate_and_fix_prices(example_prices)

    print("Fixed prices:")
    for key, value in sorted(fixed.items()):
        print(f"  {key}: {value:.2f} EUR")

    print("\nIssues:")
    for message in change_log:
        print(f" - {message}")
