import csv
import hashlib
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from smoothment.classify.model import ClassifiedRow, RowKind
from smoothment.export import (
    COLUMNS,
    UNMATCHED_PAYEE,
    ExportPlan,
    ExportRow,
    TransferLeg,
    assign_tags,
    lump_tag,
    memo_tag,
    to_export_rows,
    write_csv,
)
from smoothment.lumps import Lump, LumpKind, lump_key
from smoothment.statement.model import StatementRow


def _row(
    *,
    bank: str = "revolut",
    account: str = "Main",
    line: int = 1,
    date: datetime = datetime(2026, 1, 1),
    amount: Decimal = Decimal("10.00"),
    description: str = "Coffee",
    counterparty: str | None = None,
    external_id: str | None = None,
) -> StatementRow:
    return StatementRow(
        bank=bank,
        account=account,
        line=line,
        date=date,
        has_time=False,
        amount=amount,
        currency="EUR",
        description=description,
        counterparty=counterparty,
        external_id=external_id,
    )


def test_memo_tag_is_stable_prefixed_and_16_chars() -> None:
    row = _row()
    tag = memo_tag(row)
    other = memo_tag(row)
    assert tag == other
    assert tag.startswith("smt:")
    assert len(tag) == 16


def test_memo_tag_differs_by_account() -> None:
    a = memo_tag(_row(account="Main"))
    b = memo_tag(_row(account="Other"))
    assert a != b


def test_memo_tag_differs_by_external_id() -> None:
    a = memo_tag(_row(external_id="abc"))
    b = memo_tag(_row(external_id="xyz"))
    assert a != b


def test_memo_tag_same_for_different_line_when_external_id_set() -> None:
    a = memo_tag(_row(line=1, external_id="abc"))
    b = memo_tag(_row(line=99, external_id="abc"))
    assert a == b


def _classified(
    row: StatementRow, kind: RowKind = "purchase", payee: str | None = None
) -> ClassifiedRow:
    return ClassifiedRow(row=row, kind=kind, evidence="test", payee=payee)


def _plain(*rows: StatementRow) -> tuple[ExportRow, ...]:
    plan = ExportPlan(plain=tuple(_classified(row) for row in rows), tags=assign_tags(rows))
    return to_export_rows(plan)


def _lump(
    *,
    kind: LumpKind = "roundups",
    account: str = "Main",
    pocket: str | None = "Travel",
    counterpart: str | None = "Travel",
    day: date = date(2026, 1, 1),
    first: date = date(2026, 1, 1),
    count: int = 2,
    amount: Decimal = Decimal("-0.90"),
    payee: str | None = None,
    source_account: str | None = None,
    cutoff: datetime | None = None,
) -> Lump:
    source = source_account or account
    rows = tuple(
        _classified(_row(account=source, line=100 + i), kind="pocket_move") for i in range(count)
    )
    return Lump(
        kind=kind,
        bank="revolut",
        account=account,
        source_account=source,
        key=lump_key("revolut", source, kind, pocket, account),
        cutoff=cutoff or datetime.combine(day, datetime.min.time()).replace(hour=10),
        counterpart=counterpart,
        pocket=pocket,
        amount=amount,
        date=day,
        first=first,
        rows=rows,
        payee=payee,
    )


def test_assign_tags_numbers_identical_rows_in_the_given_order() -> None:
    row_a = _row(line=1)
    row_b = _row(line=2)
    other = _row(line=3, description="Tea")

    tags = assign_tags([row_a, other, row_b])

    assert tags[id(row_a)] == memo_tag(row_a)
    assert tags[id(row_b)] == memo_tag(row_a, 1)
    assert tags[id(other)] == memo_tag(other)


def test_tags_do_not_depend_on_which_identical_row_is_exported() -> None:
    row_a = _row(line=1)
    row_b = _row(line=2)
    tags = assign_tags([row_a, row_b])

    only_b = to_export_rows(ExportPlan(plain=(_classified(row_b),), tags=tags))
    only_a = to_export_rows(ExportPlan(plain=(_classified(row_a),), tags=tags))

    assert only_b[0].memo == memo_tag(row_a, 1)
    assert only_a[0].memo == memo_tag(row_a)


def test_tag_of_a_row_does_not_change_when_another_row_leaves_the_plan() -> None:
    first = _row(line=1)
    second = _row(line=2, description="Tea")
    third = _row(line=3)
    tags = assign_tags([first, second, third])

    full = to_export_rows(
        ExportPlan(plain=tuple(_classified(r) for r in (first, second, third)), tags=tags)
    )
    without_second = to_export_rows(
        ExportPlan(plain=(_classified(first), _classified(third)), tags=tags)
    )

    assert full[2].memo == without_second[1].memo == memo_tag(first, 1)


def test_a_row_missing_from_tags_falls_back_to_the_base_tag() -> None:
    row = _row()

    (exported,) = to_export_rows(ExportPlan(plain=(_classified(row),)))

    assert exported.memo == memo_tag(row)


def test_to_export_rows_sorts_by_account_date_line() -> None:
    row_z = _row(account="Z", line=1, date=datetime(2026, 1, 1))
    row_a_late = _row(account="A", line=2, date=datetime(2026, 1, 2))
    row_a_early = _row(account="A", line=1, date=datetime(2026, 1, 1))

    rows = _plain(row_z, row_a_late, row_a_early)

    assert [(r.account, r.date) for r in rows] == [
        ("A", row_a_early.date.date()),
        ("A", row_a_late.date.date()),
        ("Z", row_z.date.date()),
    ]


def test_to_export_rows_payee_falls_back_to_description() -> None:
    with_counterparty = _row(description="raw desc", counterparty="Alex")
    without_counterparty = _row(description="raw desc", counterparty=None)

    rows = _plain(with_counterparty, without_counterparty)

    assert {(r.payee, r.description) for r in rows} == {("Alex", "raw desc"), ("raw desc", "")}


def test_classified_payee_wins_over_counterparty() -> None:
    row = _row(description="Transfer to Alex", counterparty="Alex")
    plan = ExportPlan(plain=(_classified(row, kind="third_party", payee="Alex Example"),))

    (exported,) = to_export_rows(plan)

    assert (exported.payee, exported.transfers) == ("Alex Example", "")
    assert exported.description == "Transfer to Alex"


def test_description_is_blank_when_it_only_repeats_the_payee() -> None:
    repeated = _row(description="Coffee  Corner", counterparty="coffee corner")
    detailed = _row(
        description="Card transaction of 151.35 TRY issued by Sample Cafe",
        counterparty="Sample Cafe",
    )

    rows = {r.payee: r.description for r in _plain(repeated, detailed)}

    assert rows["coffee corner"] == ""
    assert rows["Sample Cafe"] == "Card transaction of 151.35 TRY issued by Sample Cafe"


def test_bank_rows_get_the_bank_payee() -> None:
    fee = _classified(_row(line=1, description="Metal plan fee"), kind="fee", payee="Revolut")
    interest = _classified(_row(line=2, description="Interest"), kind="interest", payee="Revolut")
    cashback = _classified(_row(line=3, description="Cashback"), kind="cashback", payee="Wise")

    rows = to_export_rows(ExportPlan(plain=(fee, interest, cashback)))

    assert [(r.payee, r.description, r.transfers) for r in rows] == [
        ("Revolut", "Metal plan fee", ""),
        ("Revolut", "Interest", ""),
        ("Wise", "Cashback", ""),
    ]


def test_bank_row_without_a_configured_payee_uses_the_default_payee() -> None:
    fee = _classified(_row(description="Account fee", counterparty=None), kind="fee")

    (exported,) = to_export_rows(ExportPlan(plain=(fee,)))

    assert (exported.payee, exported.description) == ("Account fee", "")


def test_transfer_leg_has_no_payee_or_description() -> None:
    leg = _classified(_row(amount=Decimal("-44.00"), description="To Sample Owner"), "own_transfer")

    (exported,) = to_export_rows(ExportPlan(transfers=(TransferLeg(row=leg, counterpart="Wise"),)))

    assert exported.amount == Decimal("-44.00")
    assert exported.account == "Main"
    assert (exported.payee, exported.description) == ("", "")
    assert exported.transfers == "Wise"
    assert exported.memo == memo_tag(leg.row)


def test_transfer_exported_with_one_leg_carries_both_tags_outgoing_first() -> None:
    outgoing = _classified(_row(amount=Decimal("-44.00"), description="To Wise"), "own_transfer")
    incoming = _classified(
        _row(account="Wise", amount=Decimal("44.00"), description="From Main"), "own_transfer"
    )
    tags = assign_tags([outgoing.row, incoming.row])
    leg = TransferLeg(row=outgoing, counterpart="Wise", merged=incoming)

    (exported,) = to_export_rows(ExportPlan(transfers=(leg,), tags=tags))

    assert exported.memo == f"{memo_tag(outgoing.row)} {memo_tag(incoming.row)}"
    assert exported.memo.count("smt:") == 2


def test_transfer_leg_without_a_merged_partner_carries_one_tag() -> None:
    leg = _classified(_row(amount=Decimal("-44.00")), "own_transfer")

    (exported,) = to_export_rows(ExportPlan(transfers=(TransferLeg(row=leg, counterpart="Wise"),)))

    assert exported.memo == memo_tag(leg.row)


def test_unmatched_transfer_is_exported_with_a_marker_payee_and_raw_description() -> None:
    row = _row(amount=Decimal("100.00"), description="Payment from Sample Owner")

    (exported,) = to_export_rows(ExportPlan(unmatched=(_classified(row, "own_transfer"),)))

    assert exported.payee == UNMATCHED_PAYEE == "Unmatched transfer"
    assert exported.description == "Payment from Sample Owner"
    assert exported.transfers == ""


def test_roundup_lump_is_a_transfer_to_the_pocket_account() -> None:
    lump = _lump(first=date(2026, 1, 1), day=date(2026, 1, 20), count=3)

    (exported,) = to_export_rows(ExportPlan(lumps=(lump,)))

    assert exported == ExportRow(
        date=date(2026, 1, 20),
        amount=Decimal("-0.90"),
        payee="",
        description="3 round-ups, 2026-01-01 to 2026-01-20",
        account="Main",
        transfers="Travel",
        memo=f"{lump_tag(lump)} smt-lump:{lump.key}:20260120T100000",
    )


def test_interest_and_fee_lumps_carry_the_bank_payee() -> None:
    interest = _lump(
        kind="interest",
        account="Safety",
        pocket=None,
        counterpart=None,
        amount=Decimal("0.13"),
        count=1,
        payee="Revolut",
    )
    fee = _lump(
        kind="fee",
        account="Safety",
        pocket=None,
        counterpart=None,
        amount=Decimal("-0.01"),
        count=2,
        payee="Revolut",
    )

    rows = to_export_rows(ExportPlan(lumps=(interest, fee)))

    assert {(r.payee, r.transfers, r.description) for r in rows} == {
        ("Revolut", "", "1 interest payment, 2026-01-01 to 2026-01-01"),
        ("Revolut", "", "2 fees, 2026-01-01 to 2026-01-01"),
    }


def test_lump_description_is_singular_for_a_single_row() -> None:
    roundup = _lump(count=1)
    fee = _lump(kind="fee", account="Safety", pocket=None, counterpart=None, count=1)

    rows = to_export_rows(ExportPlan(lumps=(roundup, fee)))

    assert sorted(r.description for r in rows) == [
        "1 fee, 2026-01-01 to 2026-01-01",
        "1 round-up, 2026-01-01 to 2026-01-01",
    ]


def test_lump_sorts_after_the_statement_rows_of_its_day() -> None:
    lump = _lump(day=date(2026, 1, 2))
    same_day = _row(line=7, date=datetime(2026, 1, 2, 23, 0))
    next_day = _row(line=1, date=datetime(2026, 1, 3))
    other_account = _row(account="A", line=9, date=datetime(2026, 1, 5))
    plan = ExportPlan(
        plain=tuple(_classified(row) for row in (next_day, same_day, other_account)),
        lumps=(lump,),
    )

    rows = to_export_rows(plan)

    assert [r.memo.split()[0] for r in rows] == [
        memo_tag(other_account),
        memo_tag(same_day),
        lump_tag(lump),
        memo_tag(next_day),
    ]


def test_lump_key_follows_the_documented_formula() -> None:
    material = "revolut|Main|roundups|Travel|Main"
    digest = hashlib.sha1(material.encode("utf-8"), usedforsecurity=False).hexdigest()

    assert lump_key("revolut", "Main", "roundups", "Travel", "Main") == digest[:8]
    assert (
        lump_key("revolut", "Main", "interest", None, "Main")
        == hashlib.sha1(b"revolut|Main|interest||Main", usedforsecurity=False).hexdigest()[:8]
    )


def test_lump_tag_follows_the_documented_formula() -> None:
    lump = _lump(day=date(2026, 1, 20), cutoff=datetime(2026, 1, 20, 9, 5, 7))
    material = "revolut|Main|roundups|Travel|Main|20260120T090507"
    digest = hashlib.sha1(material.encode("utf-8"), usedforsecurity=False).hexdigest()

    assert lump_tag(lump) == f"smt:{digest[:12]}"


def test_lump_tag_is_stable_and_differs_per_pocket_kind_and_cutoff() -> None:
    travel = _lump(pocket="Travel")
    home = _lump(pocket="Home", counterpart="Home")
    interest = _lump(kind="interest", pocket="Travel", counterpart=None)
    later = _lump(pocket="Travel", cutoff=datetime(2026, 1, 1, 10, 0, 1))

    assert lump_tag(travel) == lump_tag(_lump(pocket="Travel"))
    assert len({lump_tag(travel), lump_tag(home), lump_tag(interest), lump_tag(later)}) == 4


def test_lump_memo_holds_the_tag_the_key_and_the_cutoff() -> None:
    lump = _lump(cutoff=datetime(2026, 1, 20, 9, 5, 7))

    (exported,) = to_export_rows(ExportPlan(lumps=(lump,)))

    assert re.fullmatch(r"smt:[0-9a-f]{12} smt-lump:[0-9a-f]{8}:\d{8}T\d{6}", exported.memo)
    assert exported.memo == f"{lump_tag(lump)} smt-lump:{lump.key}:20260120T090507"


def test_lumps_of_two_statements_with_a_same_named_pocket_get_different_keys_and_tags() -> None:
    first = _lump(account="Travel", source_account="Main")
    second = _lump(account="Travel", source_account="Joint")

    assert first.key != second.key
    assert lump_tag(first) != lump_tag(second)
    rows = to_export_rows(ExportPlan(lumps=(first, second)))
    assert len({row.memo for row in rows}) == 2


def test_write_csv_writes_header_and_amounts_as_text(tmp_path: Path) -> None:
    rows = (
        ExportRow(
            date=datetime(2026, 1, 1).date(),
            amount=Decimal("-0.0072"),
            payee="Fund",
            description="Service Fee Charged",
            account="Safety",
            transfers="",
            memo="smt:0123456789ab",
        ),
        ExportRow(
            date=datetime(2026, 1, 2).date(),
            amount=Decimal("550.00"),
            payee="Alex",
            description="Payment",
            account="Shared",
            transfers="",
            memo="smt:abcdef012345",
        ),
    )
    path = tmp_path / "out.csv"

    write_csv(path, rows)

    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        lines = list(reader)

    assert lines[0] == COLUMNS
    assert lines[1][1] == "-0.0072"
    assert lines[2][1] == "550.00"
    assert "Category" not in lines[0]
    assert lines[1][6].startswith("smt:")
    assert lines[2][6].startswith("smt:")


def test_memo_tag_uses_canonical_amount() -> None:
    assert memo_tag(_row(amount=Decimal("-150"))) == memo_tag(_row(amount=Decimal("-150.00")))
