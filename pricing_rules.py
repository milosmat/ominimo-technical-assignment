"""
Business rules for the Ominimo motor pricing table.

This module translates the high-level pricing rules into a concrete list of
pairwise constraints between prices, e.g.:

    price[mtpl] < price[limited_casco_basic_100]

Each constraint is represented as:

    Constraint(left=cheaper_key, right=more_expensive_key, description="...")

Keeping constraint generation in a separate module makes it easy to:
- see which business rules are enforced,
- test the rule construction independently from the fixing algorithm, and
- keep validate_and_fix_prices focused on the search/repair logic rather than on domain-specific combinations.
"""

from typing import Dict, List

from pricing_model import Constraint, PriceKey


# Products that participate in variant/deductible rules.
# MTPL is intentionally excluded because, in this assignment, it has no
# variant or deductible dimension.
PRODUCTS_WITH_VARIANTS = ("limited_casco", "casco")

# Variant and deductible “grid” we support in this assignment.
# The VARIANTS tuple documents all recognised variant names; we only build
# constraints for keys that are actually present in the input price table.
VARIANTS = ("compact", "basic", "comfort", "premium")
DEDUCTIBLES = (100, 200, 500)


def _add_product_level_constraints(
    prices_by_key: Dict[PriceKey, float],
    constraints: List[Constraint],
) -> None:
    """
    Add constraints of the form:

        MTPL < Limited Casco < Casco

    The rules are applied only to combinations that actually exist in the
    provided price table. This allows the same logic to work for both
    complete and partially populated pricing grids.
    """
    mtpl_key = PriceKey("mtpl")

    # MTPL vs Limited Casco (if MTPL is present at all).
    # We require MTPL to be cheaper than every Limited Casco price in the table.
    if mtpl_key in prices_by_key:
        for key in prices_by_key:
            if key.product == "limited_casco":
                constraints.append(
                    Constraint(
                        left=mtpl_key,
                        right=key,
                        description="MTPL must be cheaper than Limited Casco",
                    )
                )

    # Limited Casco vs Casco (same variant + deductible).
    # This enforces the product-level hierarchy while keeping the coverage
    # dimensions (variant, deductible) aligned on both sides.
    for key in prices_by_key:
        if key.product != "limited_casco":
            continue

        casco_key = PriceKey(
            product="casco",
            variant=key.variant,
            deductible=key.deductible,
        )
        if casco_key in prices_by_key:
            constraints.append(
                Constraint(
                    left=key,
                    right=casco_key,
                    description=(
                        "Casco must be more expensive than Limited Casco "
                        "for the same variant and deductible"
                    ),
                )
            )


def _add_variant_level_constraints(
    prices_by_key: Dict[PriceKey, float],
    constraints: List[Constraint],
) -> None:
    """
    Add variant-level constraints of the form (per product & deductible):

        Compact/Basic < Comfort < Premium

    The business rule intentionally does *not* fix the relationship between
    Compact and Basic. We therefore only enforce:

        - Comfort > Compact (when both exist)
        - Comfort > Basic (when both exist)
        - Premium > Comfort (when both exist)

    As with product-level rules, we only generate constraints for combinations
    that actually exist in `prices_by_key`.
    """
    for product in PRODUCTS_WITH_VARIANTS:
        for deductible in DEDUCTIBLES:
            # Build all four potential keys for this (product, deductible) slice.
            pk_compact = PriceKey(product, "compact", deductible)
            pk_basic = PriceKey(product, "basic", deductible)
            pk_comfort = PriceKey(product, "comfort", deductible)
            pk_premium = PriceKey(product, "premium", deductible)

            # Comfort vs Compact
            if pk_compact in prices_by_key and pk_comfort in prices_by_key:
                constraints.append(
                    Constraint(
                        left=pk_compact,
                        right=pk_comfort,
                        description=(
                            "Comfort must be more expensive than Compact "
                            f"for {product} with deductible {deductible}"
                        ),
                    )
                )

            # Comfort vs Basic
            if pk_basic in prices_by_key and pk_comfort in prices_by_key:
                constraints.append(
                    Constraint(
                        left=pk_basic,
                        right=pk_comfort,
                        description=(
                            "Comfort must be more expensive than Basic "
                            f"for {product} with deductible {deductible}"
                        ),
                    )
                )

            # Premium vs Comfort
            if pk_comfort in prices_by_key and pk_premium in prices_by_key:
                constraints.append(
                    Constraint(
                        left=pk_comfort,
                        right=pk_premium,
                        description=(
                            "Premium must be more expensive than Comfort "
                            f"for {product} with deductible {deductible}"
                        ),
                    )
                )


def build_constraints(prices_by_key: Dict[PriceKey, float]) -> List[Constraint]:
    """
    Build the full list of pricing constraints implied by the business rules.

    Args:
        prices_by_key:
            Mapping from PriceKey to price (float). Constraints are only created
            for keys that actually exist in this dictionary, so the function is
            robust to partially filled pricing tables.

    Returns:
        List of Constraint objects of the form:

            prices[left] < prices[right]

        This list is the sole input to the fixing/optimisation logic in
        validate_and_fix_prices, which means new business rules can be added
        by extending this function without touching the solver.
    """
    constraints: List[Constraint] = []

    _add_product_level_constraints(prices_by_key, constraints)
    _add_variant_level_constraints(prices_by_key, constraints)

    return constraints
