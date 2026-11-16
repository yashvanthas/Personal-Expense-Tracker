import re

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import func

from expense_tracker import db, limiter
from expense_tracker.models import User

auth = Blueprint("auth", __name__)
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128


@auth.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("api.dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if len(email) > 320 or not EMAIL_PATTERN.fullmatch(email):
            flash("Enter a valid email address.", "error")
        elif not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
            flash(
                f"Password must be {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} characters.",
                "error",
            )
        elif db.session.query(User.id).filter(
            func.lower(User.email) == email
        ).first():
            flash("An account with that email already exists.", "error")
        else:
            user = User(email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user, fresh=True)
            return redirect(url_for("api.dashboard"))
    return render_template("auth.html", mode="register")


@auth.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("api.dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter(func.lower(User.email) == email).first()
        if user is None or not user.check_password(password):
            flash("Email or password is incorrect.", "error")
        else:
            login_user(user, fresh=True)
            return redirect(url_for("api.dashboard"))
    return render_template("auth.html", mode="login")


@auth.post("/logout")
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))
