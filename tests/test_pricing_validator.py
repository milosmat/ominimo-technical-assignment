import unittest
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from pricing_validator import validate_and_fix_prices


class PricingValidatorUnitTests(unittest.TestCase):
    """
    Unit tests for the core business rules described in the assignment.

    Each test focuses on one of the three monotonicity dimensions:
      1) By product level: MTPL < Limited Casco < Casco
      2) By variant level: Compact/Basic < Comfort < Premium
      3) By deductible level: 100 > 200 > 500  (higher deductible → lower price)

    Besides checking the final price ordering, the tests also verify that
    the validator reports changes in the `issues` list whenever it needs
    to adjust any input prices.
    """

    def test_deductible_ladder_is_enforced_and_reported(self) -> None:
        """
        Rule (3) - By deductible:
            100 > 200 > 500  (higher deductible → cheaper price)

        Scenario:
        ---------
        Limited Casco Basic is given with an inverted ladder (500 > 200),
        which is not realistic. We expect the validator to:
          * rebuild the ladder so that 500 < 200 < 100, and
          * mention both 200 and 500 keys in the issues list.
        """
        raw_prices: dict[str, float] = {
            "mtpl": 400,
            "limited_casco_basic_100": 800,
            "limited_casco_basic_200": 820,  # 200 and 500 are too expensive
            "limited_casco_basic_500": 850,
        }

        fixed_prices, issues = validate_and_fix_prices(raw_prices)

        price_100 = fixed_prices["limited_casco_basic_100"]
        price_200 = fixed_prices["limited_casco_basic_200"]
        price_500 = fixed_prices["limited_casco_basic_500"]

        # Deductible ladder must hold: 500 < 200 < 100
        self.assertLess(price_500, price_200)
        self.assertLess(price_200, price_100)

        # Both 200 and 500 entries should appear in the issues log
        joined_issues = "\n".join(issues)
        self.assertIn("limited_casco_basic_200", joined_issues)
        self.assertIn("limited_casco_basic_500", joined_issues)

    def test_product_level_mtpl_limited_casco_casco(self) -> None:
        """
        Rule (1) - By product level:
            MTPL < Limited Casco < Casco

        Scenario:
        ---------
        We start from a clearly wrong table:
          * Limited Casco is cheaper than MTPL,
          * Casco is cheaper than Limited Casco.

        We expect the validator to move Limited and Casco up so that:
          MTPL < Limited Casco < Casco
        """
        raw_prices: dict[str, float] = {
            "mtpl": 500,
            "limited_casco_basic_100": 450, # wrong: cheaper than MTPL
            "casco_basic_100": 480, # wrong: cheaper than Limited
        }

        fixed_prices, issues = validate_and_fix_prices(raw_prices)

        mtpl_price = fixed_prices["mtpl"]
        limited_price = fixed_prices["limited_casco_basic_100"]
        casco_price = fixed_prices["casco_basic_100"]

        # Product ladder after repair: MTPL < Limited Casco < Casco
        self.assertLess(mtpl_price, limited_price)
        self.assertLess(limited_price, casco_price)

        # We expect at least two corrections (Limited and Casco moved up)
        self.assertGreaterEqual(
            len(issues),
            2,
            msg="Both Limited Casco and Casco should have been adjusted in this scenario.",
        )

    def test_variant_ladder_is_enforced_and_reported(self) -> None:
        """
        Rule (2) - By variant (for Limited/Casco):
            Compact/Basic < Comfort < Premium

        Scenario:
        ---------
        Limited Casco is given with:
          * Comfort cheaper than Basic,
          * Premium only slightly above Comfort.

        We expect the validator to:
          * push Comfort above Basic by at least VARIANT_MARGIN, and
          * keep Premium above Comfort,
          * mention both Comfort and Premium in the issues list.
        """
        raw_prices: dict[str, float] = {
            "mtpl": 400,
            "limited_casco_basic_100": 800,
            "limited_casco_comfort_100": 790,   # wrong: Comfort < Basic
            "limited_casco_premium_100": 810,
        }

        fixed_prices, issues = validate_and_fix_prices(raw_prices)

        basic_price = fixed_prices["limited_casco_basic_100"]
        comfort_price = fixed_prices["limited_casco_comfort_100"]
        premium_price = fixed_prices["limited_casco_premium_100"]

        # Variant ladder: Basic/Compact < Comfort < Premium
        self.assertLess(basic_price, comfort_price)
        self.assertLess(comfort_price, premium_price)

        # Comfort and Premium should be explicitly mentioned in the issues log
        joined_issues = "\n".join(issues)
        self.assertIn("limited_casco_comfort_100", joined_issues)
        self.assertIn("limited_casco_premium_100", joined_issues)


if __name__ == "__main__":
    unittest.main(verbosity=2)
