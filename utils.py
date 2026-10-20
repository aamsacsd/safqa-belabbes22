# -*- coding: utf-8 -*-
"""Fonctions utilitaires : dates (heure d'Alger), normalisation FR/AR, téléphones, URLs."""
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

try:
    from zoneinfo import ZoneInfo

    DZ_TZ = ZoneInfo("Africa/Algiers")
except Exception:  # tzdata absent
    DZ_TZ = timezone(timedelta(hours=1))


def utcnow():
    """Date/heure UTC « naïve » (compatible SQLAlchemy, sans avertissement de dépréciation)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today_dz():
    return datetime.now(DZ_TZ).date()


_AR_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_text(text):
    """Minuscules, sans accents ni voyelles arabes, alef/ya unifiés : pour comparer FR et AR."""
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.translate(_AR_MAP).lower()
    s = s.replace("’", "'").replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


def normalize_phone(raw):
    """Retourne un mobile algérien au format 0XXXXXXXXX, ou None s'il est invalide."""
    s = re.sub(r"[\s\-\.\(\)]", "", (raw or "")).translate(_DIGITS)
    if s.startswith("+213"):
        s = "0" + s[4:]
    elif s.startswith("00213"):
        s = "0" + s[5:]
    elif s.startswith("213") and len(s) == 12:
        s = "0" + s[3:]
    return s if re.fullmatch(r"0[5-7]\d{8}", s) else None


def whatsapp_link(phone):
    return "https://wa.me/213" + phone[1:] if phone and phone.startswith("0") else None


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y")


def parse_date(raw):
    s = (raw or "").strip().translate(_DIGITS)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_budget(raw):
    digits = re.sub(r"\D", "", (raw or "").translate(_DIGITS))
    return int(digits) if digits else None


def is_http_url(url):
    try:
        p = urlparse(url or "")
    except ValueError:
        return False
    return p.scheme in {"http", "https"} and bool(p.netloc)


def safe_next_url(target):
    """N'autorise que les redirections internes (évite l'open redirect)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


def like_escape(term):
    return term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
