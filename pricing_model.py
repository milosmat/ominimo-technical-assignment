"""
Core pricing domain model.

This module defines small, typed building blocks around the flat price
dictionary keys so that the rest of the code can reason about products,
variants and deductibles without re-parsing raw strings.

It defines:
- PriceKey: a structured representation of a price dictionary key (product / variant / deductible).
- Constraint: a simple pair of PriceKeys with a textual description of the rule.
- price_key_rank: a helper to sort keys/constraints in a stable, business-friendly order (by product, then variant, then deductible).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple, Optional


@dataclass(frozen=True)
class PriceKey:
    """
    Structured representation of a pricing key.

    The original input dictionary uses flat string keys, e.g.:

        "mtpl"
        "limited_casco_basic_100"
        "casco_premium_500"

    This dataclass gives us a type-safe way to work with those keys:

        - product: "mtpl", "limited_casco", "casco"
        - variant: "compact", "basic", "comfort", "premium" (or None for MTPL)
        - deductible: 100, 200, 500 (or None for MTPL)

    Keeping this structure in one place makes the validation and fixing logic
    easier to read, test and maintain than repeatedly handling raw strings.
    """

    product: str
    variant: Optional[str] = None
    deductible: Optional[int] = None

    @classmethod
    def from_str(cls, raw_key: str) -> "PriceKey":
        """
        Parse a flat string key into a PriceKey instance.

        Supported formats:
            "mtpl"
            "limited_casco_<variant>_<deductible>"
            "casco_<variant>_<deductible>"

        Centralising this parsing logic means callers can work with PriceKey
        objects instead of duplicating string handling in multiple places.

        Raises:
            ValueError: if the format does not match any of the supported patterns.
        """
        if raw_key == "mtpl":
            return cls(product="mtpl")

        if raw_key.startswith("limited_casco_"):
            # Example: "limited_casco_basic_100"
            try:
                _, _, variant, deductible_str = raw_key.split("_", maxsplit=3)
                return cls(
                    product="limited_casco",
                    variant=variant,
                    deductible=int(deductible_str),
                )
            except (ValueError, TypeError):
                raise ValueError(f"Unsupported limited_casco key format: {raw_key!r}")

        if raw_key.startswith("casco_"):
            # Example: "casco_premium_100"
            try:
                _, variant, deductible_str = raw_key.split("_", maxsplit=2)
                return cls(
                    product="casco",
                    variant=variant,
                    deductible=int(deductible_str),
                )
            except (ValueError, TypeError):
                raise ValueError(f"Unsupported casco key format: {raw_key!r}")

        raise ValueError(f"Unsupported key format: {raw_key!r}")

    def to_str(self) -> str:
        """
        Serialize a PriceKey back to the flat string format used in the input dict.

        Returns:
            A string in one of the following forms:
                "mtpl"
                "limited_casco_<variant>_<deductible>"
                "casco_<variant>_<deductible>"

        This is mainly used when mapping corrected PriceKey objects back to the
        original flat dictionary representation.

        Raises:
            ValueError: if variant / deductible are inconsistent with the product.
        """
        if self.product == "mtpl":
            # MTPL has no variant/deductible dimension in this assignment.
            return "mtpl"

        if self.variant is None or self.deductible is None:
            raise ValueError(f"Incomplete key cannot be serialized: {self!r}")

        return f"{self.product}_{self.variant}_{self.deductible}"


class Constraint(NamedTuple):
    """
    Simple representation of a business constraint:

        prices[left] < prices[right]

    description:
        Short explanation of the rule, suitable for logs or error messages,
        e.g. "MTPL must be cheaper than Limited Casco".
    """

    left: PriceKey
    right: PriceKey
    description: str


# Rankings are used only to provide a deterministic, business-friendly
# ordering of constraints (product → variant → deductible).

PRODUCT_RANK = {
    "mtpl": 0,
    "limited_casco": 1,
    "casco": 2,
}

VARIANT_RANK = {
    None: 0,
    "compact": 1,
    "basic": 1,
    "comfort": 2,
    "premium": 3,
}

DEDUCTIBLE_RANK = {
    None: 0,
    500: 1,
    200: 2,
    100: 3,
}


def price_key_rank(key: PriceKey) -> int:
    """
    Compute a sortable rank for a given PriceKey.

    The rank encodes the business ordering we care about:

        1. Product level: MTPL < Limited Casco < Casco
        2. Within product: Compact/Basic < Comfort < Premium
        3. Within product/variant: 500 < 200 < 100 (higher deductible → cheaper)

    This is implemented as a simple weighted sum:

        product_rank * 100 + variant_rank * 10 + deductible_rank

    so that product dominates variant, which dominates deductible.
    """
    return (
        PRODUCT_RANK[key.product] * 100
        + VARIANT_RANK.get(key.variant, 0) * 10
        + DEDUCTIBLE_RANK.get(key.deductible, 0)
    )
