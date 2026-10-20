# -*- coding: utf-8 -*-
"""Modèles de données."""
import re
from datetime import timedelta

from flask import current_app
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

from utils import today_dz, utcnow

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(20), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(150))
    activity = db.Column(db.String(30))          # clé de secteur (travaux, fournitures...)
    commune = db.Column(db.String(100))
    keywords = db.Column(db.String(300))         # mots-clés du profil (score de pertinence)
    bio = db.Column(db.Text)
    public_profile = db.Column(db.Boolean, default=True, nullable=False)
    telegram_chat_id = db.Column(db.String(40))
    role = db.Column(db.String(20), default="user", nullable=False)
    plan = db.Column(db.String(20), default="free", nullable=False)
    premium_until = db.Column(db.Date)
    upgrade_requested = db.Column(db.Boolean, default=False, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    alerts = db.relationship("SavedAlert", backref="user", cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):  # Flask-Login
        return self.active

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_premium(self):
        if self.role == "admin":
            return True
        if self.plan != "premium":
            return False
        return self.premium_until is None or self.premium_until >= today_dz()

    @property
    def keyword_list(self):
        return [k.strip() for k in re.split(r"[,;،\n]", self.keywords or "") if len(k.strip()) >= 3]

    @property
    def alert_limit(self):
        key = "PREMIUM_ALERT_LIMIT" if self.is_premium else "FREE_ALERT_LIMIT"
        return current_app.config[key]


class Tender(db.Model):
    __tablename__ = "tenders"
    id = db.Column(db.Integer, primary_key=True)
    external_id = db.Column(db.String(64), unique=True, index=True, nullable=False)
    reference = db.Column(db.String(100))
    title = db.Column(db.String(500), nullable=False)
    agency = db.Column(db.String(200), nullable=False)
    sector = db.Column(db.String(30), nullable=False, index=True)
    commune = db.Column(db.String(100), nullable=False, index=True)
    budget_dzd = db.Column(db.BigInteger)
    deadline = db.Column(db.Date, nullable=False, index=True)
    source_url = db.Column(db.String(500))
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)

    @property
    def days_left(self):
        return (self.deadline - today_dz()).days

    @property
    def urgency(self):
        d = self.days_left
        if d < 0:
            return "expired"
        if d <= 3:
            return "urgent"
        if d <= 10:
            return "soon"
        return "ok"

    @property
    def is_new(self):
        return utcnow() - self.created_at <= timedelta(hours=72)

    @property
    def unlock_at(self):
        return self.created_at + timedelta(hours=current_app.config["FREE_PLAN_DELAY_HOURS"])

    @property
    def hours_until_unlock(self):
        delta = self.unlock_at - utcnow()
        return max(0, int(delta.total_seconds() // 3600) + 1)

    def locked_for(self, user):
        """Une offre récente est réservée aux Premium pendant FREE_PLAN_DELAY_HOURS."""
        if user is not None and getattr(user, "is_authenticated", False) and user.is_premium:
            return False
        return utcnow() < self.unlock_at


class SavedAlert(db.Model):
    """Alerte enregistrée : secteur + commune + mots-clés."""
    __tablename__ = "saved_alerts"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    sector = db.Column(db.String(30))
    commune = db.Column(db.String(100))
    keywords = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    @property
    def keyword_list(self):
        return [k.strip() for k in re.split(r"[,;،\n]", self.keywords or "") if len(k.strip()) >= 3]


class Favorite(db.Model):
    __tablename__ = "favorites"
    __table_args__ = (db.UniqueConstraint("user_id", "tender_id", name="uq_fav"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    tender_id = db.Column(db.Integer, db.ForeignKey("tenders.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    tender = db.relationship("Tender")


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    tender_id = db.Column(db.Integer, db.ForeignKey("tenders.id"), nullable=False)
    available_at = db.Column(db.DateTime, nullable=False)   # différé pour les comptes gratuits
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    tender = db.relationship("Tender")


class Ad(db.Model):
    """Annonce gratuite d'un organisme / d'une entreprise (modérée par l'admin)."""
    __tablename__ = "ads"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(500))
    is_approved = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    user = db.relationship("User")


class PartnershipAd(db.Model):
    """Recherche de partenaire pour un groupement momentané d'entreprises."""
    __tablename__ = "partnership_ads"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    tender_id = db.Column(db.Integer, db.ForeignKey("tenders.id"))
    tender_title = db.Column(db.String(300), nullable=False)
    looking_for = db.Column(db.String(300), nullable=False)
    message = db.Column(db.Text)
    is_open = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    user = db.relationship("User")
    tender = db.relationship("Tender")


class PasswordReset(db.Model):
    """Code de réinitialisation par SMS (stocké haché, 5 essais max)."""
    __tablename__ = "password_resets"
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), nullable=False, index=True)
    code_hash = db.Column(db.String(64), nullable=False)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
