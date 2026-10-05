"""Shared factories for classify-rule tests (not a test module itself)."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from smoothment.classify.model import ClassifyContext
from smoothment.classify.owner import OwnerMatcher
from smoothment.config import Config, OwnerSettings
from smoothment.statement.model import StatementRow

OWNER = "Sample Owner"
PARTNER = "Partner Person"
JOINT_COUNTERPARTY = "PARTNER PERSON & SAMPLE OWNER"


def make_row(**overrides: Any) -> StatementRow:
    defaults: dict[str, Any] = dict(
        bank="revolut",
        account="Shared",
        line=1,
        date=datetime(2026, 9, 1, 10, 0, 0),
        has_time=True,
        amount=Decimal("-10.00"),
        currency="EUR",
        description="Test row",
        kind="current",
    )
    defaults.update(overrides)
    return StatementRow(**defaults)


def make_config(**overrides: Any) -> Config:
    defaults: dict[str, Any] = dict(
        owner=OwnerSettings(names=[OWNER]),
        path=Path("/tmp/smoothment.toml"),
    )
    defaults.update(overrides)
    return Config(**defaults)


def make_context(config: Config | None = None) -> ClassifyContext:
    cfg = config if config is not None else make_config()
    return ClassifyContext(config=cfg, owner=OwnerMatcher(cfg.owner))
