"""Add user accounts and scope transactions and budgets by account.

Revision ID: 219f9a82493e
Revises:
Create Date: 2026-10-29 14:35:46.838495
"""

from alembic import op
import sqlalchemy as sa


revision = "219f9a82493e"
down_revision = None
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _create_user_table():
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_email", "user", ["email"], unique=True)


def _create_transaction_table():
    op.create_table(
        "transaction",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(length=10), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name="fk_transaction_user_id_user"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transaction_category", "transaction", ["category"])
    op.create_index("ix_transaction_date", "transaction", ["date"])
    op.create_index("ix_transaction_type", "transaction", ["type"])
    op.create_index("ix_transaction_user_id", "transaction", ["user_id"])


def _create_budget_table():
    op.create_table(
        "budget",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_budget_user_id_user"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "month", "category", name="uq_budget_user_month_category"
        ),
    )
    op.create_index("ix_budget_month", "budget", ["month"])
    op.create_index("ix_budget_user_id", "budget", ["user_id"])


def _ensure_user_column(table_name):
    inspector = _inspector()
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if "user_id" not in columns:
        with op.batch_alter_table(table_name) as batch:
            batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                f"fk_{table_name}_user_id_user", "user", ["user_id"], ["id"]
            )

    indexes = {index["name"] for index in _inspector().get_indexes(table_name)}
    index_name = f"ix_{table_name}_user_id"
    if index_name not in indexes:
        op.create_index(index_name, table_name, ["user_id"])


def _ensure_budget_uniqueness():
    constraints = _inspector().get_unique_constraints("budget")
    names = {constraint["name"] for constraint in constraints}
    old_constraint = "uq_budget_month_category"
    scoped_constraint = "uq_budget_user_month_category"
    if old_constraint in names or scoped_constraint not in names:
        with op.batch_alter_table("budget", recreate="always") as batch:
            if old_constraint in names:
                batch.drop_constraint(old_constraint, type_="unique")
            if scoped_constraint not in names:
                batch.create_unique_constraint(
                    scoped_constraint, ["user_id", "month", "category"]
                )


def upgrade():
    inspector = _inspector()
    if not inspector.has_table("user"):
        _create_user_table()
    else:
        indexes = {index["name"] for index in inspector.get_indexes("user")}
        if "ix_user_email" not in indexes:
            op.create_index("ix_user_email", "user", ["email"], unique=True)

    inspector = _inspector()
    if not inspector.has_table("transaction"):
        _create_transaction_table()
    else:
        _ensure_user_column("transaction")

    inspector = _inspector()
    if not inspector.has_table("budget"):
        _create_budget_table()
    else:
        _ensure_user_column("budget")
        _ensure_budget_uniqueness()


def downgrade():
    inspector = _inspector()
    if inspector.has_table("budget"):
        duplicate_budget = op.get_bind().execute(
            sa.text(
                "SELECT 1 FROM budget GROUP BY month, category "
                "HAVING COUNT(*) > 1 LIMIT 1"
            )
        ).first()
        if duplicate_budget:
            raise RuntimeError(
                "Cannot downgrade while different accounts have matching month/category budgets."
            )
        indexes = {index["name"] for index in inspector.get_indexes("budget")}
        with op.batch_alter_table("budget", recreate="always") as batch:
            batch.drop_constraint("uq_budget_user_month_category", type_="unique")
            batch.drop_constraint("fk_budget_user_id_user", type_="foreignkey")
            if "ix_budget_user_id" in indexes:
                batch.drop_index("ix_budget_user_id")
            batch.drop_column("user_id")
            batch.create_unique_constraint(
                "uq_budget_month_category", ["month", "category"]
            )

    inspector = _inspector()
    if inspector.has_table("transaction"):
        indexes = {index["name"] for index in inspector.get_indexes("transaction")}
        with op.batch_alter_table("transaction", recreate="always") as batch:
            batch.drop_constraint("fk_transaction_user_id_user", type_="foreignkey")
            if "ix_transaction_user_id" in indexes:
                batch.drop_index("ix_transaction_user_id")
            batch.drop_column("user_id")

    if _inspector().has_table("user"):
        op.drop_table("user")
