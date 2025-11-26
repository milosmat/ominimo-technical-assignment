# Ominimo Motor Pricing – Python Assignment

This repository contains my solution to the Ominimo motor-insurance pricing assignment.

The goal is to:

- validate and fix a motor pricing table based on simple business rules, and  
- demonstrate how the same base prices can be projected to countries and cities using economic and risk factors.

---

## Project structure

- `pricing_model.py`  
  Core domain model:
  - `PriceKey`: structured representation of price keys (product / variant / deductible),
  - `Constraint`: pairwise business rule between two prices,
  - `price_key_rank`: helper to sort constraints in a business-friendly order.

- `pricing_rules.py`  
  Builds the list of `Constraint` objects implied by the business rules:
  - product level: `MTPL < Limited Casco < Casco`,
  - variant level: `Basic/Compact < Comfort < Premium`,
  - only for combinations that actually exist in the input table.

- `pricing_validator.py`  
  Main entry point:
  - `validate_and_fix_prices(raw_prices: Dict[str, float]) -> Tuple[Dict[str, float], List[str]]`
  - enforces:
    - product ladder,
    - variant ladder,
    - deductible ladder (100 / 200 / 500),
  - returns the fixed price table and a list of log messages describing all corrections.

- `geo_pricing.py`  
  Geo-pricing helpers:
  - country-level relativities based on average net wage (ES / HU / RS),
  - city-level relativities within Serbia (Belgrade / Novi Sad) based on
    accident frequency and claim mix,
  - utilities to adjust prices by country and by city.

- `pricing_demo.py`  
  Small command-line demo that runs the full pipeline:
  1. validate and fix base ES prices,
  2. project them to RS,
  3. split RS into Belgrade / Novi Sad prices.

- `tests/`  
  - `test_pricing_validator_unit.py` – unit tests for the core business rules.  
  - `test_pricing_end_to_end.py` – end-to-end scenario combining validator and geo-pricing.  

---

## Python version & dependencies

The project uses only the Python standard library (no external packages).

- Target / tested version: **Python 3.10+**  
  (for modern type hints such as `X | None` and `from __future__ import annotations`).

---
