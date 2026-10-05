from decimal import Decimal

import pytest

from smoothment.classify import classify_row
from smoothment.classify.banks import accounts_of
from smoothment.config import AccountEntry, BankSettings, CashSettings, Config, OwnerSettings
from tests.classify_fixtures import OWNER, PARTNER, make_config, make_context, make_row

OWNER_ABBREVIATED = "Сэмпл О."
OWNER_PHONE = "0070000000000"


# --- accounts_of --------------------------------------------------------------


def test_accounts_of_filters_by_bank_kind_and_excluding() -> None:
    config = make_config(
        accounts=[
            AccountEntry(bank="tbank", kind="current", moneywiz="Platinum", acct_id="1"),
            AccountEntry(bank="tbank", kind="current", moneywiz="Black", acct_id="2"),
            AccountEntry(bank="tbank", kind="savings", moneywiz="TBank Savings", acct_id="3"),
            AccountEntry(bank="sovcombank", kind="current", moneywiz="Sovcom", acct_id="4"),
        ]
    )
    assert accounts_of(config, bank="tbank", excluding="Platinum") == frozenset({"Black"})
    assert accounts_of(config, not_bank="tbank", excluding="Platinum") == frozenset({"Sovcom"})


# --- TBank ----------------------------------------------------------------------


def _tbank_accounts_config() -> Config:
    return make_config(
        accounts=[
            AccountEntry(bank="tbank", moneywiz="Platinum", acct_id="1"),
            AccountEntry(bank="tbank", moneywiz="Black", acct_id="2"),
            AccountEntry(bank="sovcombank", moneywiz="Sovcom", acct_id="3"),
        ]
    )


def test_tbank_same_bank_marker_allowed_is_other_tbank_accounts() -> None:
    row = make_row(
        bank="tbank",
        account="Platinum",
        description="Между своими счетами",
        counterparty="Между своими счетами",
        amount=Decimal("-100.00"),
    )
    result = classify_row(row, make_context(_tbank_accounts_config()))
    assert result.kind == "own_transfer"
    assert result.allowed == frozenset({"Black"})
    assert result.pair_only is False
    assert result.evidence


def test_tbank_other_bank_marker_allowed_is_every_non_tbank_account() -> None:
    row = make_row(
        bank="tbank",
        account="Platinum",
        description="Себе в другой банк",
        counterparty="Себе в другой банк",
        amount=Decimal("-50.00"),
    )
    result = classify_row(row, make_context(_tbank_accounts_config()))
    assert result.kind == "own_transfer"
    assert result.allowed == frozenset({"Sovcom"})
    assert result.pair_only is False


def test_tbank_name_is_owner_abbreviated_is_own_transfer_any_account() -> None:
    config = make_config(owner=OwnerSettings(names=[OWNER, OWNER_ABBREVIATED]))
    row = make_row(
        bank="tbank",
        description=OWNER_ABBREVIATED,
        counterparty=OWNER_ABBREVIATED,
        amount=Decimal("-20.00"),
    )
    result = classify_row(row, make_context(config))
    assert result.kind == "own_transfer"
    assert result.allowed is None


def test_tbank_memo_services_is_fee() -> None:
    row = make_row(
        bank="tbank",
        description="Плата за обслуживание",
        counterparty="Плата за обслуживание",
        bank_category="Услуги банка",
        amount=Decimal("-5.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "fee"


def test_tbank_memo_interest_is_interest() -> None:
    row = make_row(
        bank="tbank",
        description="Начисление процентов",
        counterparty="Начисление процентов",
        bank_category="Проценты",
        amount=Decimal("0.10"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "interest"


def test_tbank_name_prefix_interest_on_balance() -> None:
    row = make_row(
        bank="tbank",
        description="Проценты на остаток по счету",
        counterparty="Проценты на остаток по счету",
        bank_category=None,
        amount=Decimal("0.05"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "interest"


def test_tbank_memo_bonuses_is_cashback() -> None:
    row = make_row(
        bank="tbank",
        description="Кэшбэк за покупки",
        counterparty="Кэшбэк за покупки",
        bank_category="Бонусы",
        amount=Decimal("1.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "cashback"


def test_tbank_memo_top_up_is_income() -> None:
    row = make_row(
        bank="tbank",
        description="Внесение наличных через банкомат Т-Банка",
        counterparty="Внесение наличных через банкомат Т-Банка",
        bank_category="Пополнения",
        amount=Decimal("1500.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "income"
    assert result.evidence == 'tbank: account top-up (MEMO "Пополнения")'
    assert result.payee is None


def test_tbank_memo_transfers_none_of_the_above_is_third_party() -> None:
    row = make_row(
        bank="tbank",
        description=PARTNER,
        counterparty=PARTNER,
        bank_category="Переводы",
        amount=Decimal("-30.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "third_party"


def test_tbank_otherwise_negative_is_purchase() -> None:
    row = make_row(
        bank="tbank",
        description="Supermarket",
        counterparty="Supermarket",
        bank_category=None,
        amount=Decimal("-15.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "purchase"


def test_tbank_otherwise_positive_is_refund() -> None:
    row = make_row(
        bank="tbank",
        description="Supermarket",
        counterparty="Supermarket",
        bank_category=None,
        amount=Decimal("15.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "refund"


@pytest.mark.parametrize(
    ("memo", "expected_kind"),
    [("Услуги банка", "fee"), ("Проценты", "interest"), ("Бонусы", "cashback")],
)
def test_tbank_fee_interest_cashback_get_bank_payee_and_evidence(
    memo: str, expected_kind: str
) -> None:
    config = make_config(banks={"tbank": BankSettings(payee="TBank")})
    row = make_row(
        bank="tbank",
        description="Some text",
        counterparty="Some text",
        bank_category=memo,
        amount=Decimal("-5.00"),
    )
    result = classify_row(row, make_context(config))
    assert result.kind == expected_kind
    assert result.payee == "TBank"
    assert result.evidence


# --- BBVA -------------------------------------------------------------------


@pytest.mark.parametrize(
    "concept",
    [
        "Ret. efectivo en cajero",
        "Cash withdrawal at ATM",
        "Ingreso en efectivo",
        "Cash deposit",
    ],
)
def test_bbva_cash_evidence_with_cash_account_configured(concept: str) -> None:
    config = make_config(cash=CashSettings(account="Cash"))
    row = make_row(bank="bbva", description=concept, bank_type=None, amount=Decimal("-40.00"))
    result = classify_row(row, make_context(config))
    assert result.kind == "cash"
    assert result.counterpart == "Cash"


def test_bbva_cash_row_without_cash_account_negative_is_purchase() -> None:
    row = make_row(
        bank="bbva", description="Ret. efectivo en cajero", bank_type=None, amount=Decimal("-40.00")
    )
    result = classify_row(row, make_context())
    assert result.kind == "purchase"


def test_bbva_cash_row_without_cash_account_positive_is_income() -> None:
    row = make_row(
        bank="bbva", description="Ingreso en efectivo", bank_type=None, amount=Decimal("40.00")
    )
    result = classify_row(row, make_context())
    assert result.kind == "income"


@pytest.mark.parametrize("concept", ["Transferencia recibida", "Transfer received"])
def test_bbva_transfer_from_revolut_allowed_is_revolut_accounts(concept: str) -> None:
    config = make_config(
        accounts=[
            AccountEntry(bank="revolut", moneywiz="Shared", acct_id="1"),
            AccountEntry(bank="revolut", moneywiz="Safety", acct_id="2"),
            AccountEntry(bank="bbva", moneywiz="BBVA", acct_id="3"),
        ]
    )
    row = make_row(
        bank="bbva",
        account="BBVA",
        description=concept,
        bank_type="Sent from revolut",
        amount=Decimal("100.00"),
    )
    result = classify_row(row, make_context(config))
    assert result.kind == "own_transfer"
    assert result.allowed == frozenset({"Shared", "Safety"})
    assert result.pair_only is True


def test_bbva_transfer_movement_text_is_owner_is_own_transfer_any_account() -> None:
    row = make_row(
        bank="bbva",
        description="Transferencia realizada",
        bank_type=OWNER,
        amount=Decimal("-100.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "own_transfer"
    assert result.allowed is None
    assert result.pair_only is False


def test_bbva_third_party_payee_strips_to_prefix() -> None:
    row = make_row(
        bank="bbva",
        description="Transfer completed",
        bank_type="To test user",
        amount=Decimal("-25.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "third_party"
    assert result.payee == "test user"


def test_bbva_third_party_payee_strips_from_prefix() -> None:
    row = make_row(
        bank="bbva",
        description="Transferencia recibida",
        bank_type="From another person",
        amount=Decimal("25.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "third_party"
    assert result.payee == "another person"


@pytest.mark.parametrize("movement", ["Card payment", "Pago con tarjeta"])
def test_bbva_card_payment_is_purchase(movement: str) -> None:
    row = make_row(
        bank="bbva", description="Restaurant", bank_type=movement, amount=Decimal("-12.00")
    )
    result = classify_row(row, make_context())
    assert result.kind == "purchase"


def test_bbva_otherwise_negative_is_purchase() -> None:
    row = make_row(
        bank="bbva", description="Misc", bank_type="Something else", amount=Decimal("-9.00")
    )
    result = classify_row(row, make_context())
    assert result.kind == "purchase"


def test_bbva_otherwise_positive_is_income() -> None:
    row = make_row(
        bank="bbva", description="Misc", bank_type="Something else", amount=Decimal("9.00")
    )
    result = classify_row(row, make_context())
    assert result.kind == "income"


# --- Santander ------------------------------------------------------------------


def test_santander_transfer_to_owner_from_revolut_allowed_is_revolut_accounts() -> None:
    config = make_config(
        accounts=[
            AccountEntry(bank="revolut", moneywiz="Shared", acct_id="1"),
            AccountEntry(bank="santander", moneywiz="Santander", acct_id="2"),
        ]
    )
    row = make_row(
        bank="santander",
        account="Santander",
        description="Transferencia A Favor De Sample Owner",
        bank_type="Transferencia",
        counterparty=OWNER,
        reference="Sent From Revolut",
        amount=Decimal("200.00"),
    )
    result = classify_row(row, make_context(config))
    assert result.kind == "own_transfer"
    assert result.allowed == frozenset({"Shared"})
    assert result.pair_only is False


def test_santander_transfer_to_owner_other_reference_allowed_is_none() -> None:
    row = make_row(
        bank="santander",
        description="Transferencia De Sample Owner",
        bank_type="Transferencia",
        counterparty=OWNER,
        reference="Some other note",
        amount=Decimal("200.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "own_transfer"
    assert result.allowed is None


def test_santander_transfer_non_owner_with_revolut_reference_is_third_party() -> None:
    row = make_row(
        bank="santander",
        description="Transferencia A Favor De Partner Person",
        bank_type="Transferencia",
        counterparty=PARTNER,
        reference="Sent From Revolut",
        amount=Decimal("-50.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "third_party"


def test_santander_pago_movil_is_purchase() -> None:
    row = make_row(
        bank="santander",
        description="Pago Movil En Cafe",
        bank_type="Pago Movil",
        counterparty="Cafe",
        amount=Decimal("-4.50"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "purchase"


def test_santander_otherwise_negative_is_purchase() -> None:
    row = make_row(bank="santander", description="Misc", bank_type=None, amount=Decimal("-7.00"))
    result = classify_row(row, make_context())
    assert result.kind == "purchase"


def test_santander_otherwise_positive_is_income() -> None:
    row = make_row(bank="santander", description="Misc", bank_type=None, amount=Decimal("7.00"))
    result = classify_row(row, make_context())
    assert result.kind == "income"


# --- Sovcombank -------------------------------------------------------------------


def test_sovcombank_sbp_with_owner_phone_is_own_transfer() -> None:
    config = make_config(owner=OwnerSettings(names=[OWNER], phones=[OWNER_PHONE]))
    row = make_row(
        bank="sovcombank",
        description=f"Зачисление перевода денежных средств/СБП +{OWNER_PHONE}",
        currency="RUB",
        amount=Decimal("500.00"),
    )
    result = classify_row(row, make_context(config))
    assert result.kind == "own_transfer"
    assert result.allowed is None


def test_sovcombank_sbp_without_configured_phone_is_third_party_no_payee() -> None:
    row = make_row(
        bank="sovcombank",
        description="Зачисление перевода денежных средств/СБП +79998887766",
        currency="RUB",
        amount=Decimal("500.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "third_party"
    assert result.payee is None


def test_sovcombank_loan_repayment_is_excluded() -> None:
    row = make_row(
        bank="sovcombank",
        description="ПОГАШЕНИЕ КРЕДИТА по договору",
        currency="RUB",
        amount=Decimal("-1000.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "excluded"
    assert result.reason == "internal_credit_repayment"


def test_sovcombank_card_row_negative_is_purchase() -> None:
    row = make_row(
        bank="sovcombank",
        description="Supermarket",
        reference="*1234",
        currency="RUB",
        amount=Decimal("-300.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "purchase"


def test_sovcombank_card_row_positive_is_refund() -> None:
    row = make_row(
        bank="sovcombank",
        description="Supermarket",
        reference="*1234",
        currency="RUB",
        amount=Decimal("300.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "refund"


def test_sovcombank_other_negative_is_fee() -> None:
    row = make_row(
        bank="sovcombank",
        description="Комиссия за обслуживание",
        reference=None,
        currency="RUB",
        amount=Decimal("-50.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "fee"


def test_sovcombank_other_positive_is_income() -> None:
    row = make_row(
        bank="sovcombank",
        description="Начисление процентов",
        reference=None,
        currency="RUB",
        amount=Decimal("50.00"),
    )
    result = classify_row(row, make_context())
    assert result.kind == "income"


def test_sovcombank_fee_gets_bank_payee() -> None:
    config = make_config(banks={"sovcombank": BankSettings(payee="Sovcombank")})
    row = make_row(
        bank="sovcombank",
        description="Комиссия",
        reference=None,
        currency="RUB",
        amount=Decimal("-50.00"),
    )
    result = classify_row(row, make_context(config))
    assert result.payee == "Sovcombank"
