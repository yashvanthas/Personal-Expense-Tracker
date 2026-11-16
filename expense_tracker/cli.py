import sqlite3
from datetime import date
from pathlib import Path

import click
from flask.cli import with_appcontext
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from expense_tracker import db
from expense_tracker.models import Budget, Transaction, User


def register_commands(app):
    @app.cli.command("import-legacy-data")
    @click.option("--email", required=True, help="Account email to receive the old data.")
    @click.option(
        "--source",
        required=True,
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="Path to the previous SQLite database or SQLite backup.",
    )
    @with_appcontext
    def import_legacy_data(email, source):
        user = User.query.filter(func.lower(User.email) == email.strip().lower()).first()
        if user is None:
            raise click.ClickException("Create the destination account before importing data.")
        if Transaction.query.filter_by(user_id=user.id).first() or Budget.query.filter_by(
            user_id=user.id
        ).first():
            raise click.ClickException(
                "The destination account already has data; import requires an empty account."
            )

        try:
            connection = sqlite3.connect(str(source))
            connection.row_factory = sqlite3.Row
            try:
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                if not {"transaction", "budget"}.issubset(tables):
                    raise click.ClickException(
                        "Source must be an Expense Tracker SQLite database containing transaction and budget tables."
                    )

                transaction_columns = {
                    row["name"]
                    for row in connection.execute('PRAGMA table_info("transaction")')
                }
                budget_columns = {
                    row["name"] for row in connection.execute("PRAGMA table_info(budget)")
                }
                transaction_owner_filter = (
                    " WHERE user_id IS NULL"
                    if "user_id" in transaction_columns
                    else ""
                )
                budget_owner_filter = (
                    " WHERE user_id IS NULL" if "user_id" in budget_columns else ""
                )
                transaction_rows = connection.execute(
                    'SELECT type, amount, category, description, date FROM "transaction"'
                    + transaction_owner_filter
                ).fetchall()
                budget_rows = connection.execute(
                    "SELECT month, category, amount FROM budget" + budget_owner_filter
                ).fetchall()
            finally:
                connection.close()
        except (sqlite3.DatabaseError, OSError) as error:
            raise click.ClickException(f"Could not read the legacy SQLite database: {error}") from error

        try:
            db.session.add_all(
                [
                    Transaction(
                        user_id=user.id,
                        type=row["type"],
                        amount=row["amount"],
                        category=row["category"],
                        description=row["description"],
                        date=date.fromisoformat(str(row["date"])),
                    )
                    for row in transaction_rows
                ]
            )
            db.session.add_all(
                [
                    Budget(
                        user_id=user.id,
                        month=row["month"],
                        category=row["category"],
                        amount=row["amount"],
                    )
                    for row in budget_rows
                ]
            )
            db.session.commit()
        except SQLAlchemyError as error:
            db.session.rollback()
            raise click.ClickException(f"Could not import legacy data: {error}") from error

        click.echo(
            f"Imported {len(transaction_rows)} transactions and {len(budget_rows)} budgets "
            f"into {user.email}."
        )
