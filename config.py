# -*- coding: utf-8 -*-
"""Configuration centralisée (variables d'environnement / fichier .env)."""
import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _db_url():
    url = os.getenv("DATABASE_URL", "sqlite:///safqa.db")
    if url.startswith("postgres://"):  # Heroku / Render
        url = url.replace("postgres://", "postgresql://", 1)
    return url


ENV = os.getenv("APP_ENV", "development").lower()


class Config:
    APP_VERSION = "3.0.0"
    ENV = ENV
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    SQLALCHEMY_DATABASE_URI = _db_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = ENV == "production"

    # Modèle économique (freemium)
    FREE_PLAN_DELAY_HOURS = _int("FREE_PLAN_DELAY_HOURS", 48)
    PREMIUM_PRICE_DZD = _int("PREMIUM_PRICE_DZD", 1500)
    PREMIUM_DAYS = _int("PREMIUM_DAYS", 30)
    FREE_ALERT_LIMIT = _int("FREE_ALERT_LIMIT", 3)
    PREMIUM_ALERT_LIMIT = _int("PREMIUM_ALERT_LIMIT", 20)
    # "manual" : l'admin valide les demandes / "simulation" : activation immédiate (démo PFE)
    PAYMENT_MODE = os.getenv("PAYMENT_MODE", "manual").lower()

    # Compte administrateur créé au premier lancement
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@safqa.dz").strip().lower()
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
    ADMIN_PHONE = os.getenv("ADMIN_PHONE", "0500000000")

    # Données de démonstration (clairement marquées « DÉMO » dans l'interface)
    DEMO_DATA = _bool("DEMO_DATA", ENV != "production")

    # Notifications
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000").rstrip("/")
    # SMS : console (log serveur) | demo (log + code affiché à l'écran) | webhook (passerelle SMS)
    SMS_MODE = os.getenv("SMS_MODE", "console").lower()
    SMS_WEBHOOK_URL = os.getenv("SMS_WEBHOOK_URL", "")
    SMS_WEBHOOK_TOKEN = os.getenv("SMS_WEBHOOK_TOKEN", "")

    # Collecte automatique (à adapter à la structure réelle du site source)
    PORTAL_URL = os.getenv("PORTAL_URL", "https://www.marches-publics.gov.dz/")
    SCRAPE_URL = os.getenv("SCRAPE_URL", "")
    SCRAPE_ITEM_SELECTOR = os.getenv("SCRAPE_ITEM_SELECTOR", "article")
    SCRAPE_TITLE_SELECTOR = os.getenv("SCRAPE_TITLE_SELECTOR", "h2 a, h3 a, a")
    SCRAPE_AGENCY_SELECTOR = os.getenv("SCRAPE_AGENCY_SELECTOR", ".agency")
    SCRAPE_DEADLINE_SELECTOR = os.getenv("SCRAPE_DEADLINE_SELECTOR", ".deadline")
    SCRAPE_ONLY_LOCAL = _bool("SCRAPE_ONLY_LOCAL", True)

    ITEMS_PER_PAGE = 12
