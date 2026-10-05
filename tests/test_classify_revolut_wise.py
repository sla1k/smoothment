from decimal import Decimal
from pathlib import Path

import pytest

from smoothment.classify import (
    HIDDEN_POCKET_HIDDEN,
    HIDDEN_POCKET_UNMAPPED,
    classify_row,
    classify_statement,
)
from smoothment.config import AccountEntry, BankSettings, CashSettings, Config, PocketSettings
from smoothment.statement.model import ParsedStatement
from tests.classify_fixtures import (
    JOINT_COUNTERPARTY,
    OWNER,
    PARTNER,
    make_config,
    make_context,
    make_row,
)

# --- Common rule 1: reverted -------------------------------------------------


def test_reverted_row_is_excluded() -> None:
    row = make_row(state="reverted")
    result = classify_row(row, make_context())
    assert result.kind == "excluded"
    assert result.reason == "reverted"
    assert result.evidence


# --- Common rule 2: savings statement ----------------------------------------


@pytest.mark.parametrize(
    ("bank_type", "expected_kind", "expected_reason"),
    [
        ("BUY", "excluded", "mirrored_by_main_export"),
        ("SELL", "excluded", "mirrored_by_main_export"),
        ("Return Reinvested", "excluded", "savings_internal"),
        ("Return WITHDRAWN", "excluded", "savings_internal"),
        ("Interest WITHDRAWN", "excluded", "savings_internal"),
        ("Return PAID", "interest", None),
        ("Interest PAID", "interest", None),
        ("Service Fee Charged", "fee", None),
    ],
)
def test_savings_bank_types(
    bank_type: str, expected_kind: str, expected_reason: str | None
) -> None:
    row = make_row(kind="savings", bank_type=bank_type, amount=Decimal("-1.00"))
    result = classify_row(row, make_context())
    assert result.kind == expected_kind
    assert result.reason == expected_reason
    assert result.evidence


def test_savings_unknown_type_positive_is_income() -> None:
    row = make_row(kind="savings", bank_type=None, amount=Decimal("5.00"))
    result = classify_row(row, make_context())
    assert result.kind == "income"
    assert result.evidence


def test_savings_unknown_type_negative_is_purchase() -> None:
    row = make_row(kind="savings", bank_type=None, amount=Decimal("-5.00"))
    result = classify_row(row, make_context())
    assert result.kind == "purchase"
    assert result.evidence


def test_savings_fee_gets_bank_payee_when_configured() -> None:
    config = make_config(banks={"revolut": BankSettings(payee="Revolut")})
    row = make_row(kind="savings", bank_type="Service Fee Charged", amount=Decimal("-1.00"))
    result = classify_row(row, make_context(config))
    assert result.kind == "fee"
    assert result.payee == "Revolut"


def test_savings_interest_payee_none_when_not_configured() -> None:
    row = make_row(kind="savings", bank_type="Return PAID", amount=Decimal("0.02"))
    result = classify_row(row, make_context())
    assert result.kind == "interest"
    assert result.payee is None


# --- Common rule 3: pocket rows -----------------------------------------------


SHARED = AccountEntry(bank="revolut", moneywiz="Shared", file="revolut_shared*")


def _pocket_config() -> Config:
    return make_config(
        accounts=[SHARED],
        pockets=PocketSettings(accounts={"Shared": {"Travel": "Travel", "Secret": "hidden"}}),
    )


def test_pocket_move_mapped_pocket() -> None:
    row = make_row(pocket="Travel", pocket_side=False, amount=Decimal("-5.00"))
    result = classify_row(row, make_context(_pocket_config()))
    assert result.kind == "pocket_move"
    assert result.counterpart == "Travel"
    assert result.evidence


def test_pocket_move_hidden_pocket_is_excluded() -> None:
    row = make_row(pocket="Secret", pocket_side=False)
    result = classify_row(row, make_context(_pocket_config()))
    assert result.kind == "excluded"
    assert result.reason == "hidden_pocket"
    assert result.reason_detail == HIDDEN_POCKET_HIDDEN


def test_pocket_move_unmapped_pocket_is_excluded() -> None:
    row = make_row(pocket="Unknown", pocket_side=False)
    result = classify_row(row, make_context(_pocket_config()))
    assert result.kind == "excluded"
    assert result.reason == "hidden_pocket"
    assert result.reason_detail == HIDDEN_POCKET_UNMAPPED


def test_pocket_side_interest_is_pocket_income_with_account_and_payee() -> None:
    config = make_config(
        accounts=[SHARED],
        pockets=PocketSettings(accounts={"Shared": {"Travel": "Travel"}}),
        banks={"revolut": BankSettings(payee="Revolut")},
    )
    row = make_row(pocket="Travel", pocket_side=True, bank_type="Interest", amount=Decimal("0.01"))
    result = classify_row(row, make_context(config))
    assert result.kind == "pocket_income"
    assert result.account == "Travel"
    assert result.payee == "Revolut"
    assert result.evidence


@pytest.mark.parametrize("bank_type", ["INTEREST", "interest", "Interest"])
def test_pocket_side_interest_type_is_matched_case_insensitively(bank_type: str) -> None:
    row = make_row(pocket="Travel", pocket_side=True, bank_type=bank_type, amount=Decimal("0.01"))
    result = classify_row(row, make_context(_pocket_config()))
    assert result.kind == "pocket_income"
    assert result.account == "Travel"


def test_pocket_side_non_interest_row_is_excluded() -> None:
    row = make_row(pocket="Travel", pocket_side=True, bank_type="Transfer", amount=Decimal("0.50"))
    result = classify_row(row, make_context(_pocket_config()))
    assert result.kind == "excluded"
    assert result.reason == "pocket_side_row"


def test_pocket_side_row_without_pocket_name_is_excluded_without_mapping_lookup() -> None:
    # an internal leg such as a savings-vault prefunding wallet move: never mapped, never hidden
    row = make_row(
        pocket=None,
        pocket_side=True,
        description="Saving vault deposit prefunding wallet",
        amount=Decimal("-5.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "excluded"
    assert result.reason == "pocket_side_row"
    assert result.evidence


# --- Common rule 4: cash (Revolut ATM evidence) ------------------------------


def _cash_config() -> Config:
    return make_config(cash=CashSettings(account="Cash"))


def test_atm_row_with_cash_account_configured_is_cash() -> None:
    row = make_row(
        bank_type="ATM", description="Cash withdrawal at Sample Bank", amount=Decimal("-50.00")
    )
    result = classify_row(row, make_context(_cash_config()))
    assert result.kind == "cash"
    assert result.counterpart == "Cash"
    assert result.evidence


def test_atm_row_without_cash_account_configured_is_purchase() -> None:
    # same row, no [cash] table in config at all -- the pocket table for cash is unset
    row = make_row(
        bank_type="ATM", description="Cash withdrawal at Sample Bank", amount=Decimal("-50.00")
    )
    result = classify_row(row, make_context())
    assert result.kind == "purchase"
    assert result.evidence


def test_non_atm_row_with_cash_account_configured_is_unaffected() -> None:
    row = make_row(bank_type="Card Payment", amount=Decimal("-3.50"))
    result = classify_row(row, make_context(_cash_config()))
    assert result.kind == "purchase"


# --- Revolut current rules ----------------------------------------------------


def test_revolut_charge_is_fee() -> None:
    row = make_row(bank_type="Charge", description="Metal plan fee", amount=Decimal("-15.99"))
    result = classify_row(row, make_context())
    assert result.kind == "fee"
    assert result.evidence


def test_revolut_interest_current_side_is_interest() -> None:
    row = make_row(bank_type="Interest", description="Interest paid", amount=Decimal("0.05"))
    result = classify_row(row, make_context())
    assert result.kind == "interest"
    assert result.evidence


@pytest.mark.parametrize("bank_type", ["Card Refund", "Card Credit"])
def test_revolut_card_refund_types(bank_type: str) -> None:
    row = make_row(bank_type=bank_type, amount=Decimal("5.00"))
    result = classify_row(row, make_context())
    assert result.kind == "refund"


def test_revolut_transfer_to_owner_is_own_transfer() -> None:
    row = make_row(
        bank_type="Transfer",
        description=f"Transfer to {OWNER}",
        counterparty=OWNER,
        amount=Decimal("-20.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "own_transfer"
    assert result.allowed is None
    assert result.counterpart is None
    assert result.evidence


def test_revolut_transfer_to_joint_account_counts_as_owner() -> None:
    row = make_row(
        bank_type="Transfer",
        description=f"Transfer to {JOINT_COUNTERPARTY}",
        counterparty=JOINT_COUNTERPARTY,
        amount=Decimal("-20.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "own_transfer"


def test_revolut_transfer_to_partner_alone_is_third_party() -> None:
    row = make_row(
        bank_type="Transfer",
        description=f"Transfer to {PARTNER}",
        counterparty=PARTNER,
        amount=Decimal("-20.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "third_party"
    assert result.payee == PARTNER


def test_revolut_deposit_no_counterparty_uses_description_as_payee() -> None:
    row = make_row(
        bank_type="Deposit",
        description="Utility Co Direct Debit",
        counterparty=None,
        amount=Decimal("-30.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "third_party"
    assert result.payee == "Utility Co Direct Debit"


def test_revolut_card_payment_is_purchase() -> None:
    row = make_row(bank_type="Card Payment", amount=Decimal("-3.50"))
    result = classify_row(row, make_context())
    assert result.kind == "purchase"


def test_revolut_pending_purchase_is_purchase() -> None:
    row = make_row(bank_type="Card Payment", amount=Decimal("-9.99"), state="pending")
    result = classify_row(row, make_context())
    assert result.kind == "purchase"


def test_revolut_rev_payment_negative_is_purchase() -> None:
    row = make_row(bank_type="Rev Payment", amount=Decimal("-12.00"))
    result = classify_row(row, make_context())
    assert result.kind == "purchase"


def test_revolut_unrecognised_positive_is_income() -> None:
    row = make_row(bank_type="Something Else", amount=Decimal("2.00"))
    result = classify_row(row, make_context())
    assert result.kind == "income"


# --- Wise rules ----------------------------------------------------------------


def test_wise_cashback_by_external_id() -> None:
    row = make_row(
        bank="wise",
        external_id="BALANCE_CASHBACK-300000001",
        description="Cashback",
        amount=Decimal("0.87"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "cashback"


def test_wise_cashback_by_description_even_without_marked_id() -> None:
    row = make_row(
        bank="wise",
        external_id="SOMETHING-1",
        description="Cashback",
        amount=Decimal("0.50"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "cashback"


def test_wise_cashback_gets_bank_payee_when_configured() -> None:
    config = make_config(banks={"wise": BankSettings(payee="Wise")})
    row = make_row(
        bank="wise",
        external_id="BALANCE_CASHBACK-1",
        description="Cashback",
        amount=Decimal("0.50"),
    )
    result = classify_row(row, make_context(config))
    assert result.payee == "Wise"


def test_wise_money_added_is_own_transfer() -> None:
    row = make_row(bank="wise", bank_type="MONEY_ADDED", amount=Decimal("100.00"))
    result = classify_row(row, make_context())
    assert result.kind == "own_transfer"
    assert result.allowed is None
    assert result.pair_only is True


@pytest.mark.parametrize("bank_type", ["TRANSFER", "DEPOSIT"])
def test_wise_transfer_to_owner_without_account_match_is_own_transfer_any_account(
    bank_type: str,
) -> None:
    row = make_row(
        bank="wise",
        bank_type=bank_type,
        counterparty=OWNER,
        counterparty_account=None,
        amount=Decimal("-42.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "own_transfer"
    assert result.allowed is None
    assert result.counterpart is None


def test_wise_transfer_to_owner_with_iban_match_restricts_allowed() -> None:
    # spaces on the configured side; the parser already strips them from counterparty_account
    account = AccountEntry(
        bank="santander", moneywiz="Santander", iban="ES00 0000 0000 0000 0000 0000"
    )
    config = make_config(accounts=[account])
    row = make_row(
        bank="wise",
        bank_type="TRANSFER",
        counterparty=OWNER,
        counterparty_account="ES0000000000000000000000",
        amount=Decimal("-42.00"),
    )
    result = classify_row(row, make_context(config))
    assert result.kind == "own_transfer"
    assert result.allowed == frozenset({"Santander"})
    assert result.counterpart == "Santander"


def test_wise_transfer_naming_the_wise_account_itself_is_not_a_self_transfer() -> None:
    config = make_config(
        accounts=[
            AccountEntry(bank="wise", moneywiz="Wise", iban="BE00 0000 0000 0000"),
            AccountEntry(bank="revolut", moneywiz="Revolut", acct_id="1"),
        ]
    )
    row = make_row(
        bank="wise",
        account="Wise",
        bank_type="TRANSFER",
        counterparty=OWNER,
        counterparty_account="BE00000000000000",
        amount=Decimal("42.00"),
    )
    result = classify_row(row, make_context(config))
    assert result.kind == "own_transfer"
    assert result.allowed is None
    assert result.counterpart is None


def test_wise_transfer_to_owner_with_acct_id_match_restricts_allowed() -> None:
    account = AccountEntry(bank="tbank", moneywiz="Black", acct_id="40817810000000000001")
    config = make_config(accounts=[account])
    row = make_row(
        bank="wise",
        bank_type="TRANSFER",
        counterparty=OWNER,
        counterparty_account="40817810000000000001",
        amount=Decimal("-42.00"),
    )
    result = classify_row(row, make_context(config))
    assert result.allowed == frozenset({"Black"})
    assert result.counterpart == "Black"


def test_wise_transfer_other_counterparty_is_third_party() -> None:
    row = make_row(
        bank="wise", bank_type="TRANSFER", counterparty=PARTNER, amount=Decimal("-42.00")
    )
    result = classify_row(row, make_context())
    assert result.kind == "third_party"


def test_wise_transfer_no_counterparty_is_third_party() -> None:
    row = make_row(bank="wise", bank_type="DEPOSIT", counterparty=None, amount=Decimal("44.00"))
    result = classify_row(row, make_context())
    assert result.kind == "third_party"


def test_wise_incoming_transfer_uses_payer_name_and_is_own_transfer() -> None:
    # counterparty already carries the payer's name for an inflow (parser step 2 behaviour)
    row = make_row(bank="wise", bank_type="DEPOSIT", counterparty=OWNER, amount=Decimal("44.00"))
    result = classify_row(row, make_context())
    assert result.kind == "own_transfer"


def test_wise_incoming_transfer_third_party_payer_stays_third_party() -> None:
    row = make_row(bank="wise", bank_type="DEPOSIT", counterparty=PARTNER, amount=Decimal("44.00"))
    result = classify_row(row, make_context())
    assert result.kind == "third_party"


def test_wise_card_negative_is_purchase() -> None:
    row = make_row(bank="wise", bank_type="CARD", amount=Decimal("-2.70"))
    result = classify_row(row, make_context())
    assert result.kind == "purchase"


def test_wise_card_positive_is_refund() -> None:
    row = make_row(bank="wise", bank_type="CARD", amount=Decimal("2.70"))
    result = classify_row(row, make_context())
    assert result.kind == "refund"


def test_wise_unknown_type_negative_is_purchase() -> None:
    row = make_row(bank="wise", bank_type="UNKNOWN", amount=Decimal("-5.00"))
    result = classify_row(row, make_context())
    assert result.kind == "purchase"


def test_wise_unknown_type_positive_is_income() -> None:
    row = make_row(bank="wise", bank_type="UNKNOWN", amount=Decimal("5.00"))
    result = classify_row(row, make_context())
    assert result.kind == "income"


# --- Banks without rules yet: sign-based fallback ------------------------------


@pytest.mark.parametrize("bank", ["not_a_configured_bank"])
def test_bank_without_rules_falls_back_to_purchase_when_negative(bank: str) -> None:
    row = make_row(bank=bank, amount=Decimal("-5.00"))
    result = classify_row(row, make_context())
    assert result.kind == "purchase"
    assert result.evidence


@pytest.mark.parametrize("bank", ["not_a_configured_bank"])
def test_bank_without_rules_falls_back_to_income_when_positive(bank: str) -> None:
    row = make_row(bank=bank, amount=Decimal("5.00"))
    result = classify_row(row, make_context())
    assert result.kind == "income"
    assert result.evidence


# --- classify_statement ---------------------------------------------------------


def test_classify_statement_returns_one_result_per_row_in_order() -> None:
    rows = (
        make_row(line=1, amount=Decimal("-1.00")),
        make_row(line=2, amount=Decimal("2.00")),
        make_row(line=3, state="reverted"),
    )
    statement = ParsedStatement(
        file=Path("/tmp/x.csv"),
        bank="revolut",
        kind="current",
        account="Shared",
        rows=rows,
        input_rows=3,
    )
    results = classify_statement(statement, make_context())
    assert len(results) == 3
    assert [result.row.line for result in results] == [1, 2, 3]
    assert all(result.evidence for result in results)
