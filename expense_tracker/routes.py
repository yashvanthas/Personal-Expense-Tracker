import csv
import io
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import plotly
from flask import (
    Blueprint,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user
from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError

from expense_tracker import db
from expense_tracker.analytics import (
    category_summary,
    monthly_summary,
    period_summary,
    transaction_frame,
    trend_figure,
)
from expense_tracker.importing import (
    IMPORT_FIELDS,
    IMPORT_PREVIEW_LIMIT,
    REQUIRED_IMPORT_FIELDS,
    ImportFileError,
    read_import_file,
    resolve_column_mapping,
    row_to_payload,
)
from expense_tracker.models import Budget, Transaction

api = Blueprint("api", __name__)
TRANSACTION_TYPES = {"income", "expense"}
TRANSACTION_FIELDS = {"type", "amount", "category", "description", "date"}


class ValidationError(ValueError):
    pass


def _json_body():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object")
    unknown = set(payload) - TRANSACTION_FIELDS
    if unknown:
        raise ValidationError(f"Unknown field(s): {', '.join(sorted(unknown))}")
    return payload


def _validated_values(payload):
    values = {}
    if "type" in payload:
        transaction_type = payload["type"]
        if not isinstance(transaction_type, str) or transaction_type not in TRANSACTION_TYPES:
            raise ValidationError("type must be either 'income' or 'expense'")
        values["type"] = transaction_type

    if "amount" in payload:
        try:
            amount = Decimal(str(payload["amount"]))
        except (InvalidOperation, ValueError):
            raise ValidationError("amount must be a positive number") from None
        if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
            raise ValidationError("amount must be positive and have at most 2 decimal places")
        if amount >= Decimal("10000000000"):
            raise ValidationError("amount exceeds the supported maximum")
        values["amount"] = amount

    if "category" in payload:
        category = payload["category"]
        if not isinstance(category, str) or not category.strip():
            raise ValidationError("category must be a non-empty string")
        if len(category.strip()) > 80:
            raise ValidationError("category must be at most 80 characters")
        values["category"] = category.strip()

    if "description" in payload:
        description = payload["description"]
        if not isinstance(description, str):
            raise ValidationError("description must be a string")
        if len(description) > 500:
            raise ValidationError("description must be at most 500 characters")
        values["description"] = description

    if "date" in payload:
        date_value = payload["date"]
        if (
            not isinstance(date_value, str)
            or len(date_value) != 10
            or date_value[4] != "-"
            or date_value[7] != "-"
        ):
            raise ValidationError("date must use YYYY-MM-DD format") from None
        try:
            values["date"] = date.fromisoformat(date_value)
        except ValueError:
            raise ValidationError("date must use YYYY-MM-DD format") from None

    return values


def _date_parameter(name):
    value = request.args.get(name)
    if value is None:
        return None
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise ValidationError(f"{name} must use YYYY-MM-DD format")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationError(f"{name} must use YYYY-MM-DD format") from None


def _validated_month(value, field_name="month"):
    if (
        not isinstance(value, str)
        or len(value) != 7
        or value[4] != "-"
    ):
        raise ValidationError(f"{field_name} must use YYYY-MM format")
    try:
        date.fromisoformat(f"{value}-01")
    except ValueError:
        raise ValidationError(f"{field_name} must use YYYY-MM format") from None
    return value


def _month_parameter():
    return _validated_month(request.args.get("month", date.today().strftime("%Y-%m")))


def _month_date_bounds(month):
    first_day = date.fromisoformat(f"{month}-01")
    if first_day.month == 12:
        next_month = (
            date(first_day.year + 1, 1, 1)
            if first_day.year < date.max.year
            else None
        )
    else:
        next_month = date(first_day.year, first_day.month + 1, 1)
    return first_day, next_month


def _budget_values(payload, required_fields):
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object")
    unknown = set(payload) - {"month", "category", "amount"}
    if unknown:
        raise ValidationError(f"Unknown field(s): {', '.join(sorted(unknown))}")
    missing = required_fields - set(payload)
    if missing:
        raise ValidationError(f"Missing required field(s): {', '.join(sorted(missing))}")

    values = {}
    if "month" in payload:
        values["month"] = _validated_month(payload["month"])
    if "category" in payload:
        category = payload["category"]
        if not isinstance(category, str) or not category.strip():
            raise ValidationError("category must be a non-empty string")
        if len(category.strip()) > 80:
            raise ValidationError("category must be at most 80 characters")
        values["category"] = category.strip()
    if "amount" in payload:
        try:
            amount = Decimal(str(payload["amount"]))
        except (InvalidOperation, ValueError):
            raise ValidationError("amount must be a positive number") from None
        if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
            raise ValidationError("amount must be positive and have at most 2 decimal places")
        if amount >= Decimal("10000000000"):
            raise ValidationError("amount exceeds the supported maximum")
        values["amount"] = amount
    return values


def _filtered_transactions():
    query = Transaction.query.filter_by(user_id=current_user.id)
    transaction_type = request.args.get("type")
    if transaction_type:
        if transaction_type not in TRANSACTION_TYPES:
            raise ValidationError("type must be either 'income' or 'expense'")
        query = query.filter_by(type=transaction_type)

    category = request.args.get("category")
    if category:
        if len(category) > 80:
            raise ValidationError("category filter must be at most 80 characters")
        query = query.filter_by(category=category)

    search = request.args.get("search", "").strip()
    if len(search) > 100:
        raise ValidationError("search must be at most 100 characters")
    if search:
        escaped_search = search.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.filter(
            or_(
                func.lower(Transaction.category).contains(escaped_search, escape="\\"),
                func.lower(Transaction.description).contains(escaped_search, escape="\\"),
            )
        )

    start_date = _date_parameter("start_date")
    end_date = _date_parameter("end_date")
    if start_date and end_date and start_date > end_date:
        raise ValidationError("start_date must be on or before end_date")
    if start_date:
        query = query.filter(Transaction.date >= start_date)
    if end_date:
        query = query.filter(Transaction.date <= end_date)
    return query


def _csv_safe_text(value):
    value = str(value)
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def _commit():
    db.session.commit()


def _import_mapping_from_request():
    raw_mapping = request.form.get("mapping")
    if raw_mapping is None:
        return None
    try:
        mapping = json.loads(raw_mapping)
    except json.JSONDecodeError:
        raise ValidationError("Column mapping must be valid JSON.") from None
    if not isinstance(mapping, dict) or set(mapping) - set(IMPORT_FIELDS):
        raise ValidationError("Column mapping contains an unsupported field.")
    return mapping


def _import_duplicate_key(values):
    return (
        values["date"],
        values["type"].casefold(),
        Decimal(values["amount"]).quantize(Decimal("0.01")),
        values["category"].strip().casefold(),
        " ".join(values["description"].split()).casefold(),
    )


def _analyze_import(uploaded_file, requested_mapping):
    try:
        headers, data_rows = read_import_file(uploaded_file)
        mapping = resolve_column_mapping(headers, requested_mapping)
    except ImportFileError as error:
        raise ValidationError(str(error)) from None

    missing_fields = [
        field for field in REQUIRED_IMPORT_FIELDS if mapping[field] is None
    ]
    columns = [
        {"index": str(index), "label": header}
        for index, header in enumerate(headers)
    ]
    result = {
        "columns": columns,
        "mapping": {
            field: str(index) if index is not None else ""
            for field, index in mapping.items()
        },
        "missing_fields": missing_fields,
        "total": len(data_rows),
        "ready": 0,
        "invalid": 0,
        "duplicates": 0,
        "rows": [],
        "issues": [],
    }
    if missing_fields:
        return result, []

    analyzed_rows = []
    valid_records = []
    for row_number, raw_row in data_rows:
        try:
            values = _validated_values(row_to_payload(raw_row, mapping))
            if not {"date", "type", "amount", "category"}.issubset(values):
                raise ValidationError("A required transaction field is missing")
        except (ValidationError, ValueError) as error:
            analyzed_rows.append(
                {
                    "row": row_number,
                    "status": "invalid",
                    "error": str(error),
                }
            )
            result["invalid"] += 1
            continue
        valid_records.append((row_number, values))
        analyzed_rows.append(
            {
                "row": row_number,
                "status": "ready",
                "date": values["date"].isoformat(),
                "type": values["type"],
                "amount": str(values["amount"]),
                "category": values["category"],
                "description": values["description"],
            }
        )

    existing_keys = set()
    dates = sorted({values["date"] for _, values in valid_records})
    for start in range(0, len(dates), 500):
        date_batch = dates[start : start + 500]
        existing_rows = (
            db.session.query(
                Transaction.date,
                Transaction.type,
                Transaction.amount,
                Transaction.category,
                Transaction.description,
            )
            .filter(
                Transaction.user_id == current_user.id,
                Transaction.date.in_(date_batch),
            )
            .all()
        )
        for existing_row in existing_rows:
            existing_keys.add(
                _import_duplicate_key(
                    {
                        "date": existing_row.date,
                        "type": existing_row.type,
                        "amount": existing_row.amount,
                        "category": existing_row.category,
                        "description": existing_row.description,
                    }
                )
            )

    seen_keys = set()
    accepted_records = []
    row_results = {row["row"]: row for row in analyzed_rows}
    for row_number, values in valid_records:
        key = _import_duplicate_key(values)
        row_result = row_results[row_number]
        if key in existing_keys:
            row_result.update(
                status="duplicate",
                error="An identical transaction already exists in this account.",
            )
            result["duplicates"] += 1
        elif key in seen_keys:
            row_result.update(
                status="duplicate",
                error="An identical transaction appears earlier in this file.",
            )
            result["duplicates"] += 1
        else:
            seen_keys.add(key)
            accepted_records.append((row_number, values))
            result["ready"] += 1

    result["rows"] = analyzed_rows[:IMPORT_PREVIEW_LIMIT]
    result["issues"] = [
        {"row": row["row"], "status": row["status"], "error": row["error"]}
        for row in analyzed_rows
        if row["status"] in {"invalid", "duplicate"}
    ]
    result["can_import"] = bool(accepted_records)
    return result, [values for _, values in accepted_records]


@api.errorhandler(ValidationError)
def handle_validation_error(error):
    return jsonify({"error": str(error)}), 400


@api.before_request
def require_authenticated_user():
    if request.endpoint == "api.plotly_javascript":
        return None
    if current_user.is_authenticated:
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "Authentication required"}), 401
    return redirect(url_for("auth.login", next=request.path))


@api.get("/api/transactions")
def list_transactions():
    try:
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        raise ValidationError("limit and offset must be integers") from None
    if not 1 <= limit <= 500 or offset < 0:
        raise ValidationError("limit must be 1-500 and offset must be non-negative")

    items = _filtered_transactions().order_by(
        Transaction.date.desc(), Transaction.id.desc()
    )
    return jsonify(
        {
            "transactions": [
                transaction.to_dict()
                for transaction in items.offset(offset).limit(limit).all()
            ],
            "limit": limit,
            "offset": offset,
        }
    )


@api.get("/api/categories")
def list_categories():
    categories = (
        db.session.query(Transaction.category)
        .filter(Transaction.user_id == current_user.id)
        .distinct()
        .order_by(func.lower(Transaction.category), Transaction.category)
        .all()
    )
    return jsonify({"categories": [category for (category,) in categories]})


@api.post("/api/transactions/import/preview")
def preview_transaction_import():
    uploaded_file = request.files.get("file")
    if uploaded_file is None or not uploaded_file.filename:
        raise ValidationError("Choose a .xlsx or .csv file to preview.")
    try:
        result, _ = _analyze_import(uploaded_file, _import_mapping_from_request())
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"error": "Could not check for duplicate transactions."}), 500
    return jsonify(result)


@api.post("/api/transactions/import")
def import_transactions():
    uploaded_file = request.files.get("file")
    if uploaded_file is None or not uploaded_file.filename:
        raise ValidationError("Choose a .xlsx or .csv file to import.")
    try:
        result, accepted_records = _analyze_import(
            uploaded_file, _import_mapping_from_request()
        )
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"error": "Could not check for duplicate transactions."}), 500
    if result["missing_fields"]:
        names = ", ".join(result["missing_fields"])
        raise ValidationError(f"Map the required column(s) before importing: {names}.")
    if not accepted_records:
        return jsonify(
            {
                "imported": 0,
                "invalid": result["invalid"],
                "duplicates": result["duplicates"],
                "issues": result["issues"],
            }
        )

    try:
        db.session.add_all(
            [
                Transaction(user_id=current_user.id, **values)
                for values in accepted_records
            ]
        )
        _commit()
    except SQLAlchemyError:
        db.session.rollback()
        return (
            jsonify(
                {
                    "error": (
                        "Could not import transactions because the database write "
                        "failed. No records were imported."
                    )
                }
            ),
            500,
        )
    return jsonify(
        {
            "imported": len(accepted_records),
            "invalid": result["invalid"],
            "duplicates": result["duplicates"],
            "issues": result["issues"],
        }
    )


@api.get("/api/transactions/export.csv")
def export_transactions():
    transactions = _filtered_transactions().order_by(
        Transaction.date.desc(), Transaction.id.desc()
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Date", "Type", "Category", "Description", "Amount"])
    for transaction in transactions:
        writer.writerow(
            [
                transaction.date.isoformat(),
                transaction.type,
                _csv_safe_text(transaction.category),
                _csv_safe_text(transaction.description),
                f"{transaction.amount:.2f}",
            ]
        )

    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = (
        'attachment; filename="expense-tracker-transactions.csv"'
    )
    return response


@api.get("/api/backup")
def download_backup():
    payload = {
        "format": "expense-tracker-backup",
        "version": 1,
        "transactions": [
            {
                "type": transaction.type,
                "amount": str(transaction.amount),
                "category": transaction.category,
                "description": transaction.description,
                "date": transaction.date.isoformat(),
            }
            for transaction in Transaction.query.filter_by(user_id=current_user.id)
            .order_by(Transaction.date, Transaction.id)
            .all()
        ],
        "budgets": [
            {
                "month": budget.month,
                "category": budget.category,
                "amount": str(budget.amount),
            }
            for budget in Budget.query.filter_by(user_id=current_user.id)
            .order_by(Budget.month, Budget.category)
            .all()
        ],
    }
    response = make_response(json.dumps(payload, indent=2))
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    response.headers["Content-Disposition"] = (
        'attachment; filename="expense-tracker-backup.json"'
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@api.post("/api/backup/restore")
def restore_backup():
    uploaded_file = request.files.get("backup")
    if uploaded_file is None or not uploaded_file.filename:
        raise ValidationError("Choose an Expense Tracker JSON backup file to restore")
    if request.content_length and request.content_length > 100 * 1024 * 1024:
        raise ValidationError("Backup file must be 100 MB or smaller")

    try:
        payload = json.load(uploaded_file.stream)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValidationError("Backup file must contain valid JSON") from None
    if not isinstance(payload, dict) or payload.get("format") != "expense-tracker-backup" or payload.get("version") != 1:
        raise ValidationError("Backup file format or version is not supported")
    transactions = payload.get("transactions")
    budgets = payload.get("budgets")
    if not isinstance(transactions, list) or not isinstance(budgets, list):
        raise ValidationError("Backup must include transactions and budgets lists")
    if len(transactions) > 100_000 or len(budgets) > 100_000:
        raise ValidationError("Backup contains too many records")

    transaction_values = []
    for row in transactions:
        if not isinstance(row, dict) or set(row) != TRANSACTION_FIELDS:
            raise ValidationError("Backup contains an invalid transaction record")
        values = _validated_values(row)
        if "type" not in values or "amount" not in values or "category" not in values or "date" not in values:
            raise ValidationError("Backup transaction is missing a required field")
        transaction_values.append(values)

    budget_values = []
    seen_budgets = set()
    for row in budgets:
        values = _budget_values(row, {"month", "category", "amount"})
        key = (values["month"], values["category"])
        if key in seen_budgets:
            raise ValidationError("Backup contains duplicate month/category budgets")
        seen_budgets.add(key)
        budget_values.append(values)

    db.session.query(Transaction).filter_by(user_id=current_user.id).delete(
        synchronize_session=False
    )
    db.session.query(Budget).filter_by(user_id=current_user.id).delete(
        synchronize_session=False
    )
    db.session.add_all(
        [Transaction(user_id=current_user.id, **values) for values in transaction_values]
    )
    db.session.add_all(
        [Budget(user_id=current_user.id, **values) for values in budget_values]
    )
    _commit()
    return jsonify(
        {
            "status": "restored",
            "transactions": len(transaction_values),
            "budgets": len(budget_values),
        }
    )


@api.get("/api/transactions/export-preview")
def preview_export():
    try:
        offset = int(request.args.get("offset", 0))
    except ValueError:
        raise ValidationError("offset must be a non-negative integer") from None
    if offset < 0:
        raise ValidationError("offset must be a non-negative integer")

    query = _filtered_transactions().order_by(
        Transaction.date.desc(), Transaction.id.desc()
    )
    transactions = query.offset(offset).limit(50).all()
    return jsonify(
        {
            "transactions": [
                {
                    "date": transaction.date.isoformat(),
                    "type": transaction.type,
                    "category": _csv_safe_text(transaction.category),
                    "description": _csv_safe_text(transaction.description),
                    "amount": f"{transaction.amount:.2f}",
                }
                for transaction in transactions
            ],
            "total": query.order_by(None).count(),
            "limit": 50,
            "offset": offset,
        }
    )


@api.post("/api/transactions")
def create_transaction():
    payload = _json_body()
    required = {"type", "amount", "category"}
    missing = required - set(payload)
    if missing:
        raise ValidationError(f"Missing required field(s): {', '.join(sorted(missing))}")
    values = _validated_values(payload)
    transaction = Transaction(user_id=current_user.id, **values)
    db.session.add(transaction)
    _commit()
    return jsonify({"transaction": transaction.to_dict()}), 201


@api.get("/api/transactions/<int:transaction_id>")
def get_transaction(transaction_id):
    transaction = db.session.get(Transaction, transaction_id)
    if transaction is None or transaction.user_id != current_user.id:
        return jsonify({"error": "Transaction not found"}), 404
    return jsonify({"transaction": transaction.to_dict()})


@api.route("/api/transactions/<int:transaction_id>", methods=["PUT", "PATCH"])
def update_transaction(transaction_id):
    transaction = db.session.get(Transaction, transaction_id)
    if transaction is None or transaction.user_id != current_user.id:
        return jsonify({"error": "Transaction not found"}), 404

    payload = _json_body()
    if not payload:
        raise ValidationError("At least one field is required")
    if request.method == "PUT":
        required = {"type", "amount", "category", "date"}
        missing = required - set(payload)
        if missing:
            raise ValidationError(f"PUT requires: {', '.join(sorted(missing))}")

    for field, value in _validated_values(payload).items():
        setattr(transaction, field, value)
    _commit()
    return jsonify({"transaction": transaction.to_dict()})


@api.delete("/api/transactions/<int:transaction_id>")
def delete_transaction(transaction_id):
    transaction = db.session.get(Transaction, transaction_id)
    if transaction is None or transaction.user_id != current_user.id:
        return jsonify({"error": "Transaction not found"}), 404
    db.session.delete(transaction)
    _commit()
    return "", 204


@api.get("/api/budgets")
def list_budgets():
    month = _month_parameter()
    start_date, next_month = _month_date_bounds(month)
    budgets = (
        Budget.query.filter_by(user_id=current_user.id, month=month)
        .order_by(Budget.category)
        .all()
    )
    spending_query = (
        db.session.query(Transaction.category, func.sum(Transaction.amount))
        .filter(
            Transaction.user_id == current_user.id,
            Transaction.type == "expense",
            Transaction.date >= start_date,
        )
    )
    if next_month:
        spending_query = spending_query.filter(Transaction.date < next_month)
    spending = spending_query.group_by(Transaction.category).all()
    spent_by_category = {category: Decimal(total) for category, total in spending}
    results = []
    for budget in budgets:
        limit = Decimal(budget.amount)
        spent = spent_by_category.get(budget.category, Decimal("0"))
        percentage = float(spent / limit * 100)
        results.append(
            {
                "id": budget.id,
                "month": budget.month,
                "category": budget.category,
                "amount": float(limit),
                "spent": float(spent),
                "remaining": float(limit - spent),
                "percentage": round(percentage, 2),
                "status": "over" if spent >= limit else "warning" if percentage >= 80 else "on_track",
            }
        )
    return jsonify({"month": month, "budgets": results})


@api.post("/api/budgets")
def save_budget():
    payload = request.get_json(silent=True)
    values = _budget_values(payload, {"month", "category", "amount"})
    budget = Budget.query.filter_by(
        user_id=current_user.id,
        month=values["month"],
        category=values["category"],
    ).first()
    if budget is None:
        budget = Budget(user_id=current_user.id, **values)
        db.session.add(budget)
    else:
        budget.amount = values["amount"]
    _commit()
    return jsonify(
        {
            "budget": {
                "id": budget.id,
                "month": budget.month,
                "category": budget.category,
                "amount": float(budget.amount),
            }
        }
    ), 200


@api.delete("/api/budgets/<int:budget_id>")
def delete_budget(budget_id):
    budget = db.session.get(Budget, budget_id)
    if budget is None or budget.user_id != current_user.id:
        return jsonify({"error": "Budget not found"}), 404
    db.session.delete(budget)
    _commit()
    return "", 204


@api.get("/api/analytics/monthly")
def monthly_analytics():
    start_date = _date_parameter("start_date")
    end_date = _date_parameter("end_date")
    if start_date and end_date and start_date > end_date:
        raise ValidationError("start_date must be on or before end_date")
    return jsonify(
        {
            "monthly": monthly_summary(
                transaction_frame(current_user.id, start_date, end_date)
            )
        }
    )


@api.get("/api/analytics/period")
def period_analytics():
    start_date = _date_parameter("start_date")
    end_date = _date_parameter("end_date")
    if start_date and end_date and start_date > end_date:
        raise ValidationError("start_date must be on or before end_date")
    frame = transaction_frame(current_user.id, start_date, end_date)
    return jsonify({"summary": period_summary(frame, start_date, end_date)})


@api.get("/api/analytics/categories")
def category_analytics():
    start_date = _date_parameter("start_date")
    end_date = _date_parameter("end_date")
    if start_date and end_date and start_date > end_date:
        raise ValidationError("start_date must be on or before end_date")
    return jsonify(
        {
            "categories": category_summary(
                transaction_frame(current_user.id, start_date, end_date)
            )
        }
    )


@api.get("/api/analytics/trends")
def trend_analytics():
    start_date = _date_parameter("start_date")
    end_date = _date_parameter("end_date")
    if start_date and end_date and start_date > end_date:
        raise ValidationError("start_date must be on or before end_date")
    summary = monthly_summary(
        transaction_frame(current_user.id, start_date, end_date)
    )
    return jsonify({"monthly": summary, "chart": json.loads(trend_figure(summary).to_json())})


@api.get("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@api.get("/vendor/plotly.min.js")
def plotly_javascript():
    bundle_path = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
    return send_file(
        bundle_path,
        mimetype="application/javascript",
        conditional=True,
        max_age=3600,
    )
