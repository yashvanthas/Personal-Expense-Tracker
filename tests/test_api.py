import csv
import io
import json
import re
import sqlite3
from datetime import date

import pytest
from openpyxl import Workbook
from sqlalchemy.exc import SQLAlchemyError

from expense_tracker import create_app, db
from expense_tracker.models import Budget, Transaction, User


@pytest.fixture
def client(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
            "WTF_CSRF_ENABLED": False,
        }
    )
    with app.app_context():
        db.create_all()
        user = User(email="owner@example.com")
        user.set_password("test-password-123")
        db.session.add(user)
        db.session.commit()
    test_client = app.test_client()
    test_client.post(
        "/login",
        data={"email": "owner@example.com", "password": "test-password-123"},
    )
    yield test_client
    with app.app_context():
        db.drop_all()


def create_transaction(client, **overrides):
    payload = {
        "type": "expense",
        "amount": 24.5,
        "category": "Food",
        "date": "2026-03-15",
        "description": "Lunch",
    }
    payload.update(overrides)
    return client.post("/api/transactions", json=payload)


def post_import(client, path, filename, contents, mapping=None):
    data = {"file": (io.BytesIO(contents), filename)}
    if mapping is not None:
        data["mapping"] = json.dumps(mapping)
    return client.post(path, data=data, content_type="multipart/form-data")


def test_transaction_crud(client):
    created = create_transaction(client)
    assert created.status_code == 201
    transaction = created.json["transaction"]
    transaction_id = transaction["id"]
    assert transaction["amount"] == 24.5

    fetched = client.get(f"/api/transactions/{transaction_id}")
    assert fetched.status_code == 200
    assert fetched.json["transaction"]["category"] == "Food"

    updated = client.patch(
        f"/api/transactions/{transaction_id}", json={"category": "Dining"}
    )
    assert updated.status_code == 200
    assert updated.json["transaction"]["category"] == "Dining"

    deleted = client.delete(f"/api/transactions/{transaction_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/transactions/{transaction_id}").status_code == 404


def test_validation_and_filters(client):
    assert create_transaction(client, amount=-2).status_code == 400
    assert create_transaction(client, type="transfer").status_code == 400
    assert create_transaction(client, date="20260315").status_code == 400
    create_transaction(client)
    create_transaction(
        client,
        type="income",
        amount=100,
        category="Salary",
        date="2026-04-02",
    )

    response = client.get("/api/transactions?type=income&start_date=2026-04-01")
    assert response.status_code == 200
    assert len(response.json["transactions"]) == 1
    assert response.json["transactions"][0]["category"] == "Salary"


def test_search_category_filter_and_category_options(client):
    create_transaction(client, category="Food", description="Coffee and pastry")
    create_transaction(client, category="Transport", description="Bus pass")
    create_transaction(client, category="Food", description="Weekly groceries")

    searched = client.get("/api/transactions?search=COFFEE")
    assert searched.status_code == 200
    assert len(searched.json["transactions"]) == 1
    assert searched.json["transactions"][0]["description"] == "Coffee and pastry"

    combined = client.get("/api/transactions?search=food&category=Food")
    assert combined.status_code == 200
    assert len(combined.json["transactions"]) == 2
    assert client.get("/api/transactions?search=%25").json["transactions"] == []
    assert client.get(f"/api/transactions?search={'x' * 101}").status_code == 400
    assert client.get("/api/transactions?category=" + "x" * 81).status_code == 400
    assert client.get("/api/categories").json["categories"] == ["Food", "Transport"]


def test_csv_export_respects_filters_and_is_spreadsheet_safe(client):
    create_transaction(client, category="=2+2", description="@SUM(A1:A2)")
    create_transaction(
        client,
        type="income",
        amount=100,
        category="Salary",
        date="2026-04-02",
    )

    response = client.get(
        "/api/transactions/export.csv?type=expense&start_date=2026-03-01&search=SUM"
    )
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment;" in response.headers["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(response.get_data(as_text=True).lstrip("\ufeff"))))
    assert rows == [
        ["Date", "Type", "Category", "Description", "Amount"],
        ["2026-03-15", "expense", "'=2+2", "'@SUM(A1:A2)", "24.50"],
    ]
    assert client.get(
        "/api/transactions/export.csv?start_date=2026-05-01&end_date=2026-04-01"
    ).status_code == 400
    preview = client.get("/api/transactions/export-preview?search=SUM")
    assert preview.status_code == 200
    assert preview.json["total"] == 1


def test_csv_export_preview_uses_filters_and_pages_results(client):
    for index in range(52):
        create_transaction(client, description=f"Meal {index}")
    create_transaction(client, type="income", amount=100, category="Salary")

    first_page = client.get("/api/transactions/export-preview?type=expense")
    assert first_page.status_code == 200
    assert first_page.json["total"] == 52
    assert first_page.json["limit"] == 50
    assert first_page.json["offset"] == 0
    assert len(first_page.json["transactions"]) == 50

    last_page = client.get("/api/transactions/export-preview?type=expense&offset=50")
    assert last_page.status_code == 200
    assert len(last_page.json["transactions"]) == 2
    assert client.get("/api/transactions/export-preview?offset=-1").status_code == 400


def test_monthly_category_budgets_include_spending_and_alerts(client):
    create_transaction(client, amount=80, category="Food", date="2026-03-05")
    create_transaction(client, amount=25, category="Food", date="2026-03-20")
    create_transaction(client, amount=900, category="Food", date="2026-04-01")
    create_transaction(
        client,
        type="income",
        amount=500,
        category="Food",
        date="2026-03-10",
    )

    created = client.post(
        "/api/budgets",
        json={"month": "2026-03", "category": "Food", "amount": 100},
    )
    assert created.status_code == 200
    budget_id = created.json["budget"]["id"]
    assert created.json["budget"]["amount"] == 100

    march = client.get("/api/budgets?month=2026-03")
    assert march.status_code == 200
    assert march.json["budgets"] == [
        {
            "id": budget_id,
            "month": "2026-03",
            "category": "Food",
            "amount": 100,
            "spent": 105,
            "remaining": -5,
            "percentage": 105,
            "status": "over",
        }
    ]
    assert client.get("/api/budgets?month=2026-04").json["budgets"] == []

    updated = client.post(
        "/api/budgets",
        json={"month": "2026-03", "category": "Food", "amount": 200},
    )
    assert updated.json["budget"]["id"] == budget_id
    assert len(client.get("/api/budgets?month=2026-03").json["budgets"]) == 1
    assert client.delete(f"/api/budgets/{budget_id}").status_code == 204
    assert client.delete(f"/api/budgets/{budget_id}").status_code == 404


def test_budget_validation(client):
    assert client.post(
        "/api/budgets",
        json={"month": "2026-13", "category": "Food", "amount": 100},
    ).status_code == 400
    assert client.post(
        "/api/budgets",
        json={"month": "2026-03", "category": "Food", "amount": 0},
    ).status_code == 400
    assert client.get("/api/budgets?month=202603").status_code == 400


def test_budget_december_9999_does_not_overflow(client):
    create_transaction(client, amount=25, category="Food", date="9999-12-31")
    created = client.post(
        "/api/budgets",
        json={"month": "9999-12", "category": "Food", "amount": 100},
    )
    assert created.status_code == 200
    response = client.get("/api/budgets?month=9999-12")
    assert response.status_code == 200
    assert response.json["budgets"][0]["spent"] == 25


def test_analytics_and_plotly_dashboard(client):
    create_transaction(client)
    create_transaction(
        client,
        type="income",
        amount=2000,
        category="Salary",
        date="2026-03-01",
    )
    create_transaction(client, amount=10, category="Food", date="2026-03-20")

    monthly = client.get("/api/analytics/monthly").json["monthly"]
    assert monthly == [
        {"month": "2026-03", "income": 2000.0, "expenses": 34.5, "net": 1965.5}
    ]
    categories = client.get("/api/analytics/categories").json["categories"]
    assert categories == [{"category": "Food", "amount": 34.5}]

    trends = client.get("/api/analytics/trends")
    assert trends.status_code == 200
    assert len(trends.json["chart"]["data"]) == 2
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert b"Transaction overview" in dashboard.data
    assert b"Spending overview" in dashboard.data
    assert b"Add transaction" in dashboard.data
    assert b"Expense breakdown" in dashboard.data
    assert b"Monthly budgets" in dashboard.data
    assert b"Account backup" in dashboard.data
    assert b"Restore backup" in dashboard.data
    assert b"Category or description" in dashboard.data
    assert b"Preview export" in dashboard.data
    assert b"Download CSV" in dashboard.data
    assert b"/vendor/plotly.min.js" in dashboard.data
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200
    plotly_bundle = client.get("/vendor/plotly.min.js")
    assert plotly_bundle.status_code == 200
    assert plotly_bundle.mimetype == "application/javascript"
    assert len(plotly_bundle.data) > 1_000_000


def test_period_analytics_summary_and_date_boundaries(client):
    create_transaction(client, amount=40, category="Food", date="2026-03-01")
    create_transaction(client, amount=60, category="Food", date="2026-03-03")
    create_transaction(
        client,
        type="income",
        amount=500,
        category="Salary",
        date="2026-03-02",
    )
    create_transaction(client, amount=200, category="Rent", date="2026-04-01")

    response = client.get(
        "/api/analytics/period?start_date=2026-03-01&end_date=2026-03-05"
    )
    assert response.status_code == 200
    assert response.json["summary"] == {
        "start_date": "2026-03-01",
        "end_date": "2026-03-05",
        "days": 5,
        "transaction_count": 3,
        "income": 500,
        "expenses": 100,
        "net": 400,
        "average_daily_expenses": 20,
        "top_expense_category": {"category": "Food", "amount": 100},
    }

    all_dates = client.get("/api/analytics/period").json["summary"]
    assert all_dates["start_date"] == "2026-03-01"
    assert all_dates["end_date"] == "2026-04-01"
    assert all_dates["days"] == 32
    assert client.get(
        "/api/analytics/period?start_date=2026-04-01&end_date=2026-03-01"
    ).status_code == 400


def test_period_analytics_empty_data(client):
    summary = client.get("/api/analytics/period").json["summary"]
    assert summary == {
        "start_date": None,
        "end_date": None,
        "days": 0,
        "transaction_count": 0,
        "income": 0,
        "expenses": 0,
        "net": 0,
        "average_daily_expenses": 0,
        "top_expense_category": None,
    }


def test_backup_download_and_restore(client):
    create_transaction(client, amount=42.5, category="Food")
    client.post(
        "/api/budgets",
        json={"month": "2026-03", "category": "Food", "amount": 100},
    )

    backup = client.get("/api/backup")
    assert backup.status_code == 200
    assert backup.mimetype == "application/json"
    assert "attachment;" in backup.headers["Content-Disposition"]
    backup_data = backup.data
    payload = json.loads(backup_data)
    assert payload["format"] == "expense-tracker-backup"
    assert len(payload["transactions"]) == 1
    assert len(payload["budgets"]) == 1

    create_transaction(client, amount=9, category="Transport")
    response = client.post(
        "/api/backup/restore",
        data={"backup": (io.BytesIO(backup_data), "expense-tracker-backup.json")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert response.json == {"status": "restored", "transactions": 1, "budgets": 1}
    transactions = client.get("/api/transactions").json["transactions"]
    assert len(transactions) == 1
    assert transactions[0]["category"] == "Food"
    assert len(client.get("/api/budgets?month=2026-03").json["budgets"]) == 1


def test_invalid_backup_does_not_change_live_database(client):
    create_transaction(client, category="Food")

    invalid = client.post(
        "/api/backup/restore",
        data={"backup": (io.BytesIO(b"not json"), "invalid.json")},
        content_type="multipart/form-data",
    )
    assert invalid.status_code == 400
    assert "json" in invalid.json["error"].lower()
    transactions = client.get("/api/transactions").json["transactions"]
    assert len(transactions) == 1
    assert transactions[0]["category"] == "Food"

    missing = client.post("/api/backup/restore", data={}, content_type="multipart/form-data")
    assert missing.status_code == 400


def test_authentication_and_account_data_isolation(client):
    create_transaction(client, category="Private Food")
    owner_transaction_id = client.get("/api/transactions").json["transactions"][0]["id"]
    client.post(
        "/api/budgets",
        json={"month": "2026-03", "category": "Private Food", "amount": 100},
    )

    app = client.application
    with app.app_context():
        other_user = User(email="other@example.com")
        other_user.set_password("other-password-123")
        db.session.add(other_user)
        db.session.commit()
        other_transaction = Transaction(
            user_id=other_user.id,
            type="expense",
            amount=55,
            category="Other Food",
            date=date(2026, 3, 10),
        )
        other_budget = Budget(
            user_id=other_user.id,
            month="2026-03",
            category="Other Food",
            amount=80,
        )
        db.session.add_all([other_transaction, other_budget])
        db.session.commit()
        other_transaction_id = other_transaction.id
        owner_budget_id = Budget.query.filter_by(user_id=1).one().id

    owner_backup = client.get("/api/backup").data
    with app.test_client() as other_client:
        other_client.post(
            "/login",
            data={"email": "other@example.com", "password": "other-password-123"},
        )
        assert other_client.get("/api/transactions").json["transactions"][0]["category"] == "Other Food"
        assert other_client.get(f"/api/transactions/{owner_transaction_id}").status_code == 404
        assert other_client.patch(
            f"/api/transactions/{owner_transaction_id}", json={"category": "Stolen"}
        ).status_code == 404
        assert other_client.delete(f"/api/transactions/{owner_transaction_id}").status_code == 404
        assert other_client.get("/api/categories").json["categories"] == ["Other Food"]
        assert other_client.get("/api/analytics/period").json["summary"]["expenses"] == 55
        assert other_client.get("/api/budgets?month=2026-03").json["budgets"][0]["category"] == "Other Food"
        assert other_client.delete(f"/api/budgets/{owner_budget_id}").status_code == 404
        assert other_client.get("/api/backup").json["transactions"][0]["category"] == "Other Food"
        restored = other_client.post(
            "/api/backup/restore",
            data={"backup": (io.BytesIO(owner_backup), "owner-backup.json")},
            content_type="multipart/form-data",
        )
        assert restored.status_code == 200
        assert other_client.get("/api/transactions").json["transactions"][0]["category"] == "Private Food"

    assert client.get(f"/api/transactions/{other_transaction_id}").status_code == 404
    assert client.get("/api/transactions").json["transactions"][0]["category"] == "Private Food"
    assert client.get("/api/analytics/period").json["summary"]["expenses"] == 24.5


def test_unauthenticated_routes_require_login(client):
    with client.application.test_client() as anonymous:
        response = anonymous.get("/api/transactions")
        assert response.status_code == 401
        assert response.json == {"error": "Authentication required"}
        assert anonymous.get("/dashboard").status_code == 302
        assert anonymous.get("/dashboard").headers["Location"].endswith("/login?next=/dashboard")


def test_registration_enforces_password_and_login(client):
    app = client.application
    with app.test_client() as anonymous:
        register_page = anonymous.get("/register")
        token = re.search(rb'name="csrf_token" value="([^"]+)"', register_page.data).group(1).decode()
        weak_password = anonymous.post(
            "/register",
            data={"email": "new@example.com", "password": "short"},
            headers={"X-CSRFToken": token},
        )
        assert weak_password.status_code == 200
        assert b"Password must be 12-128 characters" in weak_password.data

        token = re.search(rb'name="csrf_token" value="([^"]+)"', weak_password.data).group(1).decode()
        registered = anonymous.post(
            "/register",
            data={"email": "New@example.com", "password": "strong-password-123"},
            headers={"X-CSRFToken": token},
        )
        assert registered.status_code == 302
        assert registered.headers["Location"].endswith("/dashboard")
        assert anonymous.get("/api/transactions").json["transactions"] == []


def test_legacy_import_cli_preserves_existing_database(tmp_path):
    source = tmp_path / "legacy.sqlite"
    with sqlite3.connect(source) as legacy:
        legacy.executescript(
            'CREATE TABLE "transaction" (id INTEGER PRIMARY KEY, type TEXT, amount NUMERIC, '
            'category TEXT, description TEXT, date DATE, created_at DATETIME);'
            "CREATE TABLE budget (id INTEGER PRIMARY KEY, month TEXT, category TEXT, amount NUMERIC, "
            "CONSTRAINT uq_budget_month_category UNIQUE (month, category));"
            """INSERT INTO "transaction" VALUES
                (1, 'expense', 19.50, 'Groceries', 'Market', '2026-03-05', '2026-03-05 12:00:00');"""
            "INSERT INTO budget VALUES (1, '2026-03', 'Groceries', 200);"
        )

    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'target.db'}",
            "WTF_CSRF_ENABLED": False,
        }
    )
    with app.app_context():
        db.create_all()
        user = User(email="import@example.com")
        user.set_password("import-password-123")
        db.session.add(user)
        db.session.commit()
    result = app.test_cli_runner().invoke(
        args=["import-legacy-data", "--email", "import@example.com", "--source", str(source)]
    )
    assert result.exit_code == 0, result.output
    assert "Imported 1 transactions and 1 budgets" in result.output
    with app.app_context():
        transaction = Transaction.query.one()
        budget = Budget.query.one()
        assert transaction.user_id == 1
        assert transaction.category == "Groceries"
        assert transaction.description == "Market"
        assert budget.user_id == 1
        assert budget.amount == 200
        db.drop_all()


def test_legacy_import_can_read_and_write_the_same_sqlite_database(tmp_path):
    database_path = tmp_path / "existing-expenses.db"
    with sqlite3.connect(database_path) as legacy:
        legacy.executescript(
            'CREATE TABLE "transaction" (id INTEGER PRIMARY KEY, type TEXT, amount NUMERIC, '
            'category TEXT, description TEXT, date DATE, created_at DATETIME);'
            "CREATE TABLE budget (id INTEGER PRIMARY KEY, month TEXT, category TEXT, amount NUMERIC, "
            "CONSTRAINT uq_budget_month_category UNIQUE (month, category));"
            """INSERT INTO "transaction" VALUES
                (1, 'expense', 19.50, 'Groceries', 'Market', '2026-03-05', '2026-03-05 12:00:00');"""
            "INSERT INTO budget VALUES (1, '2026-03', 'Groceries', 200);"
        )

    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
            "WTF_CSRF_ENABLED": False,
        }
    )
    migration = app.test_cli_runner().invoke(args=["db", "upgrade"])
    assert migration.exit_code == 0, migration.output
    with app.test_client() as client:
        response = client.get("/api/transactions")
        assert response.status_code == 401
    with app.app_context():
        existing_user = User(email="existing@example.com")
        existing_user.set_password("existing-password")
        destination_user = User(email="same-db@example.com")
        destination_user.set_password("same-database-password")
        db.session.add_all([existing_user, destination_user])
        db.session.flush()
        db.session.add(
            Transaction(
                user_id=existing_user.id,
                type="expense",
                amount=75,
                category="Private",
                date=date(2026, 3, 6),
            )
        )
        db.session.add(
            Budget(
                user_id=existing_user.id,
                month="2026-03",
                category="Private",
                amount=100,
            )
        )
        db.session.commit()

    result = app.test_cli_runner().invoke(
        args=[
            "import-legacy-data",
            "--email",
            "same-db@example.com",
            "--source",
            str(database_path),
        ]
    )
    assert result.exit_code == 0, result.output
    with app.app_context():
        existing_user = User.query.filter_by(email="existing@example.com").one()
        destination_user = User.query.filter_by(email="same-db@example.com").one()
        assert (
            Transaction.query.filter_by(user_id=existing_user.id).one().category
            == "Private"
        )
        destination_transactions = Transaction.query.filter_by(
            user_id=destination_user.id
        ).all()
        assert len(destination_transactions) == 1
        assert destination_transactions[0].category == "Groceries"
        assert Budget.query.filter_by(user_id=existing_user.id).one().category == "Private"
        assert Budget.query.filter_by(user_id=destination_user.id).one().category == "Groceries"


def test_security_headers_and_csrf_protection(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'csrf.db'}",
            "WTF_CSRF_ENABLED": True,
        }
    )
    with app.app_context():
        db.create_all()
        user = User(email="csrf@example.com")
        user.set_password("csrf-password-123")
        db.session.add(user)
        db.session.commit()

    with app.test_client() as csrf_client:
        login_page = csrf_client.get("/login")
        token = re.search(rb'name="csrf_token" value="([^"]+)"', login_page.data).group(1).decode()
        csrf_client.post(
            "/login",
            data={"email": "csrf@example.com", "password": "csrf-password-123"},
            headers={"X-CSRFToken": token},
        )
        missing_token = csrf_client.post(
            "/api/transactions",
            json={"type": "expense", "amount": 5, "category": "Food"},
        )
        assert missing_token.status_code == 400
        accepted = csrf_client.post(
            "/api/transactions",
            json={"type": "expense", "amount": 5, "category": "Food"},
            headers={"X-CSRFToken": token},
        )
        assert accepted.status_code == 201
        assert accepted.headers["X-Frame-Options"] == "DENY"
        assert accepted.headers["X-Content-Type-Options"] == "nosniff"

    with app.app_context():
        db.drop_all()


def test_csv_import_preview_validates_rows_and_skips_duplicates(client):
    create_transaction(client)
    contents = (
        "Date,Type,Category,Description,Amount\n"
        "2026-03-15,expense,Food,Lunch,24.50\n"
        "2026-03-16,expense,Transit,Bus pass,2.50\n"
        "2026-03-16,expense,Transit,Bus pass,2.50\n"
        "not-a-date,expense,Food,Invalid,not-money\n"
        "2026-03-17,expense,Food,Invalid amount,not-money\n"
    ).encode()

    preview = post_import(
        client, "/api/transactions/import/preview", "expenses.csv", contents
    )
    assert preview.status_code == 200
    assert preview.json["ready"] == 1
    assert preview.json["duplicates"] == 2
    assert preview.json["invalid"] == 2
    assert preview.json["rows"][2]["status"] == "duplicate"
    assert [issue["row"] for issue in preview.json["issues"]] == [2, 4, 5, 6]
    assert "amount" in preview.json["issues"][-1]["error"]
    assert len(client.get("/api/transactions").json["transactions"]) == 1

    imported = post_import(
        client, "/api/transactions/import", "expenses.csv", contents
    )
    assert imported.status_code == 200
    assert imported.json["imported"] == 1
    assert imported.json["duplicates"] == 2
    assert imported.json["invalid"] == 2
    transactions = client.get("/api/transactions").json["transactions"]
    assert len(transactions) == 2
    assert any(item["category"] == "Transit" for item in transactions)

    repeated = post_import(
        client, "/api/transactions/import", "expenses.csv", contents
    )
    assert repeated.status_code == 200
    assert repeated.json["imported"] == 0
    assert repeated.json["duplicates"] == 3
    assert repeated.json["invalid"] == 2
    assert len(client.get("/api/transactions").json["transactions"]) == 2


def test_excel_import_defaults_missing_type_to_expense(client):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Transaction Date", "Expense Category", "Merchant", "Amount"])
    sheet.append([date(2026, 5, 6), "Food", "Market", 32.75])
    contents = io.BytesIO()
    workbook.save(contents)

    preview = post_import(
        client,
        "/api/transactions/import/preview",
        "expenses.xlsx",
        contents.getvalue(),
    )
    assert preview.status_code == 200
    assert preview.json["ready"] == 1
    assert preview.json["mapping"]["type"] == ""

    imported = post_import(
        client, "/api/transactions/import", "expenses.xlsx", contents.getvalue()
    )
    assert imported.status_code == 200
    assert imported.json["imported"] == 1
    transaction = client.get("/api/transactions").json["transactions"][0]
    assert transaction["date"] == "2026-05-06"
    assert transaction["type"] == "expense"
    assert transaction["amount"] == 32.75
    assert transaction["description"] == "Market"


def test_import_reports_missing_columns_and_rejects_empty_or_unsupported_files(client):
    no_mapping = b"When,What,Cost\n2026-05-01,Food,10"
    preview = post_import(
        client, "/api/transactions/import/preview", "expenses.csv", no_mapping
    )
    assert preview.status_code == 200
    assert preview.json["missing_fields"] == ["date", "category", "amount"]
    assert post_import(
        client, "/api/transactions/import", "expenses.csv", no_mapping
    ).status_code == 400

    mapped_preview = post_import(
        client,
        "/api/transactions/import/preview",
        "expenses.csv",
        no_mapping,
        {"date": "0", "category": "1", "amount": "2"},
    )
    assert mapped_preview.status_code == 200
    assert mapped_preview.json["ready"] == 1

    assert post_import(
        client, "/api/transactions/import/preview", "empty.csv", b""
    ).status_code == 400
    assert post_import(
        client, "/api/transactions/import/preview", "empty.csv", b"Date,Amount\n"
    ).status_code == 400
    assert post_import(
        client, "/api/transactions/import/preview", "expenses.xls", no_mapping
    ).status_code == 400
    assert post_import(
        client, "/api/transactions/import/preview", "broken.xlsx", b"not an Excel file"
    ).status_code == 400


def test_import_database_error_is_reported_and_rolled_back(client, monkeypatch):
    contents = b"Date,Category,Amount\n2026-05-01,Food,10.00\n"

    def fail_commit():
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr("expense_tracker.routes._commit", fail_commit)
    response = post_import(
        client, "/api/transactions/import", "expenses.csv", contents
    )
    assert response.status_code == 500
    assert "No records were imported" in response.json["error"]
    assert client.get("/api/transactions").json["transactions"] == []
