import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from werkzeug.datastructures import FileStorage


MAX_IMPORT_SIZE = 10 * 1024 * 1024
MAX_IMPORT_ROWS = 5_000
IMPORT_PREVIEW_LIMIT = 100
IMPORT_FIELDS = ("date", "type", "category", "description", "amount")
REQUIRED_IMPORT_FIELDS = ("date", "category", "amount")
HEADER_ALIASES = {
    "date": {"date", "transactiondate", "transactionday"},
    "type": {"type", "transactiontype", "kind"},
    "category": {"category", "expensecategory", "transactioncategory"},
    "description": {
        "description",
        "details",
        "note",
        "notes",
        "memo",
        "merchant",
        "payee",
    },
    "amount": {"amount", "transactionamount", "value", "total"},
}
DATE_FORMATS = (
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%d-%b-%Y",
    "%b %d, %Y",
)


class ImportFileError(ValueError):
    pass


def _is_empty_row(row):
    return not any(value is not None and str(value).strip() for value in row)


def _column_label(value, index):
    if value is None or not str(value).strip():
        return f"Column {index + 1}"
    return str(value).strip()


def _read_csv(contents):
    try:
        reader = csv.reader(io.StringIO(contents.decode("utf-8-sig"), newline=""))
        rows = [(index, row) for index, row in enumerate(reader, start=1)]
    except (UnicodeDecodeError, csv.Error):
        raise ImportFileError("CSV file must be valid UTF-8 with a readable header row.") from None
    return rows


def _read_xlsx(contents):
    try:
        workbook = load_workbook(io.BytesIO(contents), read_only=True, data_only=True)
    except (BadZipFile, InvalidFileException, OSError, ValueError, ParseError, KeyError):
        raise ImportFileError("Excel file is not a valid .xlsx workbook.") from None
    try:
        if not workbook.worksheets:
            raise ImportFileError("Excel workbook does not contain a worksheet.")
        rows = []
        nonempty_count = 0
        for row_number, row in enumerate(
            workbook.worksheets[0].iter_rows(values_only=True), start=1
        ):
            if row_number > 20_000:
                raise ImportFileError("Excel worksheet may not exceed 20,000 rows.")
            values = list(row)
            if not _is_empty_row(values):
                nonempty_count += 1
                if nonempty_count > MAX_IMPORT_ROWS + 1:
                    raise ImportFileError(
                        f"Import files may contain at most {MAX_IMPORT_ROWS:,} rows."
                    )
                rows.append((row_number, values))
        return rows
    except ImportFileError:
        raise
    except (BadZipFile, InvalidFileException, OSError, ValueError, ParseError, KeyError):
        raise ImportFileError("Excel file is not a valid .xlsx workbook.") from None
    finally:
        workbook.close()


def read_import_file(uploaded_file: FileStorage):
    filename = uploaded_file.filename or ""
    extension = Path(filename).suffix.lower()
    if extension not in {".csv", ".xlsx"}:
        raise ImportFileError("Choose a .xlsx or .csv file.")

    contents = uploaded_file.stream.read(MAX_IMPORT_SIZE + 1)
    if len(contents) > MAX_IMPORT_SIZE:
        raise ImportFileError("Import files must be 10 MB or smaller.")
    if not contents:
        raise ImportFileError("The selected file is empty.")

    rows = _read_csv(contents) if extension == ".csv" else _read_xlsx(contents)
    header_position = next(
        (
            index
            for index, (_, row) in enumerate(rows)
            if not _is_empty_row(row)
        ),
        None,
    )
    if header_position is None:
        raise ImportFileError("The selected file does not contain a header row.")

    _, header = rows[header_position]
    headers = [_column_label(value, index) for index, value in enumerate(header)]
    data_rows = []
    for row_index, row in rows[header_position + 1 :]:
        if _is_empty_row(row):
            continue
        data_rows.append((row_index, row))
        if len(data_rows) > MAX_IMPORT_ROWS:
            raise ImportFileError(f"Import files may contain at most {MAX_IMPORT_ROWS:,} rows.")
    if not data_rows:
        raise ImportFileError("The selected file contains headers but no transaction rows.")
    return headers, data_rows


def _normalized_header(value):
    return re.sub(r"[^a-z0-9]", "", value.lower())


def resolve_column_mapping(headers, requested_mapping=None):
    if requested_mapping is not None and not isinstance(requested_mapping, dict):
        raise ImportFileError("Column mapping must be an object.")

    mapping = {}
    for field in IMPORT_FIELDS:
        if requested_mapping is not None and field in requested_mapping:
            value = requested_mapping[field]
            if value in (None, ""):
                mapping[field] = None
                continue
            if not isinstance(value, str) or not value.isdigit():
                raise ImportFileError(f"Invalid column mapping for {field}.")
            index = int(value)
            if index >= len(headers):
                raise ImportFileError(f"Invalid column mapping for {field}.")
            mapping[field] = index
            continue

        aliases = HEADER_ALIASES[field]
        mapping[field] = next(
            (
                index
                for index, header in enumerate(headers)
                if _normalized_header(header) in aliases
            ),
            None,
        )
    return mapping


def _cell_value(row, index):
    if index is None or index >= len(row):
        return None
    return row[index]


def _normalize_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError("date is required")
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        for date_format in DATE_FORMATS:
            try:
                return datetime.strptime(text, date_format).date().isoformat()
            except ValueError:
                continue
    raise ValueError("date must be a valid date")


def _normalize_amount(value):
    if value is None or isinstance(value, bool):
        raise ValueError("amount is required")
    text = str(value).strip().replace(",", "")
    if not text:
        raise ValueError("amount is required")
    for symbol in ("$", "€", "£", "¥"):
        if text.startswith(symbol):
            text = text[len(symbol) :].strip()
            break
    try:
        return str(Decimal(text))
    except (InvalidOperation, ValueError):
        raise ValueError("amount must be a valid number") from None


def row_to_payload(row, mapping):
    raw_type = _cell_value(row, mapping["type"])
    transaction_type = str(raw_type).strip().lower() if raw_type is not None else ""
    if not transaction_type:
        transaction_type = "expense"

    raw_category = _cell_value(row, mapping["category"])
    raw_description = _cell_value(row, mapping["description"])
    return {
        "date": _normalize_date(_cell_value(row, mapping["date"])),
        "type": transaction_type,
        "category": str(raw_category).strip() if raw_category is not None else "",
        "description": str(raw_description).strip() if raw_description is not None else "",
        "amount": _normalize_amount(_cell_value(row, mapping["amount"])),
    }
