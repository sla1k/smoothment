from collections.abc import Callable

from smoothment.classify.model import ClassifiedRow, ClassifyContext
from smoothment.config import AccountEntry, Config
from smoothment.statement.model import StatementRow


def bank_payee(row: StatementRow, context: ClassifyContext) -> str | None:
    """The bank's configured payee, for fee/interest/cashback/pocket_income rows."""
    settings = context.config.banks.get(row.bank)
    return settings.payee if settings else None


def accounts_of(
    config: Config, *, bank: str | None = None, not_bank: str | None = None, excluding: str
) -> frozenset[str]:
    """MoneyWiz names of `kind == "current"` accounts, filtered by bank, minus `excluding`."""
    return frozenset(
        entry.moneywiz
        for entry in config.accounts
        if entry.kind == "current"
        and entry.moneywiz != excluding
        and (bank is None or entry.bank == bank)
        and (not_bank is None or entry.bank != not_bank)
    )


def _normalize_id(value: str) -> str:
    return value.replace(" ", "").casefold()


def _match_account(context: ClassifyContext, row: StatementRow) -> AccountEntry | None:
    """Another configured account whose iban or acct_id matches, spaces removed and case-folded."""
    if not row.counterparty_account:
        return None
    target = _normalize_id(row.counterparty_account)
    for entry in context.config.accounts:
        if entry.moneywiz == row.account:
            continue
        for candidate in (entry.iban, entry.acct_id):
            if candidate is not None and _normalize_id(candidate) == target:
                return entry
    return None


def revolut_type(row: StatementRow) -> str:
    return (row.bank_type or "").casefold().replace("_", " ")


def is_revolut_cash(row: StatementRow) -> bool:
    """Every ATM row is cash evidence for the common cash rule, whatever it says."""
    return revolut_type(row) == "atm"


def classify_revolut(row: StatementRow, context: ClassifyContext) -> ClassifiedRow:
    kind = revolut_type(row)

    if kind == "atm":
        return ClassifiedRow(
            row=row,
            kind="purchase",
            evidence="revolut: ATM row, cash account not configured",
        )
    if kind == "charge":
        return ClassifiedRow(
            row=row,
            kind="fee",
            payee=bank_payee(row, context),
            evidence=f'revolut: charge ("{row.description}")',
        )
    if kind == "interest":
        return ClassifiedRow(
            row=row,
            kind="interest",
            payee=bank_payee(row, context),
            evidence=f'revolut: interest on the current account ("{row.description}")',
        )
    if kind in ("card refund", "card credit"):
        return ClassifiedRow(
            row=row,
            kind="refund",
            evidence=f'revolut: card refund ("{row.description}")',
        )
    if kind in ("transfer", "deposit"):
        counterparty = row.counterparty
        if context.owner.is_owner(counterparty):
            return ClassifiedRow(
                row=row,
                kind="own_transfer",
                allowed=None,
                evidence=f'revolut: Transfer to the owner ("{row.description}")',
            )
        if counterparty:
            return ClassifiedRow(
                row=row,
                kind="third_party",
                payee=counterparty,
                evidence=f'revolut: transfer to a third party ("{row.description}")',
            )
        return ClassifiedRow(
            row=row,
            kind="third_party",
            payee=row.description,
            evidence=(
                f'revolut: transfer with no counterparty, a direct debit ("{row.description}")'
            ),
        )

    if row.amount < 0:
        return ClassifiedRow(
            row=row,
            kind="purchase",
            evidence=f'revolut: card payment or unrecognised negative type ("{row.bank_type}")',
        )
    return ClassifiedRow(
        row=row,
        kind="income",
        evidence=f'revolut: unrecognised positive type ("{row.bank_type}")',
    )


def classify_wise(row: StatementRow, context: ClassifyContext) -> ClassifiedRow:
    external_id = row.external_id or ""
    if external_id.startswith("BALANCE_CASHBACK") or row.description == "Cashback":
        return ClassifiedRow(
            row=row,
            kind="cashback",
            payee=bank_payee(row, context),
            evidence=f'wise: cashback ("{row.description}")',
        )

    bank_type = row.bank_type or ""

    if bank_type == "MONEY_ADDED":
        return ClassifiedRow(
            row=row,
            kind="own_transfer",
            allowed=None,
            pair_only=True,
            evidence=f'wise: money added to the balance ("{row.description}")',
        )

    if bank_type in ("TRANSFER", "DEPOSIT"):
        if context.owner.is_owner(row.counterparty):
            entry = _match_account(context, row)
            if entry is not None:
                return ClassifiedRow(
                    row=row,
                    kind="own_transfer",
                    allowed=frozenset({entry.moneywiz}),
                    counterpart=entry.moneywiz,
                    evidence=(
                        "wise: transfer to the owner's known account "
                        f'("{row.counterparty_account}")'
                    ),
                )
            return ClassifiedRow(
                row=row,
                kind="own_transfer",
                allowed=None,
                evidence=f'wise: transfer to the owner ("{row.description}")',
            )
        return ClassifiedRow(
            row=row,
            kind="third_party",
            evidence=f'wise: transfer to a third party ("{row.description}")',
        )

    if bank_type == "CARD":
        if row.amount < 0:
            return ClassifiedRow(
                row=row, kind="purchase", evidence=f'wise: card payment ("{row.description}")'
            )
        return ClassifiedRow(
            row=row, kind="refund", evidence=f'wise: card refund ("{row.description}")'
        )

    if row.amount < 0:
        return ClassifiedRow(
            row=row,
            kind="purchase",
            evidence=f'wise: unrecognised negative type ("{row.bank_type}")',
        )
    return ClassifiedRow(
        row=row, kind="income", evidence=f'wise: unrecognised positive type ("{row.bank_type}")'
    )


_TBANK_SAME_BANK_TRANSFER = "Между своими счетами"
_TBANK_OTHER_BANK_TRANSFER = "Себе в другой банк"
_TBANK_INTEREST_NAME_PREFIX = "Проценты на остаток"
_TBANK_MEMO_FEE = "Услуги банка"
_TBANK_MEMO_INTEREST = "Проценты"
_TBANK_MEMO_CASHBACK = "Бонусы"
_TBANK_MEMO_TRANSFERS = "Переводы"
_TBANK_MEMO_TOP_UP = "Пополнения"


def classify_tbank(row: StatementRow, context: ClassifyContext) -> ClassifiedRow:
    name = row.description
    memo = row.bank_category

    if name == _TBANK_SAME_BANK_TRANSFER:
        return ClassifiedRow(
            row=row,
            kind="own_transfer",
            allowed=accounts_of(context.config, bank="tbank", excluding=row.account),
            evidence=f'tbank: transfer between own tbank accounts ("{name}")',
        )
    if name == _TBANK_OTHER_BANK_TRANSFER:
        return ClassifiedRow(
            row=row,
            kind="own_transfer",
            allowed=accounts_of(context.config, not_bank="tbank", excluding=row.account),
            evidence=f'tbank: transfer to the owner at another bank ("{name}")',
        )
    if context.owner.is_owner(row.counterparty):
        return ClassifiedRow(
            row=row,
            kind="own_transfer",
            allowed=None,
            evidence=f'tbank: NAME is the owner ("{name}")',
        )
    if memo == _TBANK_MEMO_FEE:
        return ClassifiedRow(
            row=row,
            kind="fee",
            payee=bank_payee(row, context),
            evidence=f'tbank: bank fee (MEMO "{memo}")',
        )
    if memo == _TBANK_MEMO_INTEREST or name.startswith(_TBANK_INTEREST_NAME_PREFIX):
        return ClassifiedRow(
            row=row,
            kind="interest",
            payee=bank_payee(row, context),
            evidence=f'tbank: interest ("{memo or name}")',
        )
    if memo == _TBANK_MEMO_CASHBACK:
        return ClassifiedRow(
            row=row,
            kind="cashback",
            payee=bank_payee(row, context),
            evidence=f'tbank: cashback (MEMO "{memo}")',
        )
    if memo == _TBANK_MEMO_TRANSFERS:
        return ClassifiedRow(
            row=row,
            kind="third_party",
            evidence=f'tbank: transfer to a third party (MEMO "{memo}")',
        )
    if memo == _TBANK_MEMO_TOP_UP and row.amount > 0:
        return ClassifiedRow(
            row=row,
            kind="income",
            evidence=f'tbank: account top-up (MEMO "{memo}")',
        )

    if row.amount < 0:
        return ClassifiedRow(
            row=row,
            kind="purchase",
            evidence=f'tbank: unrecognised negative row, sign-based fallback ("{name}")',
        )
    return ClassifiedRow(
        row=row,
        kind="refund",
        evidence=f'tbank: unrecognised positive row, sign-based fallback ("{name}")',
    )


def _cf(text: str | None) -> str:
    return (text or "").strip().casefold()


_BBVA_CASH_PREFIXES = (
    "ret. efectivo",
    "cash withdrawal",
    "ingreso en efectivo",
    "cash deposit",
)
_BBVA_TRANSFER_CONCEPTS = {
    "transferencia recibida",
    "transfer received",
    "transferencia realizada",
    "transfer completed",
}
_BBVA_CARD_PAYMENT = {"card payment", "pago con tarjeta"}
_BBVA_REVOLUT_MOVEMENT = "sent from revolut"
_BBVA_DIRECTION_PREFIXES = ("to ", "from ")


def is_bbva_cash(row: StatementRow) -> bool:
    """A cash withdrawal or deposit, English or Spanish wording."""
    return _cf(row.description).startswith(_BBVA_CASH_PREFIXES)


def _strip_bbva_direction_prefix(text: str) -> str:
    folded = text.casefold()
    for prefix in _BBVA_DIRECTION_PREFIXES:
        if folded.startswith(prefix):
            return text[len(prefix) :].strip()
    return text.strip()


def classify_bbva(row: StatementRow, context: ClassifyContext) -> ClassifiedRow:
    concept = _cf(row.description)
    movement = (row.bank_type or "").strip()

    if concept in _BBVA_TRANSFER_CONCEPTS:
        if movement.casefold() == _BBVA_REVOLUT_MOVEMENT:
            return ClassifiedRow(
                row=row,
                kind="own_transfer",
                allowed=accounts_of(context.config, bank="revolut", excluding=row.account),
                pair_only=True,
                evidence=f'bbva: transfer from Revolut ("{row.description}")',
            )
        if context.owner.is_owner(movement):
            return ClassifiedRow(
                row=row,
                kind="own_transfer",
                allowed=None,
                evidence=f'bbva: transfer to/from the owner ("{movement}")',
            )
        return ClassifiedRow(
            row=row,
            kind="third_party",
            payee=_strip_bbva_direction_prefix(movement) if movement else None,
            evidence=f'bbva: transfer with a third party ("{movement}")',
        )

    if movement.casefold() in _BBVA_CARD_PAYMENT:
        return ClassifiedRow(
            row=row,
            kind="purchase",
            evidence=f'bbva: card payment ("{row.description}")',
        )

    if row.amount < 0:
        return ClassifiedRow(
            row=row,
            kind="purchase",
            evidence=f'bbva: unrecognised negative row, sign-based fallback ("{row.description}")',
        )
    return ClassifiedRow(
        row=row,
        kind="income",
        evidence=f'bbva: unrecognised positive row, sign-based fallback ("{row.description}")',
    )


_SANTANDER_REVOLUT_REFERENCE = "Sent From Revolut"


def classify_santander(row: StatementRow, context: ClassifyContext) -> ClassifiedRow:
    bank_type = row.bank_type

    if bank_type == "Transferencia":
        if context.owner.is_owner(row.counterparty):
            allowed = (
                accounts_of(context.config, bank="revolut", excluding=row.account)
                if row.reference == _SANTANDER_REVOLUT_REFERENCE
                else None
            )
            return ClassifiedRow(
                row=row,
                kind="own_transfer",
                allowed=allowed,
                evidence=f'santander: transfer to the owner ("{row.description}")',
            )
        return ClassifiedRow(
            row=row,
            kind="third_party",
            payee=row.counterparty,
            evidence=f'santander: transfer to a third party ("{row.description}")',
        )

    if bank_type == "Pago Movil":
        return ClassifiedRow(
            row=row,
            kind="purchase",
            evidence=f'santander: mobile payment ("{row.description}")',
        )

    if row.amount < 0:
        return ClassifiedRow(
            row=row,
            kind="purchase",
            evidence=(
                f'santander: unrecognised negative row, sign-based fallback ("{row.description}")'
            ),
        )
    return ClassifiedRow(
        row=row,
        kind="income",
        evidence=(
            f'santander: unrecognised positive row, sign-based fallback ("{row.description}")'
        ),
    )


_SOVCOMBANK_SBP_PREFIX = "Зачисление перевода денежных средств/СБП"
_SOVCOMBANK_REPAYMENT_PREFIX = "ПОГАШЕНИЕ КРЕДИТА"


def classify_sovcombank(row: StatementRow, context: ClassifyContext) -> ClassifiedRow:
    description = row.description
    folded = description.casefold()

    if folded.startswith(_SOVCOMBANK_SBP_PREFIX.casefold()):
        if context.owner.mentions_phone(description):
            return ClassifiedRow(
                row=row,
                kind="own_transfer",
                allowed=None,
                evidence=(f'sovcombank: SBP transfer mentioning the owner phone ("{description}")'),
            )
        return ClassifiedRow(
            row=row,
            kind="third_party",
            payee=None,
            evidence=(
                f"sovcombank: SBP transfer, no owner phone, statement names nobody "
                f'("{description}")'
            ),
        )

    if folded.startswith(_SOVCOMBANK_REPAYMENT_PREFIX.casefold()):
        return ClassifiedRow(
            row=row,
            kind="excluded",
            reason="internal_credit_repayment",
            evidence=f'sovcombank: loan repayment ("{description}")',
        )

    if row.reference:
        if row.amount < 0:
            return ClassifiedRow(
                row=row,
                kind="purchase",
                evidence=f'sovcombank: card purchase ("{description}")',
            )
        return ClassifiedRow(
            row=row,
            kind="refund",
            evidence=f'sovcombank: card refund ("{description}")',
        )

    if row.amount < 0:
        return ClassifiedRow(
            row=row,
            kind="fee",
            payee=bank_payee(row, context),
            evidence=f'sovcombank: commission, no card reference ("{description}")',
        )
    return ClassifiedRow(
        row=row,
        kind="income",
        evidence=f'sovcombank: unrecognised positive row, sign-based fallback ("{description}")',
    )


BANK_RULES: dict[str, Callable[[StatementRow, ClassifyContext], ClassifiedRow]] = {
    "revolut": classify_revolut,
    "wise": classify_wise,
    "tbank": classify_tbank,
    "bbva": classify_bbva,
    "santander": classify_santander,
    "sovcombank": classify_sovcombank,
}

CASH_EVIDENCE: dict[str, Callable[[StatementRow], bool]] = {
    "revolut": is_revolut_cash,
    "bbva": is_bbva_cash,
}
