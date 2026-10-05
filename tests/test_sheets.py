from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from smoothment.statement.sheets import cell_date, cell_decimal, xlsx_rows


def test_xlsx_rows_reads_only_first_sheet(tmp_path: Path) -> None:
    workbook = openpyxl.Workbook()
    first = workbook.active
    assert first is not None
    first.title = "First"
    first.append(["a", "b"])
    first.append([1, 2])
    second = workbook.create_sheet("Second")
    second.append(["x", "y"])
    path = tmp_path / "multi_sheet.xlsx"
    workbook.save(path)

    rows = xlsx_rows(path)

    assert rows == [("a", "b"), (1, 2)]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (550, Decimal("550.00")),
        (-545.58, Decimal("-545.58")),
        (Decimal("1.5"), Decimal("1.5")),
        ("-149.87", Decimal("-149.87")),
        ("0", Decimal("0")),
        ("1.234,56", Decimal("1234.56")),
        (" 56,85 ", Decimal("56.85")),
    ],
)
def test_cell_decimal_table(value: object, expected: Decimal) -> None:
    assert cell_decimal(value) == expected


@pytest.mark.parametrize("value", [None, True, "abc", object()])
def test_cell_decimal_rejects(value: object) -> None:
    with pytest.raises(ValueError, match="not a number"):
        cell_decimal(value)


def test_cell_date_text_month_day_year() -> None:
    assert cell_date("12/05/2025", "%m/%d/%Y") == datetime(2025, 12, 5)


def test_cell_date_text_day_month_year() -> None:
    assert cell_date("05/12/2025", "%d/%m/%Y") == datetime(2025, 12, 5)


def test_cell_date_datetime_passthrough() -> None:
    value = datetime(2026, 1, 2, 3, 4, 5)
    assert cell_date(value, "%m/%d/%Y") is value


def test_cell_date_date_becomes_midnight() -> None:
    assert cell_date(date(2026, 1, 2), "%m/%d/%Y") == datetime(2026, 1, 2, 0, 0, 0)


@pytest.mark.parametrize("value", [None, 5, "2026-09-04"])
def test_cell_date_rejects(value: object) -> None:
    with pytest.raises(ValueError):
        cell_date(value, "%m/%d/%Y")
