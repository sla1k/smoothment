from smoothment.classify import banks
from smoothment.classify.banks import bank_payee
from smoothment.classify.model import ClassifiedRow, ClassifyContext, RowKind
from smoothment.statement.model import ParsedStatement, StatementRow

HIDDEN_POCKET_UNMAPPED = "not in config"
HIDDEN_POCKET_HIDDEN = "mapped to hidden"

_SAVINGS_MIRRORED = {"BUY", "SELL"}
_SAVINGS_INTERNAL = {"Return Reinvested", "Return WITHDRAWN", "Interest WITHDRAWN"}
_SAVINGS_INTEREST = {"Return PAID", "Interest PAID"}


def _classify_savings(row: StatementRow, context: ClassifyContext) -> ClassifiedRow:
    bank_type = row.bank_type

    if bank_type in _SAVINGS_MIRRORED:
        return ClassifiedRow(
            row=row,
            kind="excluded",
            reason="mirrored_by_main_export",
            evidence=f'common: savings "{bank_type}" is mirrored on the current export',
        )
    if bank_type in _SAVINGS_INTERNAL:
        return ClassifiedRow(
            row=row,
            kind="excluded",
            reason="savings_internal",
            evidence=f'common: internal savings movement ("{bank_type}")',
        )
    if bank_type in _SAVINGS_INTEREST:
        return ClassifiedRow(
            row=row,
            kind="interest",
            payee=bank_payee(row, context),
            evidence=f'common: savings interest ("{bank_type}")',
        )
    if bank_type == "Service Fee Charged":
        return ClassifiedRow(
            row=row,
            kind="fee",
            payee=bank_payee(row, context),
            evidence=f'common: savings fee ("{bank_type}")',
        )

    kind: RowKind = "income" if row.amount > 0 else "purchase"
    return ClassifiedRow(
        row=row,
        kind=kind,
        evidence=f'common: unrecognised savings type, sign-based fallback ("{bank_type}")',
    )


def _classify_pocket(row: StatementRow, context: ClassifyContext) -> ClassifiedRow:
    pocket = row.pocket

    if pocket is None:
        # An internal pocket-side leg that names no pocket (e.g. a savings-vault prefunding
        # wallet move) never goes through the mapping lookup.
        return ClassifiedRow(
            row=row,
            kind="excluded",
            reason="pocket_side_row",
            evidence=(
                f'common: internal pocket-side leg without a pocket name ("{row.description}")'
            ),
        )

    accounts = context.config.pockets.accounts
    target = accounts.get(row.account, {}).get(pocket)

    if target is None or target == "hidden":
        return ClassifiedRow(
            row=row,
            kind="excluded",
            reason="hidden_pocket",
            reason_detail=HIDDEN_POCKET_UNMAPPED if target is None else HIDDEN_POCKET_HIDDEN,
            evidence=f'common: pocket "{pocket}" has no mapping or is hidden',
        )
    if row.pocket_side:
        if banks.revolut_type(row) == "interest":
            return ClassifiedRow(
                row=row,
                kind="pocket_income",
                account=target,
                payee=bank_payee(row, context),
                evidence=f'common: interest paid into pocket "{pocket}" ("{row.description}")',
            )
        return ClassifiedRow(
            row=row,
            kind="excluded",
            reason="pocket_side_row",
            evidence=(
                f'common: pocket-side row mirrored on the current export ("{row.description}")'
            ),
        )
    return ClassifiedRow(
        row=row,
        kind="pocket_move",
        counterpart=target,
        evidence=f'common: move to pocket "{pocket}" ("{row.description}")',
    )


def _fallback(row: StatementRow) -> ClassifiedRow:
    kind: RowKind = "purchase" if row.amount < 0 else "income"
    return ClassifiedRow(
        row=row,
        kind=kind,
        evidence=f"{row.bank}: no bank rules exist yet, sign-based fallback",
    )


def classify_row(row: StatementRow, context: ClassifyContext) -> ClassifiedRow:
    if row.state == "reverted":
        return ClassifiedRow(
            row=row, kind="excluded", reason="reverted", evidence="common: reverted state"
        )

    if row.kind == "savings":
        return _classify_savings(row, context)

    if row.pocket is not None or row.pocket_side:
        return _classify_pocket(row, context)

    if context.config.cash is not None:
        is_cash = banks.CASH_EVIDENCE.get(row.bank)
        if is_cash is not None and is_cash(row):
            return ClassifiedRow(
                row=row,
                kind="cash",
                counterpart=context.config.cash.account,
                evidence=f'{row.bank}: cash evidence ("{row.description}")',
            )

    handler = banks.BANK_RULES.get(row.bank)
    if handler is not None:
        return handler(row, context)
    return _fallback(row)


def classify_statement(
    statement: ParsedStatement, context: ClassifyContext
) -> tuple[ClassifiedRow, ...]:
    return tuple(classify_row(row, context) for row in statement.rows)
