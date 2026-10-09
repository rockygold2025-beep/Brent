import os
import secrets
import random
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, timedelta, date
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf import CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash

from models import db, User, Package, Investment, Transaction, Referral, AuditLog

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-only-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///investment.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["BRAND_NAME"] = os.getenv("BRAND_NAME", "Brent Investment Platform")
app.config["WELCOME_BONUS_NGN"] = int(os.getenv("WELCOME_BONUS_NGN", "600"))
app.config["REFERRAL_PERCENT"] = Decimal(os.getenv("REFERRAL_PERCENT", "15"))
app.config["BANK_NAME"] = os.getenv("BANK_NAME", "PalmPay")
app.config["BANK_ACCOUNT_NUMBER"] = os.getenv("BANK_ACCOUNT_NUMBER", "9015739887")
app.config["BANK_ACCOUNT_NAME"] = os.getenv("BANK_ACCOUNT_NAME", "Samuel Jeremiah")
app.config["MIN_WITHDRAWAL"] = Decimal(os.getenv("MIN_WITHDRAWAL", "1200"))
app.config["WITHDRAWAL_FEE_PERCENT"] = Decimal(os.getenv("WITHDRAWAL_FEE_PERCENT", "2"))
app.config["TELEGRAM_URL"] = os.getenv("TELEGRAM_URL", "https://t.me/brentinvestment")
app.config["CHECKIN_MAX"] = int(os.getenv("CHECKIN_MAX", "80"))

db.init_app(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
limiter = Limiter(key_func=get_remote_address, app=app, default_limits=["300 per minute"])

# name, amount, daily_return_naira
PACKAGE_DATA = [
    ("Starter", 3000, 500),
    ("Bronze", 5000, 1000),
    ("Silver", 10000, 2500),
    ("Gold", 25000, 6500),
    ("Platinum", 50000, 14000),
    ("Diamond", 100000, 30000),
    ("Premium", 150000, 48000),
    ("Executive", 250000, 85000),
    ("Elite", 350000, 125000),
    ("Principal", 500000, 185000),
]

PACKAGE_REASONS = {
    "Starter": "Start small and watch steady daily growth from day one.",
    "Bronze": "Step up your commitment and unlock stronger daily earnings.",
    "Silver": "A favorite for members who want serious daily progress.",
    "Gold": "Built for builders who want meaningful returns every day.",
    "Platinum": "Premium tier — higher placement, higher daily income.",
    "Diamond": "Ambitious capital meets sharp daily growth.",
    "Premium": "Scale with confidence and collect elevated daily returns.",
    "Executive": "Executive-level deposit for powerful daily output.",
    "Elite": "Near the top — elite capital, elite daily income.",
    "Principal": "Flagship product for maximum daily return potential.",
}


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.context_processor
def globals_processor():
    return {
        "brand_name": app.config["BRAND_NAME"],
        "welcome_bonus": app.config["WELCOME_BONUS_NGN"],
        "referral_percent": app.config["REFERRAL_PERCENT"],
        "bank_name": app.config["BANK_NAME"],
        "bank_account_number": app.config["BANK_ACCOUNT_NUMBER"],
        "bank_account_name": app.config["BANK_ACCOUNT_NAME"],
        "min_withdrawal": app.config["MIN_WITHDRAWAL"],
        "withdrawal_fee_percent": app.config["WITHDRAWAL_FEE_PERCENT"],
        "telegram_url": app.config["TELEGRAM_URL"],
    }


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def ledger_balance(user_id):
    rows = Transaction.query.filter_by(user_id=user_id, status="success").all()
    balance = Decimal("0")
    for row in rows:
        if row.type in {"deposit", "profit", "referral_bonus", "welcome_bonus", "refund", "checkin_bonus"}:
            balance += Decimal(row.amount)
        elif row.type in {"withdrawal", "withdrawal_fee"}:
            balance -= Decimal(row.amount)
    for row in Transaction.query.filter_by(user_id=user_id, type="withdrawal", status="pending").all():
        balance -= Decimal(row.amount)
    for row in Transaction.query.filter_by(user_id=user_id, type="withdrawal_fee", status="pending").all():
        balance -= Decimal(row.amount)
    return balance


def has_active_or_funded_product(user_id):
    """User must have at least one active investment (or successful deposit) to withdraw."""
    if Investment.query.filter_by(user_id=user_id, status="active").first():
        return True
    if Transaction.query.filter_by(user_id=user_id, type="deposit", status="success").first():
        return True
    return False


def add_transaction(user_id, tx_type, amount, reference=None, description="", status="success"):
    db.session.add(Transaction(
        user_id=user_id, type=tx_type, amount=Decimal(amount),
        reference=reference, description=description, status=status,
    ))


def audit(action, target="", details=""):
    db.session.add(AuditLog(
        admin_id=current_user.id if current_user.is_authenticated and current_user.is_admin else None,
        action=action, target=target, details=details,
    ))


def initialize_data():
    if Package.query.count() == 0:
        for name, amount, daily_naira in PACKAGE_DATA:
            reason = PACKAGE_REASONS.get(name, "")
            db.session.add(Package(
                name=name, min_amount=amount, max_amount=amount,
                duration_days=30, payout_enabled=True,
                daily_payout=Decimal(daily_naira),
                description=reason,
            ))
    email, password = os.getenv("ADMIN_EMAIL"), os.getenv("ADMIN_PASSWORD")
    if email and password and not User.query.filter_by(email=email.lower()).first():
        db.session.add(User(
            name="Administrator", email=email.lower(),
            password_hash=generate_password_hash(password),
            referral_code="ADMIN", is_admin=True, is_verified=True,
        ))


def activate_investment(investment):
    if investment.status == "active":
        return
    investment.status = "active"
    investment.started_at = datetime.utcnow()
    investment.maturity_at = datetime.utcnow() + timedelta(days=investment.package.duration_days)
    paid = Decimal(investment.principal)
    tx = Transaction.query.filter_by(
        reference=investment.payment_reference, type="deposit", status="pending"
    ).first()
    if tx:
        tx.status = "success"
        tx.description = f"Verified bank transfer for {investment.package.name}"
    elif not Transaction.query.filter_by(reference=investment.payment_reference, type="deposit", status="success").first():
        add_transaction(
            investment.user_id, "deposit", paid, investment.payment_reference,
            f"Verified bank transfer for {investment.package.name}",
        )
    referral = Referral.query.filter_by(referred_id=investment.user_id, status="pending").first()
    if referral:
        referral.amount = (paid * referral.percentage / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        referral.status = "qualified"
        add_transaction(
            referral.referrer_id, "referral_bonus", referral.amount,
            description=f"15% referral bonus for user #{investment.user_id}", status="pending",
        )


@app.route("/")
def index():
    packages = Package.query.filter_by(active=True).order_by(Package.min_amount).all()
    return render_template("index.html", packages=packages)


@app.route("/packages")
def packages():
    return render_template(
        "packages.html",
        packages=Package.query.filter_by(active=True).order_by(Package.min_amount).all(),
    )


@app.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    ref_from_url = request.args.get("ref", "").strip().upper()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        referral_code = request.form.get("referral_code", "").strip().upper() or ref_from_url
        if len(name) < 2 or "@" not in email or len(password) < 8:
            flash("Enter valid details. Password must be at least 8 characters.", "error")
            return render_template("register.html", prefill_ref=referral_code)
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
            return render_template("register.html", prefill_ref=referral_code)
        referrer = User.query.filter_by(referral_code=referral_code).first() if referral_code else None
        user = User(
            name=name, email=email, password_hash=generate_password_hash(password),
            referral_code=secrets.token_hex(4).upper(),
            referred_by=referrer.id if referrer else None, is_verified=True,
        )
        db.session.add(user)
        db.session.commit()
        db.session.add(Transaction(
            user_id=user.id, type="welcome_bonus",
            amount=app.config["WELCOME_BONUS_NGN"],
            description="Welcome bonus — credited on signup.", status="success",
        ))
        if referrer:
            db.session.add(Referral(
                referrer_id=referrer.id, referred_id=user.id,
                percentage=app.config["REFERRAL_PERCENT"], status="pending",
            ))
        db.session.commit()
        login_user(user)
        flash(f"Welcome! ₦{app.config['WELCOME_BONUS_NGN']:,} has been added to your balance.", "success")
        return redirect(url_for("dashboard"))
    return render_template("register.html", prefill_ref=ref_from_url)


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin_dashboard" if current_user.is_admin else "dashboard"))
    if request.method == "POST":
        user = User.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
        if not user or not check_password_hash(user.password_hash, request.form.get("password", "")):
            flash("Invalid email or password.", "error")
            return render_template("login.html")
        if user.status != "active":
            flash("Your account is restricted.", "error")
            return render_template("login.html")
        login_user(user)
        return redirect(url_for("admin_dashboard" if user.is_admin else "dashboard"))
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    investments = Investment.query.filter_by(user_id=current_user.id).order_by(Investment.created_at.desc()).all()
    transactions = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.created_at.desc()).limit(12).all()
    checked_in_today = current_user.last_checkin == date.today()
    return render_template(
        "dashboard.html",
        investments=investments, transactions=transactions,
        balance=ledger_balance(current_user.id),
        checked_in_today=checked_in_today,
    )


@app.route("/checkin", methods=["POST"])
@login_required
@limiter.limit("5 per minute")
def checkin():
    if current_user.last_checkin == date.today():
        flash("You already claimed today's check-in bonus.", "error")
        return redirect(url_for("dashboard"))
    amount = Decimal(random.randint(1, app.config["CHECKIN_MAX"]))
    current_user.last_checkin = date.today()
    db.session.add(Transaction(
        user_id=current_user.id, type="checkin_bonus", amount=amount,
        description=f"Daily check-in bonus (₦{amount})", status="success",
    ))
    db.session.commit()
    flash(f"Check-in successful! ₦{amount} credited to your balance.", "success")
    return redirect(url_for("dashboard"))


@app.route("/referral")
@login_required
def referral():
    ref_link = url_for("register", ref=current_user.referral_code, _external=True)
    refs = Referral.query.filter_by(referrer_id=current_user.id).order_by(Referral.created_at.desc()).all()
    return render_template("referral.html", ref_link=ref_link, refs=refs)


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if len(name) < 2:
            flash("Enter a valid name.", "error")
        else:
            current_user.name = name
            db.session.commit()
            flash("Profile updated.", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", balance=ledger_balance(current_user.id))


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        current_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not check_password_hash(current_user.password_hash, current_pw):
            flash("Current password is incorrect.", "error")
        elif len(new_pw) < 8:
            flash("New password must be at least 8 characters.", "error")
        elif new_pw != confirm:
            flash("New passwords do not match.", "error")
        else:
            current_user.password_hash = generate_password_hash(new_pw)
            db.session.commit()
            flash("Password changed successfully.", "success")
            return redirect(url_for("settings"))
    return render_template("settings.html")


@app.route("/withdraw", methods=["GET", "POST"])
@login_required
def withdraw():
    balance = ledger_balance(current_user.id)
    can_withdraw = has_active_or_funded_product(current_user.id)
    fee_pct = app.config["WITHDRAWAL_FEE_PERCENT"]
    if request.method == "POST":
        if not can_withdraw:
            flash("You need an active investment product before you can withdraw. The welcome bonus alone cannot be withdrawn.", "error")
            return render_template("withdraw.html", balance=balance, can_withdraw=can_withdraw, fee_pct=fee_pct)
        try:
            amount = Decimal(request.form.get("amount", "0"))
        except InvalidOperation:
            amount = Decimal("0")
        bank_name = request.form.get("bank_name", "").strip()
        account_number = request.form.get("account_number", "").strip()
        account_name = request.form.get("account_name", "").strip()
        fee = (amount * fee_pct / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_deduct = amount + fee
        if amount < app.config["MIN_WITHDRAWAL"]:
            flash(f"Minimum withdrawal is ₦{app.config['MIN_WITHDRAWAL']:,.0f}.", "error")
            return render_template("withdraw.html", balance=balance, can_withdraw=can_withdraw, fee_pct=fee_pct)
        if total_deduct > balance:
            flash(f"Insufficient balance. You need ₦{total_deduct:,.2f} (amount + {fee_pct}% fee).", "error")
            return render_template("withdraw.html", balance=balance, can_withdraw=can_withdraw, fee_pct=fee_pct)
        if not bank_name or len(account_number) < 10 or len(account_name) < 2:
            flash("Enter valid bank details.", "error")
            return render_template("withdraw.html", balance=balance, can_withdraw=can_withdraw, fee_pct=fee_pct)
        ref = f"WD-{secrets.token_hex(5).upper()}"
        desc = f"Withdrawal to {bank_name} {account_number} ({account_name})"
        db.session.add(Transaction(
            user_id=current_user.id, type="withdrawal", amount=amount,
            reference=ref, description=desc, status="pending",
        ))
        db.session.add(Transaction(
            user_id=current_user.id, type="withdrawal_fee", amount=fee,
            reference=ref, description=f"{fee_pct}% withdrawal charge", status="pending",
        ))
        db.session.commit()
        flash(f"Withdrawal of ₦{amount:,.2f} submitted (fee ₦{fee:,.2f}). We are processing your request.", "success")
        return redirect(url_for("dashboard"))
    return render_template("withdraw.html", balance=balance, can_withdraw=can_withdraw, fee_pct=fee_pct)


@app.route("/invest/<int:package_id>", methods=["POST"])
@login_required
def invest(package_id):
    package = db.session.get(Package, package_id)
    if not package or not package.active:
        abort(404)
    try:
        amount = Decimal(request.form.get("amount", "0"))
    except InvalidOperation:
        amount = Decimal("0")
    if amount != Decimal(package.min_amount):
        flash("Invalid package amount.", "error")
        return redirect(url_for("packages"))
    reference = f"INV-{secrets.token_hex(6).upper()}"
    investment = Investment(
        user_id=current_user.id, package_id=package.id,
        principal=amount, payment_reference=reference, status="awaiting_payment",
    )
    db.session.add(investment)
    db.session.add(Transaction(
        user_id=current_user.id, type="deposit", amount=amount,
        reference=reference,
        description=f"Deposit for {package.name}",
        status="pending",
    ))
    db.session.commit()
    return redirect(url_for("payment_instructions", investment_id=investment.id))


@app.route("/payment/<int:investment_id>")
@login_required
def payment_instructions(investment_id):
    investment = db.session.get(Investment, investment_id)
    if not investment or investment.user_id != current_user.id:
        abort(404)
    return render_template("payment.html", investment=investment)


@app.route("/payment/<int:investment_id>/confirm", methods=["POST"])
@login_required
def confirm_payment_sent(investment_id):
    investment = db.session.get(Investment, investment_id)
    if not investment or investment.user_id != current_user.id:
        abort(404)
    if investment.status == "awaiting_payment":
        investment.status = "payment_submitted"
        db.session.commit()
        flash("Thanks! Your transfer is pending admin verification.", "success")
    return redirect(url_for("dashboard"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    users = User.query.order_by(User.created_at.desc()).limit(20).all()
    investments = Investment.query.order_by(Investment.created_at.desc()).limit(30).all()
    pending_investments = Investment.query.filter(
        Investment.status.in_(["awaiting_payment", "payment_submitted"])
    ).order_by(Investment.created_at.desc()).all()
    pending = Transaction.query.filter_by(status="pending").order_by(Transaction.created_at.desc()).all()
    return render_template(
        "admin.html",
        users=users, investments=investments,
        pending_investments=pending_investments, pending=pending,
    )


@app.route("/admin/investment/<int:inv_id>/approve", methods=["POST"])
@admin_required
def approve_investment(inv_id):
    investment = db.session.get(Investment, inv_id)
    if not investment:
        abort(404)
    if investment.status in ("awaiting_payment", "payment_submitted"):
        activate_investment(investment)
        audit("approve_investment", str(investment.id),
              f"Approved investment #{investment.id} for user {investment.user_id}")
        db.session.commit()
        flash(f"Investment #{investment.id} approved and activated.", "success")
    else:
        flash("Investment is not pending payment.", "error")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/investment/<int:inv_id>/reject", methods=["POST"])
@admin_required
def reject_investment(inv_id):
    investment = db.session.get(Investment, inv_id)
    if not investment:
        abort(404)
    if investment.status in ("awaiting_payment", "payment_submitted"):
        investment.status = "payment_failed"
        tx = Transaction.query.filter_by(
            reference=investment.payment_reference, type="deposit", status="pending"
        ).first()
        if tx:
            tx.status = "rejected"
        audit("reject_investment", str(investment.id),
              f"Rejected investment #{investment.id}")
        db.session.commit()
        flash(f"Investment #{investment.id} rejected.", "success")
    else:
        flash("Investment is not pending payment.", "error")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/transaction/<int:tx_id>/approve", methods=["POST"])
@admin_required
def approve_transaction(tx_id):
    tx = db.session.get(Transaction, tx_id)
    if not tx:
        abort(404)
    tx.status = "success"
    # If approving a withdrawal, also approve linked fee with same reference
    if tx.type == "withdrawal" and tx.reference:
        fee = Transaction.query.filter_by(
            reference=tx.reference, type="withdrawal_fee", status="pending"
        ).first()
        if fee:
            fee.status = "success"
    audit("approve_transaction", str(tx.id), f"Approved {tx.type} for user {tx.user_id}")
    db.session.commit()
    flash(f"{tx.type.replace('_', ' ').title()} approved.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/transaction/<int:tx_id>/reject", methods=["POST"])
@admin_required
def reject_transaction(tx_id):
    tx = db.session.get(Transaction, tx_id)
    if not tx:
        abort(404)
    tx.status = "rejected"
    if tx.type == "withdrawal" and tx.reference:
        fee = Transaction.query.filter_by(
            reference=tx.reference, type="withdrawal_fee", status="pending"
        ).first()
        if fee:
            fee.status = "rejected"
    audit("reject_transaction", str(tx.id), f"Rejected {tx.type} for user {tx.user_id}")
    db.session.commit()
    flash(f"{tx.type.replace('_', ' ').title()} rejected.", "success")
    return redirect(url_for("admin_dashboard"))


with app.app_context():
    db.create_all()
    initialize_data()
    db.session.commit()

if __name__ == "__main__":
    debug = os.getenv("FLASK_ENV") != "production"
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    print(f"\n  Starting {app.config['BRAND_NAME']}")
    print(f"  Open http://{host}:{port}")
    print(f"  Admin: {os.getenv('ADMIN_EMAIL', 'admin@example.com')}")
    print(f"  Bank:  {app.config['BANK_NAME']} {app.config['BANK_ACCOUNT_NUMBER']} — {app.config['BANK_ACCOUNT_NAME']}\n")
    app.run(host=host, port=port, debug=debug)
