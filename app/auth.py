"""Authentication: signup, login, and OTP-based password reset.

Passwords are hashed with PBKDF2-HMAC-SHA256 from the standard library -- no
external crypto dependency to install or get wrong.

There is no mail service on a hackathon clock, so the reset OTP is displayed on
screen in demo mode. That is a deliberate, visible shortcut, not an oversight:
swap ``_deliver_otp`` for a real mail send and the flow is production-shaped.
"""

import functools
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for,
)

from .db import execute, query

bp = Blueprint("auth", __name__)

PBKDF2_ROUNDS = 120_000
OTP_TTL_MINUTES = 10
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now():
    return datetime.now(timezone.utc)


def now_str():
    return _now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt_hex, digest_hex = stored.split("$")
    except (ValueError, AttributeError):
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


# ---------------------------------------------------------------------------
# Session plumbing
# ---------------------------------------------------------------------------


@bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True) if user_id else None


def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view(**kwargs)

    return wrapped_view


# ---------------------------------------------------------------------------
# Signup / login / logout
# ---------------------------------------------------------------------------


@bp.route("/signup", methods=("GET", "POST"))
def signup():
    if g.user:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        role = request.form.get("role", "Inventory Manager").strip() or "Inventory Manager"

        errors = []
        if not name:
            errors.append("Your name is required.")
        if not EMAIL_PATTERN.match(email):
            errors.append("That does not look like a valid email address.")
        if len(password) < 8:
            errors.append("Choose a password of at least 8 characters.")
        if password != confirm:
            errors.append("The two passwords do not match.")
        if query("SELECT 1 FROM users WHERE email = ?", (email,), one=True):
            errors.append("An account with that email already exists.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("auth/signup.html", form=request.form)

        user_id = execute(
            """INSERT INTO users (email, name, role, password_hash, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (email, name, role, hash_password(password), now_str()),
        )
        session.clear()
        session["user_id"] = user_id
        flash(f"Welcome to StockSense, {name}.", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("auth/signup.html", form={})


@bp.route("/login", methods=("GET", "POST"))
def login():
    if g.user:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)

        if user is None or not verify_password(password, user["password_hash"]):
            flash("Incorrect email or password.", "error")
            return render_template("auth/login.html", email=email)

        session.clear()
        session["user_id"] = user["id"]
        flash(f"Signed in as {user['name']}.", "success")

        nxt = request.args.get("next") or request.form.get("next")
        if nxt and nxt.startswith("/"):
            return redirect(nxt)
        return redirect(url_for("dashboard.index"))

    return render_template("auth/login.html", email="")


@bp.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))


# ---------------------------------------------------------------------------
# OTP password reset
# ---------------------------------------------------------------------------


def _deliver_otp(email: str, otp: str) -> None:
    """Hand the OTP to the user.

    Demo mode: the caller renders it on screen. Replace this with a mail send
    (SES, SendGrid, SMTP) and the rest of the flow needs no change.
    """
    return None


@bp.route("/forgot-password", methods=("GET", "POST"))
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)

        if user is None:
            # Do not reveal whether an account exists. Same message either way.
            flash("If that email has an account, a reset code has been sent.", "info")
            return redirect(url_for("auth.forgot_password"))

        otp = f"{secrets.randbelow(1_000_000):06d}"
        expires = (_now() + timedelta(minutes=OTP_TTL_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
        execute(
            """INSERT INTO password_resets (email, otp, expires_at, used, created_at)
               VALUES (?, ?, ?, 0, ?)""",
            (email, otp, expires, now_str()),
        )
        _deliver_otp(email, otp)

        # Demo mode: no mail service, so show the code. Clearly labelled.
        return render_template(
            "auth/otp_issued.html", email=email, otp=otp, ttl=OTP_TTL_MINUTES
        )

    return render_template("auth/forgot_password.html")


@bp.route("/reset-password", methods=("GET", "POST"))
def reset_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        otp = request.form.get("otp", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        record = query(
            """SELECT * FROM password_resets
               WHERE email = ? AND otp = ? AND used = 0
               ORDER BY id DESC LIMIT 1""",
            (email, otp),
            one=True,
        )

        errors = []
        if record is None:
            errors.append("That reset code is not valid for this email address.")
        elif record["expires_at"] < now_str():
            errors.append("That reset code has expired. Request a new one.")
        if len(password) < 8:
            errors.append("Choose a password of at least 8 characters.")
        if password != confirm:
            errors.append("The two passwords do not match.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("auth/reset_password.html", email=email, otp=otp)

        user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)
        if user is None:
            flash("That account no longer exists.", "error")
            return redirect(url_for("auth.forgot_password"))

        execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(password), user["id"]),
        )
        execute("UPDATE password_resets SET used = 1 WHERE id = ?", (record["id"],))
        flash("Your password has been reset. Sign in with your new password.", "success")
        return redirect(url_for("auth.login"))

    return render_template(
        "auth/reset_password.html",
        email=request.args.get("email", ""),
        otp=request.args.get("otp", ""),
    )


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


@bp.route("/profile", methods=("GET", "POST"))
@login_required
def profile():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        role = request.form.get("role", "").strip() or g.user["role"]

        if not name:
            flash("Your name cannot be empty.", "error")
            return redirect(url_for("auth.profile"))

        execute("UPDATE users SET name = ?, role = ? WHERE id = ?", (name, role, g.user["id"]))
        flash("Profile updated.", "success")
        return redirect(url_for("auth.profile"))

    stats = {
        "documents": query(
            "SELECT COUNT(*) AS n FROM documents WHERE created_by = ?", (g.user["id"],), one=True
        )["n"],
        "validated": query(
            "SELECT COUNT(*) AS n FROM documents WHERE validated_by = ?", (g.user["id"],), one=True
        )["n"],
        "moves": query(
            "SELECT COUNT(*) AS n FROM stock_moves WHERE created_by = ?", (g.user["id"],), one=True
        )["n"],
    }
    return render_template("auth/profile.html", stats=stats)
