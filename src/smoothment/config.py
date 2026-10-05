import tomllib
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

type AccountKind = Literal["current", "savings", "pocket"]
type Bank = Literal["revolut", "wise", "tbank", "bbva", "santander", "sovcombank"]

CONFIG_FILE_NAME = "smoothment.toml"
DEFAULT_DB_PATH = Path(
    "~/Library/Containers/com.moneywiz.personalfinance-setapp/Data/Library/Application Support/"
    "MoneyWiz_iCloud.sqlite"
).expanduser()
PROBE_FILE_NAME = "smoothment.probe.toml"


class ConfigError(Exception):
    """Configuration file is missing, unparsable, or invalid."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _default_db_path() -> Path:
    return DEFAULT_DB_PATH


class MoneyWizSettings(Strict):
    db: Path = Field(default_factory=_default_db_path)
    single_leg_creates_reciprocal: bool | None = None
    two_legs_link_once: bool | None = None
    memo_lands_in_notes: bool | None = None
    existing_leg_links: bool | None = None

    @field_validator("db", mode="after")
    @classmethod
    def _expand(cls, value: Path) -> Path:
        return value.expanduser()


class OwnerSettings(Strict):
    names: list[str]
    phones: list[str] = []

    @field_validator("phones", mode="after")
    @classmethod
    def _normalize_phones(cls, value: list[str]) -> list[str]:
        digits = ["".join(ch for ch in phone if ch.isdigit()) for phone in value]
        for phone in digits:
            if len(phone) < 10:
                raise ValueError(f"phone must have at least 10 digits: {phone!r}")
        return digits


class AccountEntry(Strict):
    bank: Bank
    kind: AccountKind = "current"
    moneywiz: str
    acct_id: str | None = None
    iban: str | None = None
    file: str | None = None

    @model_validator(mode="after")
    def _at_least_one_identity(self) -> AccountEntry:
        if not (self.acct_id or self.iban or self.file):
            raise ValueError("account needs at least one of acct_id, iban, file")
        return self


class PocketSettings(Strict):
    roundup_max: Decimal = Decimal("1.00")
    accounts: dict[str, dict[str, str]] = {}

    @field_validator("roundup_max", mode="after")
    @classmethod
    def _non_negative(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("roundup_max must be non-negative")
        return value


class BankSettings(Strict):
    payee: str


class CashSettings(Strict):
    account: str


class TransferSettings(Strict):
    window_days: int = 3
    tolerance: Decimal = Decimal("0.02")

    @field_validator("window_days", mode="after")
    @classmethod
    def _window_days_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("window_days must be non-negative")
        return value

    @field_validator("tolerance", mode="after")
    @classmethod
    def _tolerance_non_negative(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("tolerance must be non-negative")
        return value


class Config(Strict):
    moneywiz: MoneyWizSettings = Field(default_factory=MoneyWizSettings)
    owner: OwnerSettings
    accounts: list[AccountEntry] = []
    pockets: PocketSettings = PocketSettings()
    banks: dict[Bank, BankSettings] = {}
    categories: dict[str, Any] = {}  # accepted and ignored, for older config files
    cash: CashSettings | None = None
    transfers: TransferSettings = TransferSettings()
    path: Path

    @model_validator(mode="after")
    def _pockets_name_configured_accounts(self) -> Config:
        names = {entry.moneywiz for entry in self.accounts}
        for account, pockets in self.pockets.accounts.items():
            if account not in names:
                raise ValueError(
                    f"pockets.accounts.{account}: not the moneywiz name of a configured account"
                )
            for pocket, target in pockets.items():
                if target == account:
                    raise ValueError(
                        f"pockets.accounts.{account}.{pocket}: maps to its own account {target!r}"
                    )
        return self


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}; pass --config") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc


def _format_validation_error(path: Path, exc: ValidationError) -> str:
    lines = [f"{path}: invalid config"]
    for err in exc.errors():
        location = ".".join(str(part) for part in err["loc"]) or "<root>"
        lines.append(f"  {location}: {err['msg']}")
    return "\n".join(lines)


def default_config_path(folder: Path | None = None) -> Path:
    """smoothment.toml next to the statement folder, or in the working directory without one."""
    return (folder.parent if folder is not None else Path.cwd()) / CONFIG_FILE_NAME


def load_config(path: Path) -> Config:
    data = _read_toml(path)
    probe_path = path.parent / PROBE_FILE_NAME
    if probe_path.exists():
        overlay = _read_toml(probe_path).get("moneywiz", {})
        data.setdefault("moneywiz", {}).update(overlay)
    data["path"] = path
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(path, exc)) from exc
