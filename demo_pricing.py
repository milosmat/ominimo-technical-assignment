"""Small command-line demo for the pricing validator and geo-pricing helpers.

The script showcases the full pricing pipeline:

  1) Validates and fixes a base price table for ES (reference country).
  2) Projects those prices to Serbia (RS) using country-level wage relativities.
  3) Further adjusts prices for two Serbian cities (Belgrade and Novi Sad)
     using accident frequency and city-level deductible relativities.

This is purely a convenience tool for manual inspection; the automated tests
are the main source of truth for correctness.
"""

from __future__ import annotations

from typing import Mapping

from pricing_validator import validate_and_fix_prices
from geo_pricing import (
    AVERAGE_NET_WAGE_EUR,
    CITY_POP_RS,
    CITY_ACCIDENTS_RS_2020,
    SERBIA_POP_2022,
    SERBIA_ACCIDENTS_2020,
    compute_country_factors,
    adjust_prices_for_country,
    compute_city_factors,
    adjust_prices_for_city,
)

# ---------------------------------------------------------------------------
# Base input - deliberately slightly inconsistent price table
# (used to demonstrate how the validator fixes it)
# ---------------------------------------------------------------------------

RAW_BASE_PRICES_ES: dict[str, float] = {
    "mtpl": 400.0,
    "limited_casco_basic_100": 800.0,
    "limited_casco_basic_200": 820.0,
    "limited_casco_basic_500": 850.0,
    "casco_basic_100": 780.0,
}


def print_price_table(title: str, prices_eur: Mapping[str, float]) -> None:
    """Pretty-print a simple {key -> price} table in EUR."""
    print(title)
    for key in sorted(prices_eur):
        print(f"  {key:30s}: {prices_eur[key]:.2f} EUR")


def run_demo_for_serbia(base_prices_es: Mapping[str, float]) -> None:
    """Run the full demonstration pipeline for the Serbian market (RS)."""
    # 1) Validate and fix base prices (reference country: ES)
    fixed_prices_es, issues = validate_and_fix_prices(dict(base_prices_es))

    print_price_table("Base fixed prices (reference country ES):", fixed_prices_es)

    print("\nIssues during validation:")
    if not issues:
        print("  (no issues – price table already consistent)")
    else:
        for message in issues:
            print(f" - {message}")

    # 2) Country-level factors based on average net wages
    country_factors = compute_country_factors(
        AVERAGE_NET_WAGE_EUR,
        reference_country="ES",
        alpha=1.0,
    )

    # Serbia – national average prices
    prices_rs = adjust_prices_for_country(
        fixed_prices_es,
        country_code="RS",
        country_factors=country_factors,
    )
    print()
    print_price_table("Prices for country RS (national average):", prices_rs)

    # 3) City-level factors within Serbia (Belgrade / Novi Sad)
    city_factors_rs = compute_city_factors(
        city_populations=CITY_POP_RS,
        city_accidents=CITY_ACCIDENTS_RS_2020,
        min_factor=0.9,
        max_factor=1.2,
        gamma=0.2,
        national_total_population=SERBIA_POP_2022,
        national_total_accidents=SERBIA_ACCIDENTS_2020,
    )

    print("\nCity factors within RS (population + accidents 2020):")
    for city_name, factor in city_factors_rs.items():
        print(f"  {city_name:10s}: {factor:.3f}")

    # 4) City-level prices for each of the RS cities
    for city_name in CITY_POP_RS.keys():
        city_prices = adjust_prices_for_city(
            country_prices=prices_rs,
            city_name=city_name,
            city_factors=city_factors_rs,
        )
        print()
        print_price_table(f"Prices for RS / {city_name}:", city_prices)


def main() -> None:
    """Entry-point when running this module as a script."""
    run_demo_for_serbia(RAW_BASE_PRICES_ES)


if __name__ == "__main__":
    main()
