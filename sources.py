# -*- coding: utf-8 -*-
"""Alimentation de la base : saisie admin, import CSV, collecte web configurable, démo."""
import csv
import hashlib
import io
import logging
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup
from flask import current_app
from urllib.parse import urljoin

from constants import (COMMUNE_NAMES, SECTORS, WILAYA_WIDE, classify_sector,
                       commune_from_label, detect_commune, mentions_wilaya,
                       sector_key_from_label)
from models import Tender, db
from notifier import dispatch_new_tender
from utils import is_http_url, normalize_text, parse_budget, parse_date, today_dz, utcnow

logger = logging.getLogger(__name__)


def _fingerprint(title, agency, deadline):
    raw = "|".join([normalize_text(title), normalize_text(agency), deadline.isoformat()])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def upsert_tender(data, *, demo=False, notify=True):
    """Crée une offre (dédoublonnée). Secteur et commune sont auto-détectés si absents.

    Retourne l'offre créée, ou None si elle existait déjà. Lève ValueError si données invalides.
    """
    title = (data.get("title") or "").strip()[:500]
    agency = (data.get("agency") or "").strip()[:200]
    deadline = data.get("deadline")
    if not title or not agency or not isinstance(deadline, date):
        raise ValueError("title, agency et deadline sont obligatoires")

    context = f"{title} {agency} {data.get('description') or ''}"
    sector = data.get("sector") if data.get("sector") in SECTORS else classify_sector(context)
    commune = data.get("commune") if data.get("commune") in COMMUNE_NAMES else detect_commune(context)
    ext = data.get("external_id") or _fingerprint(title, agency, deadline)
    if Tender.query.filter_by(external_id=ext).first():
        return None

    url = data.get("source_url") or ""
    tender = Tender(
        external_id=ext, reference=(data.get("reference") or None), title=title, agency=agency,
        sector=sector, commune=commune, budget_dzd=data.get("budget_dzd"), deadline=deadline,
        source_url=url if is_http_url(url) else None,
        description=(data.get("description") or "").strip() or None,
        is_demo=demo, created_at=data.get("created_at") or utcnow(),
    )
    db.session.add(tender)
    db.session.commit()
    if notify:
        dispatch_new_tender(tender)
    return tender


def import_csv(text):
    """CSV (UTF-8) : title,agency,deadline[,sector,commune,budget,source_url,description,reference]."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    added = skipped = 0
    errors = []
    for n, row in enumerate(reader, start=2):
        if n > 501:
            errors.append("500 lignes maximum par import")
            break
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        deadline = parse_date(row.get("deadline"))
        try:
            t = upsert_tender({
                "title": row.get("title"), "agency": row.get("agency"), "deadline": deadline,
                "sector": sector_key_from_label(row.get("sector", "")),
                "commune": commune_from_label(row.get("commune", "")),
                "budget_dzd": parse_budget(row.get("budget")), "source_url": row.get("source_url"),
                "description": row.get("description"), "reference": row.get("reference"),
            })
        except ValueError:
            errors.append(f"ligne {n}")
            continue
        if t:
            added += 1
        else:
            skipped += 1
    return added, skipped, errors


def scrape_configured_source():
    """Collecte générique pilotée par .env. À adapter aux sélecteurs réels du site visé
    (et à ses conditions d'utilisation). Retourne (ajoutées, message_erreur|None)."""
    cfg = current_app.config
    if not cfg["SCRAPE_URL"]:
        return 0, "SCRAPE_URL non configuré"
    try:
        r = requests.get(cfg["SCRAPE_URL"], timeout=15,
                         headers={"User-Agent": "SafqaBelabbesBot/3.0 (projet etudiant)"})
        r.raise_for_status()
    except requests.RequestException as exc:
        return 0, f"Source injoignable : {exc}"
    soup = BeautifulSoup(r.text, "html.parser")
    added = 0
    for item in soup.select(cfg["SCRAPE_ITEM_SELECTOR"])[:100]:
        a = item.select_one(cfg["SCRAPE_TITLE_SELECTOR"])
        ag = item.select_one(cfg["SCRAPE_AGENCY_SELECTOR"])
        dl = item.select_one(cfg["SCRAPE_DEADLINE_SELECTOR"])
        if not a or not dl:
            continue
        title = a.get_text(" ", strip=True)
        agency = ag.get_text(" ", strip=True) if ag else "—"
        deadline = parse_date(dl.get_text(" ", strip=True))
        if not deadline or not title:
            continue
        if cfg["SCRAPE_ONLY_LOCAL"] and not mentions_wilaya(f"{title} {agency} {item.get_text(' ')}"):
            continue
        link = urljoin(cfg["SCRAPE_URL"], a.get("href", "")) if a.get("href") else cfg["SCRAPE_URL"]
        try:
            if upsert_tender({"title": title, "agency": agency, "deadline": deadline, "source_url": link}):
                added += 1
        except ValueError:
            continue
    return added, None


def seed_demo():
    """Offres fictives à dates relatives (toujours d'actualité). Marquées « DÉMO »."""
    if Tender.query.count() > 0:
        return 0
    today, now = today_dz(), utcnow()
    portal = current_app.config["PORTAL_URL"]
    rows = [
        ("Travaux de réhabilitation de la route reliant Sidi Bel Abbès à Telagh",
         "Direction des Travaux Publics de la wilaya de Sidi Bel Abbès", "Telagh", 45_000_000, 21, timedelta(days=9)),
        ("Acquisition de matériel informatique pour l'université Djillali Liabès",
         "Université Djillali Liabès de Sidi Bel Abbès", "Sidi Bel Abbès", 8_500_000, 12, timedelta(days=4)),
        ("خدمات النظافة والحراسة للمؤسسة الاستشفائية الجامعية", "المؤسسة الاستشفائية الجامعية",
         "Sidi Bel Abbès", 12_000_000, 33, timedelta(days=3)),
        ("Réalisation d'un réseau d'assainissement - commune de Tessala",
         "APC de Tessala", "Tessala", 18_750_000, 27, timedelta(hours=30)),
        ("إنجاز مدرسة ابتدائية 6 أقسام بمدينة سفيزف", "مديرية التجهيزات العمومية", "Sfisef",
         62_000_000, 40, timedelta(hours=20)),
        ("Fourniture de denrées alimentaires pour les cantines scolaires",
         "Direction de l'Éducation de la wilaya de Sidi Bel Abbès", "Toute la wilaya", 6_200_000, 15, timedelta(hours=8)),
        ("Étude et suivi des travaux d'aménagement du marché couvert de Ben Badis",
         "APC de Ben Badis", "Ben Badis", 3_400_000, 18, timedelta(hours=3)),
        ("Maintenance des équipements d'éclairage public - Ras El Ma",
         "APC de Ras El Ma", "Ras El Ma", 2_900_000, 9, timedelta(days=6)),
        ("Entretien et réparation du parc automobile de la wilaya",
         "Secrétariat général de la wilaya", "Sidi Bel Abbès", 5_100_000, 6, timedelta(days=7)),
    ]
    added = 0
    for title, agency, commune, budget, days, age in rows:
        t = upsert_tender({
            "title": title, "agency": agency, "commune": commune, "budget_dzd": budget,
            "deadline": today + timedelta(days=days), "created_at": now - age,
            "source_url": portal, "description": "Offre de démonstration (données fictives).",
        }, demo=True, notify=False)
        added += 1 if t else 0
    return added
