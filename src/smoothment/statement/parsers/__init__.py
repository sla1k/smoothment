from collections.abc import Callable
from pathlib import Path

from smoothment.config import AccountKind
from smoothment.statement.model import ParsedStatement
from smoothment.statement.parsers import bbva, revolut, santander, sovcombank, tbank, wise

type Parser = Callable[[Path, str, str | None], ParsedStatement]

PARSERS: dict[tuple[str, AccountKind], Parser] = {
    ("revolut", "current"): revolut.parse_current,
    ("revolut", "savings"): revolut.parse_savings,
    ("wise", "current"): wise.parse_current,
    ("tbank", "current"): tbank.parse_current,
    ("bbva", "current"): bbva.parse_current,
    ("santander", "current"): santander.parse_current,
    ("sovcombank", "current"): sovcombank.parse_current,
}
