from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
import xlrd

from smoothment.money import parse_decimal, to_decimal


def xlsx_rows(path: Path) -> list[tuple[object, ...]]:
    """Every row of the first worksheet, with formulas evaluated to their cached values."""
    workbook = openpyxl.load_workbook(path, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        return list(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()


def xls_rows(path: Path) -> list[list[str]]:
    """Every row of the first sheet of a legacy BIFF workbook, each cell as text."""
    sheet = xlrd.open_workbook(path).sheet_by_index(0)
    rows: list[list[str]] = []
    for row_index in range(sheet.nrows):
        row: list[str] = []
        for value in sheet.row_values(row_index):
            if isinstance(value, float) and value.is_integer():
                row.append(str(int(value)))
            else:
                row.append(str(value))
        rows.append(row)
    return rows


def has_content(cells: Sequence[object]) -> bool:
    """True when at least one cell holds something other than None or blank text."""
    return any(cell is not None and str(cell).strip() for cell in cells)


def cell_decimal(value: object) -> Decimal:
    """Parse a spreadsheet cell holding an amount into an exact Decimal."""
    if isinstance(value, bool):
        raise ValueError(f"not a number: {value!r}")
    if isinstance(value, int | float):
        return to_decimal(value)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        text = value.strip()
        if "," in text and text.rfind(",") > text.rfind("."):
            return parse_decimal(text, decimal_sep=",", thousands_sep=".")
        return parse_decimal(text)
    raise ValueError(f"not a number: {value!r}")


def cell_date(value: object, fmt: str) -> datetime:
    """Parse a spreadsheet cell holding a date into a datetime."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        try:
            return datetime.strptime(value, fmt)
        except ValueError as exc:
            raise ValueError(f"not a date: {value!r}") from exc
    raise ValueError(f"not a date: {value!r}")
