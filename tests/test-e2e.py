import unittest
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


from pricing_validator import validate_and_fix_prices
from geo_pricing import (
    AVERAGE_NET_WAGE_EUR,
    CITY_POP_RS,
    CITY_ACCIDENTS_RS_2020,
    SERBIA_POP_2022,
    SERBIA_ACCIDENTS_2020,
    compute_country_factors,
    compute_city_factors,
    adjust_prices_for_country,
    adjust_prices_for_city,
)


def _print_price_table(title: str, prices: dict[str, float]) -> None:
    """
    Pretty-print a price table (sorted by key) to stdout.

    This helper is only for manual inspection when running the tests locally.
    The assertions below are what actually determine whether the test
    passes or fails.
    """
    print(f"\n{title}")
    print("-" * len(title))
    for key in sorted(prices):
        print(f"  {key:30s} {prices[key]:8.2f} EUR")


class PricingEndToEndTests(unittest.TestCase):
    """
    End-to-end tests that stitch together:

      * the core pricing validator (monotonicity rules), and
      * geo-pricing adjustments (countries and cities).

    The goal is to show that the business rules remain consistent after
    each transformation step, not just on the initial ES price table.
    """

    def test_full_pipeline_from_raw_prices(self) -> None:
        """
        End-to-end scenario intentionally close to the wording of the assignment,
        but with a richer product/variant structure.

        What this test simulates
        ------------------------
        1. Business gives us a raw price table with several problems:

             * wrong deductible ladder for Limited Casco (Basic/Compact/Comfort/Premium):
                   500 > 200 > 100 instead of 500 < 200 < 100,
             * Casco Basic is cheaper than Limited Casco Basic,
             * Casco Premium is more expensive than Limited Casco Premium,
               but with a gap smaller than PRODUCT_MARGIN (10%),
             * Limited Casco Compact is slightly MORE expensive than Basic,
               which is allowed by the requirements and *must not* be changed.

        2. We run the main engine:

               fixed_prices, issues = validate_and_fix_prices(raw_prices)

           which should:
             * normalise deductibles (100 / 200 / 500) per product+variant,
             * enforce MTPL < Limited Casco < Casco for both Basic and Premium,
             * enforce Basic/Compact < Comfort < Premium,
             * keep all changes documented in the `issues` list.

        3. On top of this we plug in geo-pricing:

             * scale prices to ES / HU / RS using average net wages,
             * then split RS into cities (Belgrade / Novi Sad) using
               accident statistics.

        What we expect to see
        ---------------------
        * The validator changes some prices and explains why in `issues`.
        * After the fix, all business rules hold:
             - by product: MTPL < Limited Casco < Casco,
             - by variant: Basic/Compact < Comfort < Premium,
             - by deductible: 500 < 200 < 100 for Limited Casco variants.
        * The relative ordering between Compact and Basic is preserved
          (Compact stays slightly more expensive than Basic).
        * ES is the reference country; RS should end up cheapest.
        * Inside RS, Belgrade (higher accident rate) should be more expensive
          than Novi Sad, and all ladders should still hold on city level.
        """

        # 0) Raw prices – intentionally messy but realistic-looking.
        #    We include all four variants for Limited Casco (compact/basic/comfort/premium)
        #    to demonstrate that compact vs basic relationship is not forced.
        raw_prices: dict[str, float] = {
            "mtpl": 400,

            # LIMITED CASCO / BASIC:
            #   - deductible ladder is wrong (500 and 200 are *more* expensive than 100)
            "limited_casco_basic_100": 800,
            "limited_casco_basic_200": 820,
            "limited_casco_basic_500": 850,

            # LIMITED CASCO / COMPACT:
            #   - compact is slightly more expensive than basic, which is allowed:
            #       basic_100 = 800, compact_100 = 820
            #     (we only require both to be below Comfort & Premium).
            "limited_casco_compact_100": 820,
            "limited_casco_compact_200": 840,
            "limited_casco_compact_500": 870,

            # LIMITED CASCO / COMFORT:
            #   - also with wrong ladder, but variant order vs basic/compact is fine.
            "limited_casco_comfort_100": 900,
            "limited_casco_comfort_200": 920,
            "limited_casco_comfort_500": 950,

            # LIMITED CASCO / PREMIUM:
            #   - again, wrong ladder but correct variant ordering.
            "limited_casco_premium_100": 1_000,
            "limited_casco_premium_200": 1_020,
            "limited_casco_premium_500": 1_050,

            # CASCO / BASIC:
            #   - clearly wrong: Casco Basic cheaper than Limited Casco Basic.
            "casco_basic_100": 780,

            # CASCO / PREMIUM:
            #   - Casco Premium is above Limited Premium, but with a gap
            #     smaller than PRODUCT_MARGIN (10%), so validator should
            #     push it a bit higher.
            "casco_premium_100": 1_070,
        }

        _print_price_table("RAW PRICES (input from business)", raw_prices)

        # 1) Validation and repair on the reference country (ES)
        fixed_prices, issues = validate_and_fix_prices(raw_prices)

        _print_price_table(
            "FIXED PRICES AFTER validate_and_fix_prices()", fixed_prices
        )

        print("\nISSUES / CHANGES APPLIED BY VALIDATOR")
        print("-------------------------------------")
        if not issues:
            print("  (no changes – input was already consistent)")
        else:
            for msg in issues:
                print(" -", msg)

        # Test 1: we expect at least one correction for such an inconsistent input
        self.assertTrue(
            issues,
            "Validator should report at least one correction for this raw price table.",
        )
        self.assertNotEqual(
            raw_prices,
            fixed_prices,
            msg="Fixed price table should not be identical to the raw input.",
        )

        # --- Product-level checks on ES (reference) ------------------------

        # MTPL < Limited Casco < Casco for BASIC 100
        self.assertLess(fixed_prices["mtpl"], fixed_prices["limited_casco_basic_100"])
        self.assertLess(
            fixed_prices["limited_casco_basic_100"],
            fixed_prices["casco_basic_100"],
        )

        # MTPL < Limited Casco < Casco for PREMIUM 100
        self.assertLess(fixed_prices["mtpl"], fixed_prices["limited_casco_premium_100"])
        self.assertLess(
            fixed_prices["limited_casco_premium_100"],
            fixed_prices["casco_premium_100"],
        )

        # --- Variant ladder for Limited Casco (Basic/Compact/Comfort/Premium) ----

        # Basic/Compact < Comfort < Premium – per assignment.
        basic_100 = fixed_prices["limited_casco_basic_100"]
        compact_100 = fixed_prices["limited_casco_compact_100"]
        comfort_100 = fixed_prices["limited_casco_comfort_100"]
        premium_100 = fixed_prices["limited_casco_premium_100"]

        # Comfort and Premium must sit above both Basic and Compact:
        self.assertLess(basic_100, comfort_100)
        self.assertLess(compact_100, comfort_100)
        self.assertLess(comfort_100, premium_100)

        # BUT: Compact vs Basic relationship is *not* fixed by the business rules.
        # We started with Compact slightly more expensive than Basic; we expect the
        # validator to keep that ordering and *not* touch Compact.
        self.assertGreater(
            compact_100,
            basic_100,
            msg="Compact is allowed to be more expensive than Basic and should stay that way.",
        )
        # Optional: verify that Compact price stayed exactly as in the input.
        self.assertEqual(
            compact_100,
            raw_prices["limited_casco_compact_100"],
            msg="Compact 100 price should not be changed by the validator.",
        )

        # And ensure there is NO issue that directly adjusts compact_100.
        for msg in issues:
            self.assertFalse(
                msg.startswith("Aligned limited_casco_compact_100")
                or msg.startswith("Adjusted limited_casco_compact_100"),
                msg=(
                    "Compact 100 should not be directly adjusted; "
                    "it may appear as 'base' in other messages, which is fine."
                ),
            )

        # --- Deductible ladders for Limited Casco (Basic/Compact/Comfort/Premium) ---

        for variant in ("basic", "compact", "comfort", "premium"):
            price_100 = fixed_prices[f"limited_casco_{variant}_100"]
            price_200 = fixed_prices[f"limited_casco_{variant}_200"]
            price_500 = fixed_prices[f"limited_casco_{variant}_500"]

            # 500 < 200 < 100
            self.assertLess(price_500, price_200)
            self.assertLess(price_200, price_100)

        # 2) Countries – use AVERAGE_NET_WAGE_EUR from geo_pricing
        country_factors = compute_country_factors(
            AVERAGE_NET_WAGE_EUR,
            reference_country="ES",
            alpha=1.0,
        )

        print("\nCOUNTRY FACTORS (relative to ES)")
        print("--------------------------------")
        for country_code, factor in country_factors.items():
            print(f"  {country_code}: {factor:.4f}")

        es_prices = adjust_prices_for_country(fixed_prices, "ES", country_factors)
        hu_prices = adjust_prices_for_country(fixed_prices, "HU", country_factors)
        rs_prices = adjust_prices_for_country(fixed_prices, "RS", country_factors)

        _print_price_table("ES PRICES (reference country)", es_prices)
        _print_price_table("HU PRICES (scaled by wage HU/ES)", hu_prices)
        _print_price_table("RS PRICES (scaled by wage RS/ES)", rs_prices)

        # Test 2: ES is the reference, RS should be the cheapest (lowest wage)
        self.assertGreaterEqual(
            es_prices["mtpl"],
            hu_prices["mtpl"],
            msg="ES (reference) should not be cheaper than HU after scaling.",
        )
        self.assertGreaterEqual(
            es_prices["mtpl"],
            rs_prices["mtpl"],
            msg="ES (reference) should not be cheaper than RS after scaling.",
        )
        self.assertLess(
            rs_prices["mtpl"],
            hu_prices["mtpl"],
            msg="RS should be cheaper than HU after scaling.",
        )
        self.assertLess(
            rs_prices["mtpl"],
            es_prices["mtpl"],
            msg="RS should be cheaper than ES after scaling.",
        )

        # Product ladder and deductible ladder must still hold at RS level.
        # BASIC
        self.assertLess(rs_prices["mtpl"], rs_prices["limited_casco_basic_100"])
        self.assertLess(
            rs_prices["limited_casco_basic_100"],
            rs_prices["casco_basic_100"],
        )
        # PREMIUM
        self.assertLess(rs_prices["mtpl"], rs_prices["limited_casco_premium_100"])
        self.assertLess(
            rs_prices["limited_casco_premium_100"],
            rs_prices["casco_premium_100"],
        )

        # Deductibles for all Limited Casco variants in RS
        for variant in ("basic", "compact", "comfort", "premium"):
            price_100 = rs_prices[f"limited_casco_{variant}_100"]
            price_200 = rs_prices[f"limited_casco_{variant}_200"]
            price_500 = rs_prices[f"limited_casco_{variant}_500"]
            self.assertLess(price_500, price_200)
            self.assertLess(price_200, price_100)

        # 3) Cities within Serbia (Belgrade / Novi Sad)
        city_factors_rs = compute_city_factors(
            CITY_POP_RS,
            city_accidents=CITY_ACCIDENTS_RS_2020,
            min_factor=0.9,
            max_factor=1.2,
            gamma=0.2,
            national_total_population=SERBIA_POP_2022,
            national_total_accidents=SERBIA_ACCIDENTS_2020,
        )

        print("\nCITY FACTORS WITHIN RS")
        print("----------------------")
        for city, factor in city_factors_rs.items():
            print(f"  {city:10s}: {factor:.4f}")

        beograd_prices = adjust_prices_for_city(rs_prices, "Beograd", city_factors_rs)
        novi_sad_prices = adjust_prices_for_city(rs_prices, "Novi Sad", city_factors_rs)

        _print_price_table("RS / BEOGRAD (higher accident rate)", beograd_prices)
        _print_price_table("RS / NOVI SAD (lower accident rate)", novi_sad_prices)

        # Test 3: Belgrade has higher accident rate -> MTPL should be more expensive
        self.assertGreater(
            beograd_prices["mtpl"],
            novi_sad_prices["mtpl"],
            msg="Belgrade MTPL should be more expensive than Novi Sad MTPL.",
        )

        # In both cities, all ladders must still hold.
        for city_name, city_prices in [
            ("Beograd", beograd_prices),
            ("Novi Sad", novi_sad_prices),
        ]:
            with self.subTest(city=city_name):
                # Product ladders for BASIC and PREMIUM (100 deductible)
                self.assertLess(
                    city_prices["mtpl"],
                    city_prices["limited_casco_basic_100"],
                )
                self.assertLess(
                    city_prices["limited_casco_basic_100"],
                    city_prices["casco_basic_100"],
                )
                self.assertLess(
                    city_prices["mtpl"],
                    city_prices["limited_casco_premium_100"],
                )
                self.assertLess(
                    city_prices["limited_casco_premium_100"],
                    city_prices["casco_premium_100"],
                )

                # Deductible ladders for ALL Limited Casco variants
                for variant in ("basic", "compact", "comfort", "premium"):
                    price_100 = city_prices[f"limited_casco_{variant}_100"]
                    price_200 = city_prices[f"limited_casco_{variant}_200"]
                    price_500 = city_prices[f"limited_casco_{variant}_500"]
                    self.assertLess(price_500, price_200)
                    self.assertLess(price_200, price_100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
