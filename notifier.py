# -*- coding: utf-8 -*-
"""Envoi d'alertes : notifications in-app, Telegram (Premium) et SMS (réinitialisation)."""
import logging

import requests
from flask import current_app

from matching import alert_matches
from models import Notification, SavedAlert, User, db
from utils import utcnow

logger = logging.getLogger(__name__)


def send_sms(phone, text):
    """Modes : console (log), demo (log, le code est affiché à l'écran), webhook (passerelle SMS)."""
    cfg = current_app.config
    mode = cfg["SMS_MODE"]
    if mode in {"console", "demo"}:
        logger.info("SMS -> %s : %s", phone, text)
        return True
    if mode == "webhook" and cfg["SMS_WEBHOOK_URL"]:
        headers = {}
        if cfg["SMS_WEBHOOK_TOKEN"]:
            headers["Authorization"] = f"Bearer {cfg['SMS_WEBHOOK_TOKEN']}"
        try:
            r = requests.post(cfg["SMS_WEBHOOK_URL"], json={"to": phone, "message": text},
                              headers=headers, timeout=10)
            return r.ok
        except requests.RequestException as exc:
            logger.error("SMS webhook : %s", exc)
    return False


def send_telegram(chat_id, text):
    token = current_app.config["TELEGRAM_TOKEN"]
    if not token or not chat_id:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=10,
        )
        return r.ok
    except requests.RequestException as exc:
        logger.error("Telegram : %s", exc)
        return False


def dispatch_new_tender(tender):
    """Crée les notifications des utilisateurs dont une alerte correspond à la nouvelle offre.

    Premium : disponible tout de suite (+ Telegram). Gratuit : après le délai d'attente.
    """
    alerts = SavedAlert.query.join(User).filter(User.active.is_(True)).all()
    seen, created = set(), 0
    base = current_app.config["PUBLIC_BASE_URL"]
    for alert in alerts:
        if alert.user_id in seen or not alert_matches(alert, tender):
            continue
        seen.add(alert.user_id)
        user = alert.user
        available = utcnow() if user.is_premium else tender.unlock_at
        db.session.add(Notification(user_id=user.id, tender_id=tender.id, available_at=available))
        created += 1
        if user.is_premium and user.telegram_chat_id:
            send_telegram(
                user.telegram_chat_id,
                f"📢 {tender.title}\n{tender.agency}\n⏳ {tender.deadline:%d/%m/%Y}\n"
                f"{base}/tender/{tender.id}",
            )
    db.session.commit()
    return created
