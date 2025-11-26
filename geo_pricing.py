"""Geographical pricing helpers for the Ominimo motor-insurance assignment.

This module is responsible for:

* Country-level relativities:
    - Derive a simple price factor per country from average net wage as an
      affordability proxy.

* City-level relativities within Serbia:
    - Use accident frequency per capita for Belgrade and Novi Sad to obtain
      relative risk factors vs. the national average.
    - Combine these with small/big claims information (share of material
      damage accidents) to tweak deductible relativities by city.

The functions are intentionally small and deterministic so they are easy to
unit-test and easy to explain in the README, and so that geo-pricing can be
reasoned about separately from the core pricing validator.
"""

from __future__ import annotations

import math
from typing import Dict, Mapping


# ---------------------------------------------------------------------------
# Country-level economic data
# ---------------------------------------------------------------------------

# Average net wages in EUR per month, used as a simple affordability proxy.
AVERAGE_NET_WAGE_EUR: Dict[str, float] = {
    "RS": 930.0,
    "HU": 1_113.0,
    "ES": 2_000.0,
}

# ---------------------------------------------------------------------------
# Serbian city-level exposure and accident data
# ---------------------------------------------------------------------------

# Population by city (Serbia) – Census 2022.
CITY_POP_RS: Dict[str, int] = {
    "Beograd": 1_685_563,  # administrative area of Belgrade
    "Novi Sad": 368_967,   # city of Novi Sad with suburban areas
}

# Number of traffic accidents by city (Serbia) in 2020.
# Almost half of all accidents in Serbia are in Belgrade (9,061),
# and Novi Sad is the only other city with a four-digit count (~1,316).
CITY_ACCIDENTS_RS_2020: Dict[str, int] = {
    "Beograd": 9_061,
    "Novi Sad": 1_316,
}

# National totals – used as reference when computing city risk.
SERBIA_POP_2022: int = 6_664_449
SERBIA_ACCIDENTS_2020: int = 19_481

# ---------------------------------------------------------------------------
# Deductible relativities – base and per-city adjustments
# ---------------------------------------------------------------------------

# Baseline deductible structure on the reference market (country level):
#   100 EUR: 0% discount (factor = 1.00)
#   200 EUR: ~10% discount (factor = 0.90)
#   500 EUR: ~20% discount (factor = 0.80)
BASE_DEDUCTIBLE_FACTORS: Dict[int, float] = {
    100: 1.00,
    200: 0.90,
    500: 0.80,
}

# City-level deductible factors for Serbia (RS):
# From NEZ open data (2025) we extracted the share of accidents with
# "material damage only":
#   - Serbia (national average): ≈ 58.8%
#   - Belgrade: ≈ 75.0%
#   - Novi Sad: ≈ 48.0%
#
# Intuition:
#   * higher share of small material-damage accidents  -> customers are
#     more likely to file many small claims -> high deductibles become
#     more attractive -> we give slightly higher discounts;
#   * lower share of small claims (relatively more severe accidents)
#     -> high deductibles are less attractive -> discounts should be
#     somewhat smaller.
#
# Step 1: turn the city shares into a *relative frequency* vs. the national
# average:
#
#       r_city = share_city / share_serbia
#
# For our numbers:
#       r_Beograd ≈ 0.75 / 0.588 ≈ 1.28
#       r_NoviSad ≈ 0.48 / 0.588 ≈ 0.82
#
# Step 2: scale the base discount for each deductible d using
#
#       discount_{d, city} = discount_d_base * (1 + γ * (r_city - 1)),
#
# where:
#   - discount_d_base is 0.10 for 200 EUR and 0.20 for 500 EUR;
#   - γ (gamma) controls how strongly we react to the difference in claim mix.
#
# We choose γ ≈ 0.73 so that we stay in a realistic ±2–4 p.p. band around
# the base discounts, but still reflect the data:
#
#   Belgrade (r ≈ 1.28, more small claims):
#       discount_200_BG ≈ 0.10 * (1 + 0.73 * (1.28 - 1)) ≈ 0.120 -> 12.0%
#       discount_500_BG ≈ 0.20 * (1 + 0.73 * (1.28 - 1)) ≈ 0.240 -> 24.0%
#
#   Novi Sad (r ≈ 0.82, relatively more severe accidents):
#       discount_200_NS ≈ 0.10 * (1 + 0.73 * (0.82 - 1)) ≈ 0.087 ->  8.7%
#       discount_500_NS ≈ 0.20 * (1 + 0.73 * (0.82 - 1)) ≈ 0.173 -> 17.3%
#
# Step 3: convert the discounts into price *factors*:
#
#       factor_{d, city} = 1 - discount_{d, city}
#
# which gives exactly the factors we hard-code below (rounded):
#   Belgrade: 200 -> 0.88, 500 -> 0.76
#   Novi Sad: 200 -> 0.9133, 500 -> 0.8266
CITY_DEDUCTIBLE_FACTORS_RS: Dict[str, Dict[int, float]] = {
    "Beograd": {
        100: 1.00,
        200: 0.88,    # ~12% discount (more small material-damage claims)
        500: 0.76,    # ~24% discount
    },
    "Novi Sad": {
        100: 1.00,
        200: 0.9133,  # ~8.7% discount (relatively more severe accidents)
        500: 0.8266,  # ~17.3% discount
    },
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def round_to_step(value: float, step: float = 5.0) -> float:
    """Round *value* to the nearest multiple of ``step`` (half-up).

    This helper is used to keep geo-adjusted prices on a simple commercial
    grid and avoid overly granular values.

    Example with step=5::

        186.0  -> 185.0
        187.6  -> 190.0
        192.5  -> 195.0  (half-up)
    """
    quotient = value / step
    lower = math.floor(quotient)
    frac = quotient - lower

    if frac < 0.5:
        return lower * step
    return (lower + 1) * step


# ---------------------------------------------------------------------------
# Country-level relativities
# ---------------------------------------------------------------------------

def compute_country_factors(
    average_net_wage_eur: Mapping[str, float],
    reference_country: str = "ES",
    alpha: float = 1.0,
) -> Dict[str, float]:
    """Compute simple country relativities based on average net wage.

    The idea is that premiums should scale with purchasing power:

        factor[country] ≈ (wage[country] / wage[reference_country]) ** alpha

    where ``alpha`` controls how sensitive prices are to wage differences.
    ``alpha = 1`` means linear scaling; lower values compress the range and
    give a more conservative differentiation between countries.
    """
    reference_wage = average_net_wage_eur[reference_country]
    factors: Dict[str, float] = {}

    for country_code, wage in average_net_wage_eur.items():
        relativity = wage / reference_wage
        factors[country_code] = relativity ** alpha

    return factors


def adjust_prices_for_country(
    base_prices: Mapping[str, float],
    country_code: str,
    country_factors: Mapping[str, float],
) -> Dict[str, float]:
    """Apply a country-level factor to a base price table.

    The function multiplies each price by the country factor and rounds the
    result to the nearest 5 EUR to avoid overly granular prices. The same
    base table can be reused for multiple countries by changing only the
    ``country_code`` argument.
    """
    factor = country_factors.get(country_code, 1.0)

    return {
        key: round_to_step(price * factor, step=5.0)
        for key, price in base_prices.items()
    }


# ---------------------------------------------------------------------------
# City-level relativities within Serbia
# ---------------------------------------------------------------------------

def get_city_deductible_multiplier(city_name: str, deductible: int) -> float:
    """Return a city-specific multiplier relative to the base deductible factors.

    Example:
        If the base factor for 500 EUR is 0.80, and Belgrade uses 0.76,
        the multiplier is 0.76 / 0.80 = 0.95 (an extra ~5% discount on top
        of the national 500 EUR discount).

    If the city or deductible is unknown, the function falls back to 1.0
    (no additional adjustment). This makes it safe to call for any key.
    """
    city_factors = CITY_DEDUCTIBLE_FACTORS_RS.get(city_name)
    if not city_factors:
        return 1.0

    base_factor = BASE_DEDUCTIBLE_FACTORS.get(deductible, 1.0)
    city_factor = city_factors.get(deductible, base_factor)

    if base_factor == 0.0:
        return 1.0

    return city_factor / base_factor


def compute_city_factors(
    city_populations: Mapping[str, int],
    city_accidents: Mapping[str, int] | None = None,
    *,
    min_factor: float = 0.9,
    max_factor: float = 1.2,
    gamma: float = 0.2,
    national_total_population: int | None = None,
    national_total_accidents: int | None = None,
) -> Dict[str, float]:
    """Compute relative risk factors per city.

    If both city populations and city accident counts are available, and
    national totals are provided, we use the following model::

        rate_city    = accidents_city / population_city
        avg_rate     = national_total_accidents / national_total_population
        raw_risk     = rate_city / avg_rate
        price_factor = 1 + gamma * (raw_risk - 1)

    The parameter ``gamma`` controls how aggressively risk differences are
    translated into price differences. Finally, the factor is clamped into
    ``[min_factor, max_factor]`` to avoid extreme prices.

    If accident information is missing, we fall back to a simple scaling
    based only on population (larger cities get slightly higher factors).
    """
    # ------------------------------------------------------------------
    # Fallback: no accident data – differentiate only by population size
    # ------------------------------------------------------------------
    if not city_accidents:
        populations = list(city_populations.values())
        pop_min, pop_max = min(populations), max(populations)
        pop_range = pop_max - pop_min

        if pop_range == 0:
            return {city: 1.0 for city in city_populations}

        factors: Dict[str, float] = {}
        for city, pop in city_populations.items():
            fraction = (pop - pop_min) / pop_range  # in [0, 1]
            factor = min_factor + fraction * (max_factor - min_factor)
            factors[city] = factor
        return factors

    # ------------------------------------------------------------------
    # With accident data: compute per-capita accident rates by city
    # ------------------------------------------------------------------
    rates: Dict[str, float] = {}
    total_pop_local = 0
    total_acc_local = 0

    for city, pop in city_populations.items():
        accidents = city_accidents.get(city, 0)
        if pop > 0 and accidents > 0:
            rate = accidents / pop
            rates[city] = rate
            total_pop_local += pop
            total_acc_local += accidents
        else:
            rates[city] = 0.0

    # Average accident rate – prefer national totals if they are available.
    if national_total_population is not None and national_total_accidents is not None:
        avg_rate = national_total_accidents / national_total_population
    else:
        if total_pop_local == 0 or total_acc_local == 0:
            return {city: 1.0 for city in city_populations}
        avg_rate = total_acc_local / total_pop_local

    # Transform risk differences into price factors.
    factors: Dict[str, float] = {}
    for city, rate in rates.items():
        if rate == 0.0:
            raw_risk = 1.0
        else:
            raw_risk = rate / avg_rate

        price_factor = 1.0 + gamma * (raw_risk - 1.0)
        clamped = max(min_factor, min(max_factor, price_factor))
        factors[city] = clamped

    return factors


def adjust_prices_for_city(
    country_prices: Mapping[str, float],
    city_name: str,
    city_factors: Mapping[str, float],
) -> Dict[str, float]:
    """Apply city-level and deductible-level adjustments on top of country prices.

    Steps:
        1. Multiply by the city risk factor (accident frequency / severity).
        2. If the price key encodes a deductible suffix (``..._100``, ``..._200``,
           ``..._500``), apply an additional deductible multiplier specific to
           the city (Belgrade / Novi Sad).
        3. Round the final price to the nearest 5 EUR.

    Keys for products without deductibles (e.g. ``"mtpl"``) only receive the
    city factor and the final rounding.
    """
    base_city_factor = city_factors.get(city_name, 1.0)
    adjusted: Dict[str, float] = {}

    for key, base_price in country_prices.items():
        # Step 1: city-level factor (frequency/severity of accidents)
        price = base_price * base_city_factor

        # Step 2: try to extract deductible from the key, e.g. "..._100"
        deductible: int | None = None
        parts = key.split("_")
        try:
            maybe_deductible = int(parts[-1])
            if maybe_deductible in (100, 200, 500):
                deductible = maybe_deductible
        except ValueError:
            deductible = None

        if deductible is not None:
            ded_mult = get_city_deductible_multiplier(city_name, deductible)
            price *= ded_mult

        # Step 3: final rounding
        adjusted[key] = round_to_step(price, step=5.0)

    return adjusted


# ---------------------------------------------------------------------------
# Small demo when executed directly (optional helper)
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover - manual smoke-test only
    demo_base_prices = {
        "mtpl": 400.0,
        "limited_casco_basic_100": 800.0,
    }

    country_factors_demo = compute_country_factors(
        AVERAGE_NET_WAGE_EUR,
        reference_country="ES",
        alpha=1.0,
    )

    print("Average net wages (EUR):")
    for country_code, wage in AVERAGE_NET_WAGE_EUR.items():
        print(f"  {country_code}: {wage:.2f}")

    print("\nCountry factors (relative to ES):")
    for country_code, factor in country_factors_demo.items():
        print(f"  {country_code}: {factor:.4f}")

    print("\nBase prices (reference country ES):")
    for key, value in demo_base_prices.items():
        print(f"  {key}: {value:.2f} EUR")

    print("\nAdjusted prices by country:")
    for country_code in AVERAGE_NET_WAGE_EUR.keys():
        adjusted_prices = adjust_prices_for_country(
            demo_base_prices,
            country_code=country_code,
            country_factors=country_factors_demo,
        )
        print(f"\n  Country = {country_code}")
        for key, value in adjusted_prices.items():
            print(f"    {key}: {value:.2f} EUR")
