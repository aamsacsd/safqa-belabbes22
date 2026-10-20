# -*- coding: utf-8 -*-
"""Routes de l'application."""
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta
from functools import wraps
from urllib.parse import urlparse

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func, or_

from constants import COMMUNE_NAMES, SECTORS, WILAYA_WIDE
from i18n import LANGS, translate
from matching import score_tender
from models import (Ad, Favorite, Notification, PartnershipAd, PasswordReset, SavedAlert,
                    Tender, User, db)
from notifier import send_sms
from sources import import_csv, scrape_configured_source, upsert_tender
from utils import (is_http_url, like_escape, normalize_phone, parse_budget, parse_date,
                   safe_next_url, today_dz, utcnow)

bp = Blueprint("main", __name__)

# ---------------------------------------------------------------- utilitaires

_attempts = defaultdict(deque)


def throttled(key, limit, window):
    """Limiteur simple en mémoire (par processus) contre la force brute."""
    now, q = time.monotonic(), _attempts[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


def client_ip():
    return request.remote_addr or "?"


def is_premium():
    return current_user.is_authenticated and current_user.is_premium


def admin_required(fn):
    @login_required
    def inner(*a, **k):
        if not current_user.is_admin:
            abort(403)
        return fn(*a, **k)
    return wraps(fn)(inner)


def f(name):
    return (request.form.get(name) or "").strip()


def free_cutoff():
    return utcnow() - timedelta(hours=current_app.config["FREE_PLAN_DELAY_HOURS"])


def code_hash(phone, code):
    key = current_app.config["SECRET_KEY"].encode()
    return hmac.new(key, f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def filtered_query(args):
    """Requête commune à la page d'accueil et à l'API."""
    q = Tender.query.filter_by(is_active=True)
    if args.get("expired") != "1":
        q = q.filter(Tender.deadline >= today_dz())
    sector, commune, text = args.get("sector", ""), args.get("commune", ""), (args.get("q") or "").strip()
    if sector in SECTORS:
        q = q.filter(Tender.sector == sector)
    if commune in COMMUNE_NAMES and commune != WILAYA_WIDE:
        q = q.filter(or_(Tender.commune == commune, Tender.commune == WILAYA_WIDE))
    if text:
        like = f"%{like_escape(text[:80])}%"
        q = q.filter(or_(Tender.title.ilike(like, escape="\\"), Tender.agency.ilike(like, escape="\\"),
                         Tender.description.ilike(like, escape="\\")))
        if not is_premium():  # la recherche ne doit pas révéler les offres encore verrouillées
            q = q.filter(Tender.created_at <= free_cutoff())
    if args.get("sort") == "deadline":
        return q.order_by(Tender.deadline.asc(), Tender.id.desc())
    return q.order_by(Tender.created_at.desc(), Tender.id.desc())


# ---------------------------------------------------------------- pages publiques

@bp.route("/")
def index():
    page = request.args.get("page", 1, type=int)
    pagination = filtered_query(request.args).paginate(
        page=page, per_page=current_app.config["ITEMS_PER_PAGE"], error_out=False)
    favs = set()
    if current_user.is_authenticated:
        favs = {x.tender_id for x in Favorite.query.filter_by(user_id=current_user.id)}
    items = []
    for t in pagination.items:
        score, reasons = (None, [])
        if current_user.is_authenticated:
            score, reasons = score_tender(current_user, t)
        items.append({"tender": t, "locked": t.locked_for(current_user), "score": score,
                      "reasons": reasons, "fav": t.id in favs})

    base = Tender.query.filter(Tender.is_active.is_(True), Tender.deadline >= today_dz())
    stats = {
        "active": base.count(),
        "new": base.filter(Tender.created_at >= utcnow() - timedelta(hours=48)).count(),
        "closing": base.filter(Tender.deadline <= today_dz() + timedelta(days=7)).count(),
    }
    locked_count = 0 if is_premium() else base.filter(Tender.created_at > free_cutoff()).count()
    ads = Ad.query.filter_by(is_approved=True).order_by(Ad.created_at.desc()).limit(4).all()

    return render_template(
        "index.html", items=items, pagination=pagination, stats=stats, locked_count=locked_count,
        ads=ads, args=request.args,
        page_url=lambda p: url_for("main.index", **{**request.args.to_dict(), "page": p}))


@bp.route("/tender/<int:tid>")
@login_required
def tender_detail(tid):
    tender = db.get_or_404(Tender, tid)
    if not tender.is_active and not current_user.is_admin:
        abort(404)
    if tender.locked_for(current_user):
        flash(translate("locked_msg", h=tender.hours_until_unlock), "warning")
        return redirect(url_for("main.pricing"))
    score, reasons = score_tender(current_user, tender)
    fav = Favorite.query.filter_by(user_id=current_user.id, tender_id=tid).first() is not None
    return render_template("detail.html", tender=tender, score=score, reasons=reasons, fav=fav)


@bp.post("/tender/<int:tid>/favorite")
@login_required
def toggle_favorite(tid):
    tender = db.get_or_404(Tender, tid)
    if tender.locked_for(current_user):
        abort(403)
    fav = Favorite.query.filter_by(user_id=current_user.id, tender_id=tid).first()
    if fav:
        db.session.delete(fav)
    else:
        db.session.add(Favorite(user_id=current_user.id, tender_id=tid))
    db.session.commit()
    return redirect(safe_next_url(request.form.get("next")) or url_for("main.tender_detail", tid=tid))


@bp.route("/stats")
def stats():
    base = Tender.query.filter(Tender.is_active.is_(True), Tender.deadline >= today_dz())
    ids = base.with_entities(Tender.id)
    by_sector = (db.session.query(Tender.sector, func.count(Tender.id)).filter(Tender.id.in_(ids))
                 .group_by(Tender.sector).order_by(func.count(Tender.id).desc()).all())
    by_commune = (db.session.query(Tender.commune, func.count(Tender.id)).filter(Tender.id.in_(ids))
                  .group_by(Tender.commune).order_by(func.count(Tender.id).desc()).limit(10).all())
    data = {
        "total": base.count(),
        "new48": base.filter(Tender.created_at >= utcnow() - timedelta(hours=48)).count(),
        "closing": base.filter(Tender.deadline <= today_dz() + timedelta(days=7)).count(),
        "members": User.query.filter_by(active=True).count(),
    }
    return render_template("stats.html", data=data, by_sector=by_sector, by_commune=by_commune)


@bp.route("/pricing")
def pricing():
    return render_template("pricing.html")


@bp.route("/lang/<code>")
def set_lang(code):
    from i18n import LANGS
    if code in LANGS:
        session["lang"] = code
    ref = urlparse(request.referrer or "")
    back = ref.path + (f"?{ref.query}" if ref.query else "") if ref.netloc == request.host else ""
    return redirect(safe_next_url(back) or url_for("main.index"))


# ---------------------------------------------------------------- authentification

@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        name, email, pw, cf = f("full_name"), f("email").lower(), request.form.get("password", ""), request.form.get("confirm", "")
        phone = normalize_phone(f("phone"))
        errors = []
        if len(name) < 3:
            errors.append("err_name")
        if "@" not in email or "." not in email.split("@")[-1]:
            errors.append("err_email")
        if not phone:
            errors.append("err_phone")
        if len(pw) < 8:
            errors.append("err_password")
        elif pw != cf:
            errors.append("err_confirm")
        if not errors and User.query.filter_by(email=email).first():
            errors.append("err_email_taken")
        if not errors and User.query.filter_by(phone=phone).first():
            errors.append("err_phone_taken")
        if errors:
            for e in errors:
                flash(translate(e), "error")
            return render_template("register.html", form=request.form), 400
        activity = f("activity")
        commune = f("commune")
        user = User(full_name=name, email=email, phone=phone, company=f("company")[:150] or None,
                    activity=activity if activity in SECTORS else None,
                    commune=commune if commune in COMMUNE_NAMES else None,
                    public_profile=request.form.get("public_profile") == "on")
        user.set_password(pw)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash(translate("ok_registered"), "success")
        return redirect(url_for("main.dashboard"))
    return render_template("register.html", form={"public_profile": "on"})


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        ident, pw = f("identifier").lower(), request.form.get("password", "")
        if throttled(f"login:{client_ip()}:{ident}", 8, 600):
            flash(translate("err_throttle"), "error")
            return render_template("login.html"), 429
        user = (User.query.filter_by(email=ident).first() if "@" in ident
                else User.query.filter_by(phone=normalize_phone(ident) or "-").first())
        if user and user.active and user.check_password(pw):
            login_user(user, remember=True)
            return redirect(safe_next_url(request.args.get("next")) or url_for("main.dashboard"))
        flash(translate("err_credentials"), "error")
        return render_template("login.html"), 401
    return render_template("login.html")


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.index"))


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        phone = normalize_phone(f("phone"))
        if not phone:
            flash(translate("err_phone"), "error")
            return render_template("forgot_password.html"), 400
        if throttled(f"forgot:{client_ip()}", 5, 900):
            flash(translate("err_throttle"), "error")
            return render_template("forgot_password.html"), 429
        # Réponse identique que le numéro existe ou non (pas d'énumération de comptes).
        user = User.query.filter_by(phone=phone, active=True).first()
        recent = PasswordReset.query.filter(
            PasswordReset.phone == phone, PasswordReset.created_at > utcnow() - timedelta(minutes=15)).count()
        if user and recent < 3:
            code = "".join(secrets.choice("0123456789") for _ in range(6))
            db.session.add(PasswordReset(phone=phone, code_hash=code_hash(phone, code),
                                         expires_at=utcnow() + timedelta(minutes=15)))
            db.session.commit()
            send_sms(phone, f"Safqa Belabbes : code {code} (valable 15 min)")
            if current_app.config["SMS_MODE"] == "demo":
                flash(translate("demo_code", code=code), "warning")
        flash(translate("ok_reset_sent"), "success")
        session["reset_phone"] = phone
        return redirect(url_for("main.reset_password"))
    return render_template("forgot_password.html")


@bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    phone = session.get("reset_phone")
    if not phone:
        return redirect(url_for("main.forgot_password"))
    if request.method == "POST":
        code, pw, cf = f("code"), request.form.get("password", ""), request.form.get("confirm", "")
        if len(pw) < 8 or pw != cf:
            flash(translate("err_password"), "error")
            return render_template("reset_password.html"), 400
        reset = (PasswordReset.query.filter_by(phone=phone, used=False)
                 .order_by(PasswordReset.id.desc()).first())
        valid = bool(reset and reset.expires_at > utcnow() and reset.attempts < 5)
        if valid and hmac.compare_digest(reset.code_hash, code_hash(phone, code)):
            user = User.query.filter_by(phone=phone).first()
            user.set_password(pw)
            reset.used = True
            db.session.commit()
            session.pop("reset_phone", None)
            flash(translate("ok_reset_done"), "success")
            return redirect(url_for("main.login"))
        if valid:
            reset.attempts += 1
            db.session.commit()
        flash(translate("err_code"), "error")
        return render_template("reset_password.html"), 400
    return render_template("reset_password.html")


# ---------------------------------------------------------------- espace membre

@bp.route("/dashboard")
@login_required
def dashboard():
    favorites = (Favorite.query.filter_by(user_id=current_user.id)
                 .order_by(Favorite.created_at.desc()).limit(20).all())
    notifs = (Notification.query.filter(Notification.user_id == current_user.id,
                                        Notification.available_at <= utcnow())
              .order_by(Notification.created_at.desc()).limit(15).all())
    unread = sum(1 for n in notifs if not n.is_read)
    return render_template("dashboard.html", user=current_user, favorites=favorites,
                           notifs=notifs, unread=unread,
                           alerts=SavedAlert.query.filter_by(user_id=current_user.id).all(),
                           simulation=current_app.config["PAYMENT_MODE"] == "simulation")


@bp.post("/profile/update")
@login_required
def update_profile():
    u = current_user
    u.company = f("company")[:150] or None
    u.activity = f("activity") if f("activity") in SECTORS else None
    u.commune = f("commune") if f("commune") in COMMUNE_NAMES else None
    u.keywords = f("keywords")[:300] or None
    u.bio = f("bio")[:1000] or None
    u.telegram_chat_id = f("telegram_chat_id")[:40] or None
    u.public_profile = request.form.get("public_profile") == "on"
    db.session.commit()
    flash(translate("saved_ok"), "success")
    return redirect(url_for("main.dashboard"))


@bp.post("/alerts/new")
@login_required
def alert_new():
    sector, commune, kws = f("sector"), f("commune"), f("keywords")[:300]
    sector = sector if sector in SECTORS else ""
    commune = commune if commune in COMMUNE_NAMES else ""
    if not (sector or commune or kws):
        flash(translate("err_alert_empty"), "error")
    elif SavedAlert.query.filter_by(user_id=current_user.id).count() >= current_user.alert_limit:
        flash(translate("err_alert_limit", n=current_user.alert_limit), "error")
    else:
        db.session.add(SavedAlert(user_id=current_user.id, sector=sector or None,
                                  commune=commune or None, keywords=kws or None))
        db.session.commit()
        flash(translate("alert_created"), "success")
    return redirect(url_for("main.dashboard"))


@bp.post("/alerts/<int:aid>/delete")
@login_required
def alert_delete(aid):
    alert = db.get_or_404(SavedAlert, aid)
    if alert.user_id != current_user.id:
        abort(403)
    db.session.delete(alert)
    db.session.commit()
    return redirect(url_for("main.dashboard"))


@bp.post("/notifications/read")
@login_required
def notifications_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return redirect(url_for("main.dashboard"))


@bp.post("/upgrade")
@login_required
def upgrade():
    if current_user.is_premium:
        return redirect(url_for("main.dashboard"))
    if current_app.config["PAYMENT_MODE"] == "simulation":
        current_user.plan = "premium"
        current_user.premium_until = today_dz() + timedelta(days=current_app.config["PREMIUM_DAYS"])
        current_user.upgrade_requested = False
        flash(translate("upgrade_done"), "success")
    else:
        current_user.upgrade_requested = True
        flash(translate("upgrade_pending"), "success")
    db.session.commit()
    return redirect(url_for("main.dashboard"))


# ---------------------------------------------------------------- réseau local

@bp.route("/partners", methods=["GET", "POST"])
@login_required
def partners():
    if request.method == "POST":
        title, looking = f("tender_title")[:300], f("looking_for")[:300]
        if not title or not looking:
            flash(translate("err_required"), "error")
        else:
            tender = db.session.get(Tender, request.form.get("tender_id", type=int) or 0)
            if tender and tender.locked_for(current_user):
                tender = None
            db.session.add(PartnershipAd(user_id=current_user.id, tender_id=tender.id if tender else None,
                                         tender_title=title, looking_for=looking, message=f("message")[:1000] or None))
            db.session.commit()
            flash(translate("p_posted"), "success")
        return redirect(url_for("main.partners"))
    prefill = None
    if request.args.get("tender", type=int):
        t = db.session.get(Tender, request.args.get("tender", type=int))
        if t and not t.locked_for(current_user):
            prefill = t
    ads = PartnershipAd.query.filter_by(is_open=True).order_by(PartnershipAd.created_at.desc()).limit(60).all()
    return render_template("partners.html", ads=ads, prefill=prefill)


@bp.post("/partners/<int:pid>/close")
@login_required
def partner_close(pid):
    ad = db.get_or_404(PartnershipAd, pid)
    if ad.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    ad.is_open = False
    db.session.commit()
    flash(translate("p_closed"), "success")
    return redirect(url_for("main.partners"))


@bp.route("/directory")
@login_required
def directory():
    q = User.query.filter(User.active.is_(True), User.public_profile.is_(True), User.role != "admin")
    sector, commune = request.args.get("sector", ""), request.args.get("commune", "")
    if sector in SECTORS:
        q = q.filter(User.activity == sector)
    if commune in COMMUNE_NAMES:
        q = q.filter(User.commune == commune)
    return render_template("directory.html", members=q.order_by(User.company, User.full_name).limit(100).all(),
                           args=request.args)


@bp.route("/profile/<int:uid>")
@login_required
def public_profile(uid):
    user = db.get_or_404(User, uid)
    if not user.active or (not user.public_profile and user.id != current_user.id and not current_user.is_admin):
        abort(404)
    ads = Ad.query.filter_by(user_id=uid, is_approved=True).all()
    return render_template("profile.html", member=user, ads=ads)


@bp.route("/ads", methods=["GET", "POST"])
@login_required
def ads():
    if request.method == "POST":
        title, desc, link = f("title")[:200], f("description")[:2000], f("link")[:500]
        if not title or not desc:
            flash(translate("err_required"), "error")
        elif link and not is_http_url(link):
            flash(translate("err_link"), "error")
        else:
            db.session.add(Ad(user_id=current_user.id, title=title, description=desc, link=link or None))
            db.session.commit()
            flash(translate("ad_submitted"), "success")
        return redirect(url_for("main.ads"))
    return render_template(
        "ads.html",
        my_ads=Ad.query.filter_by(user_id=current_user.id).order_by(Ad.created_at.desc()).all(),
        approved=Ad.query.filter_by(is_approved=True).order_by(Ad.created_at.desc()).limit(30).all())


# ---------------------------------------------------------------- administration

@bp.route("/admin")
@admin_required
def admin_panel():
    stats = {
        "users": User.query.count(),
        "premium": User.query.filter_by(plan="premium").count(),
        "tenders": Tender.query.count(),
        "active": Tender.query.filter_by(is_active=True).count(),
    }
    return render_template(
        "admin.html", stats=stats,
        requests_=User.query.filter_by(upgrade_requested=True).all(),
        pending_ads=Ad.query.filter_by(is_approved=False).order_by(Ad.created_at.desc()).all(),
        tenders=Tender.query.order_by(Tender.created_at.desc()).limit(40).all(),
        users=User.query.order_by(User.created_at.desc()).limit(50).all())


@bp.post("/admin/tender/new")
@admin_required
def admin_tender_new():
    deadline = parse_date(f("deadline"))
    try:
        t = upsert_tender({
            "title": f("title"), "agency": f("agency"), "deadline": deadline,
            "sector": f("sector"), "commune": f("commune"), "budget_dzd": parse_budget(f("budget")),
            "source_url": f("source_url"), "description": f("description"), "reference": f("reference")[:100],
        })
    except ValueError:
        flash(translate("err_required"), "error")
        return redirect(url_for("main.admin_panel"))
    flash(translate("tender_added") if t else translate("tender_dup"), "success" if t else "warning")
    return redirect(url_for("main.admin_panel"))


@bp.post("/admin/tender/<int:tid>/<action>")
@admin_required
def admin_tender_action(tid, action):
    tender = db.get_or_404(Tender, tid)
    if action == "toggle":
        tender.is_active = not tender.is_active
    elif action == "delete":
        Favorite.query.filter_by(tender_id=tid).delete()
        Notification.query.filter_by(tender_id=tid).delete()
        PartnershipAd.query.filter_by(tender_id=tid).update({"tender_id": None})
        db.session.delete(tender)
    else:
        abort(404)
    db.session.commit()
    return redirect(url_for("main.admin_panel"))


@bp.post("/admin/import-csv")
@admin_required
def admin_import_csv():
    file = request.files.get("file")
    if not file or not file.filename.lower().endswith(".csv"):
        flash(translate("err_required"), "error")
        return redirect(url_for("main.admin_panel"))
    try:
        text = file.read(2_000_000).decode("utf-8-sig")
    except UnicodeDecodeError:
        flash(translate("err_csv_encoding"), "error")
        return redirect(url_for("main.admin_panel"))
    added, skipped, errors = import_csv(text)
    flash(translate("imported", n=added, s=skipped, e=len(errors)), "success")
    return redirect(url_for("main.admin_panel"))


@bp.post("/admin/sync")
@admin_required
def admin_sync():
    added, err = scrape_configured_source()
    flash(err or translate("sync_result", n=added), "error" if err else "success")
    return redirect(url_for("main.admin_panel"))


@bp.post("/admin/user/<int:uid>/<action>")
@admin_required
def admin_user_action(uid, action):
    user = db.get_or_404(User, uid)
    if action == "approve":
        user.plan, user.upgrade_requested = "premium", False
        user.premium_until = today_dz() + timedelta(days=current_app.config["PREMIUM_DAYS"])
    elif action == "reject":
        user.upgrade_requested = False
    elif action == "downgrade":
        user.plan, user.premium_until = "free", None
    elif action == "toggle" and user.id != current_user.id:
        user.active = not user.active
    else:
        abort(404)
    db.session.commit()
    flash(translate("user_updated"), "success")
    return redirect(url_for("main.admin_panel"))


@bp.post("/admin/ad/<int:aid>/toggle")
@admin_required
def admin_ad_toggle(aid):
    ad = db.get_or_404(Ad, aid)
    ad.is_approved = not ad.is_approved
    db.session.commit()
    return redirect(url_for("main.admin_panel"))


# ---------------------------------------------------------------- API publique & divers

def _api_row(t):
    return {"id": t.id, "title": t.title, "agency": t.agency, "sector": t.sector, "commune": t.commune,
            "budget_dzd": t.budget_dzd, "deadline": t.deadline.isoformat(), "days_left": t.days_left,
            "demo": t.is_demo}


@bp.get("/api/tenders")
def api_tenders():
    limit = min(request.args.get("limit", 50, type=int), 100)
    q = filtered_query(request.args)
    if not is_premium():
        q = q.filter(Tender.created_at <= free_cutoff())
    return jsonify([_api_row(t) for t in q.limit(limit).all()])


@bp.get("/api/stats")
def api_stats():
    return jsonify({"tenders": Tender.query.filter_by(is_active=True).count(),
                    "members": User.query.filter_by(active=True).count(),
                    "version": current_app.config["APP_VERSION"]})


@bp.get("/manifest.json")
def manifest():
    return jsonify({"name": translate("app_name"), "short_name": "Safqa", "start_url": "/",
                    "display": "standalone", "background_color": "#f6f7f9", "theme_color": "#0e7c66"})


@bp.get("/health")
def health():
    return jsonify({"status": "ok"})
