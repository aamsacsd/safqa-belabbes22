# -*- coding: utf-8 -*-
"""Safqa Belabbès — veille des marchés publics de la wilaya de Sidi Bel Abbès."""
import logging
import os
import secrets

import click
from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager
from flask_wtf.csrf import CSRFError, CSRFProtect, generate_csrf
from markupsafe import Markup

from config import Config
from constants import COMMUNE_AR, COMMUNES, SECTORS
from i18n import LANGS, current_lang, translate
from models import User, db
from sources import scrape_configured_source, seed_demo
from utils import today_dz, whatsapp_link

csrf = CSRFProtect()
login_manager = LoginManager()


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    if not app.config["SECRET_KEY"]:
        if app.config["ENV"] == "production":
            raise RuntimeError("SECRET_KEY obligatoire en production (voir .env.example).")
        app.config["SECRET_KEY"] = "dev-only-insecure-key"

    logging.basicConfig(level=logging.INFO)
    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "main.login"

    @login_manager.user_loader
    def load_user(uid):
        user = db.session.get(User, int(uid))
        return user if user and user.active else None

    @login_manager.unauthorized_handler
    def unauthorized():
        flash(translate("login_required"), "warning")
        return redirect(url_for("main.login", next=request.full_path.rstrip("?")))

    _register_template_helpers(app)

    from views import bp
    app.register_blueprint(bp)
    _register_errors(app)
    _register_cli(app)

    with app.app_context():
        db.create_all()
        _bootstrap_admin(app)
        if app.config["DEMO_DATA"]:
            seed_demo()
    return app


def _register_template_helpers(app):
    app.jinja_env.globals["csrf_input"] = lambda: Markup(
        f'<input type="hidden" name="csrf_token" value="{generate_csrf()}">')

    @app.template_filter("budget")
    def fmt_budget(value):
        if value is None:
            return translate("budget_undefined")
        unit = "دج" if current_lang() == "ar" else "DA"
        return f"{value:,}".replace(",", " ") + f" {unit}"

    @app.template_filter("dmy")
    def fmt_date(value):
        return value.strftime("%d/%m/%Y") if value else "—"

    @app.context_processor
    def inject():
        lang = current_lang()
        return {
            "tr": translate,
            "lang": lang,
            "dir": "rtl" if lang == "ar" else "ltr",
            "other_lang": "ar" if lang == "fr" else "fr",
            "sector_label": lambda k: SECTORS.get(k, {}).get(lang, k or "—"),
            "commune_label": lambda c: COMMUNE_AR.get(c, c) if lang == "ar" else (c or "—"),
            "sectors": SECTORS,
            "communes": COMMUNES,
            "wa": whatsapp_link,
            "today": today_dz(),
            "app_version": app.config["APP_VERSION"],
            "premium_price": app.config["PREMIUM_PRICE_DZD"],
            "delay_hours": app.config["FREE_PLAN_DELAY_HOURS"],
        }


def _register_errors(app):
    def page(code, key):
        return render_template("error.html", code=code, message=translate(key)), code

    @app.errorhandler(403)
    def forbidden(_):
        return page(403, "err_forbidden")

    @app.errorhandler(404)
    def not_found(_):
        return page(404, "err_notfound")

    @app.errorhandler(500)
    def server_error(_):
        db.session.rollback()
        return page(500, "err_server")

    @app.errorhandler(CSRFError)
    def csrf_error(_):
        return page(400, "err_csrf")


def _bootstrap_admin(app):
    if User.query.filter_by(role="admin").first():
        return
    cfg = app.config
    password = cfg["ADMIN_PASSWORD"]
    generated = not password
    if generated:
        password = secrets.token_urlsafe(10)
    admin = User(full_name="Administrateur", email=cfg["ADMIN_EMAIL"], phone=cfg["ADMIN_PHONE"],
                 role="admin", plan="premium", public_profile=False)
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    if generated:
        print(f"\n[Safqa] Compte admin créé : {cfg['ADMIN_EMAIL']} / {password}\n"
              "        (définissez ADMIN_PASSWORD dans .env pour choisir le vôtre)\n", flush=True)


def _register_cli(app):
    @app.cli.command("seed-demo")
    def seed_demo_cmd():
        """Ajoute les offres de démonstration si la base est vide."""
        click.echo(f"{seed_demo()} offres de démonstration ajoutées")

    @app.cli.command("sync-source")
    def sync_cmd():
        """Lance la collecte configurée (SCRAPE_URL)."""
        added, err = scrape_configured_source()
        click.echo(err or f"{added} nouvelles offres")


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")),
                     debug=os.getenv("FLASK_DEBUG") == "1")
