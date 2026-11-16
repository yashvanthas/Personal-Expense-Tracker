from datetime import date

import pandas as pd
import plotly.graph_objects as go

from expense_tracker.models import Transaction


def transaction_frame(user_id, start_date=None, end_date=None):
    query = Transaction.query.filter(Transaction.user_id == user_id)
    if start_date:
        query = query.filter(Transaction.date >= start_date)
    if end_date:
        query = query.filter(Transaction.date <= end_date)

    records = [
        {
            "date": transaction.date,
            "type": transaction.type,
            "amount": float(transaction.amount),
            "category": transaction.category,
        }
        for transaction in query.order_by(Transaction.date).all()
    ]
    return pd.DataFrame(records, columns=["date", "type", "amount", "category"])


def monthly_summary(frame):
    if frame.empty:
        return []

    frame = frame.copy()
    frame["month"] = frame["date"].map(lambda value: value.strftime("%Y-%m"))
    totals = frame.pivot_table(
        index="month", columns="type", values="amount", aggfunc="sum", fill_value=0
    )
    months = []
    for month, row in totals.iterrows():
        income = float(row.get("income", 0))
        expenses = float(row.get("expense", 0))
        months.append(
            {
                "month": month,
                "income": round(income, 2),
                "expenses": round(expenses, 2),
                "net": round(income - expenses, 2),
            }
        )
    return months


def category_summary(frame):
    expenses = frame[frame["type"] == "expense"]
    if expenses.empty:
        return []

    totals = (
        expenses.groupby("category", as_index=False)["amount"]
        .sum()
        .sort_values(["amount", "category"], ascending=[False, True])
    )
    return [
        {"category": row.category, "amount": round(float(row.amount), 2)}
        for row in totals.itertuples(index=False)
    ]


def period_summary(frame, start_date=None, end_date=None):
    income = frame.loc[frame["type"] == "income", "amount"].sum()
    expenses = frame.loc[frame["type"] == "expense", "amount"].sum()
    categories = category_summary(frame)

    if start_date:
        period_start = start_date
    elif frame.empty:
        period_start = None
    else:
        period_start = min(frame["date"])

    if end_date:
        period_end = end_date
    elif frame.empty:
        period_end = None
    else:
        period_end = max(frame["date"])

    days = max(1, (period_end - period_start).days + 1) if period_start and period_end else 0
    return {
        "start_date": period_start.isoformat() if period_start else None,
        "end_date": period_end.isoformat() if period_end else None,
        "days": days,
        "transaction_count": len(frame),
        "income": round(float(income), 2),
        "expenses": round(float(expenses), 2),
        "net": round(float(income - expenses), 2),
        "average_daily_expenses": round(float(expenses / days), 2) if days else 0,
        "top_expense_category": categories[0] if categories else None,
    }


def trend_figure(summary):
    months = [item["month"] for item in summary]
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=months,
            y=[item["income"] for item in summary],
            mode="lines+markers",
            name="Income",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=months,
            y=[item["expenses"] for item in summary],
            mode="lines+markers",
            name="Expenses",
        )
    )
    figure.update_layout(
        title="Monthly income and expenses",
        xaxis_title="Month",
        yaxis_title="Amount",
        template="plotly_white",
        hovermode="x unified",
    )
    return figure
