"""Loads config/matching.yaml and config/vat_rates.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


@dataclass(frozen=True)
class MatchConfig:
    price_tolerance_pct: Decimal
    qty_tolerance_countable: Decimal
    qty_tolerance_weight_pct: Decimal
    description_match_min_score: float
    min_field_confidence: float
    vat_rates: frozenset[Decimal]
    weight_units: frozenset[str] = frozenset({"kg"})


@cache
def load_config(config_dir: Path = CONFIG_DIR) -> MatchConfig:
    m = yaml.safe_load((config_dir / "matching.yaml").read_text(encoding="utf-8"))
    v = yaml.safe_load((config_dir / "vat_rates.yaml").read_text(encoding="utf-8"))
    return MatchConfig(
        price_tolerance_pct=Decimal(str(m["price_tolerance_pct"])),
        qty_tolerance_countable=Decimal(str(m["qty_tolerance"]["countable"])),
        qty_tolerance_weight_pct=Decimal(str(m["qty_tolerance"]["weight_pct"])),
        description_match_min_score=float(m["description_match_min_score"]),
        min_field_confidence=float(m["min_field_confidence"]),
        vat_rates=frozenset(Decimal(str(r)) for r in v["rates"]),
    )
