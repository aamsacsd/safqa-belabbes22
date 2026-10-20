# -*- coding: utf-8 -*-
"""Référentiels locaux : secteurs, communes de la wilaya de Sidi Bel Abbès, mots-clés."""
import re

from utils import normalize_text

SECTORS = {
    "travaux": {"fr": "Travaux", "ar": "أشغال"},
    "fournitures": {"fr": "Fournitures", "ar": "لوازم"},
    "services": {"fr": "Services", "ar": "خدمات"},
    "etudes": {"fr": "Études", "ar": "دراسات"},
}

# Ordre = priorité de détection (« étude et suivi des travaux » -> études)
SECTOR_KEYWORDS = {
    "etudes": ["etude", "suivi", "controle technique", "expertise", "maitrise d'oeuvre", "audit",
               "دراسه", "دراسة", "متابعه", "مراقبه", "خبره", "تدقيق"],
    "services": ["nettoyage", "gardiennage", "maintenance", "transport", "restauration", "formation",
                 "location", "entretien", "خدمات", "نظافه", "حراسه", "صيانه", "نقل", "اطعام", "تكوين", "كراء"],
    "fournitures": ["fourniture", "acquisition", "approvisionnement", "equipement", "materiel", "achat",
                    "اقتناء", "توريد", "تجهيز", "معدات", "لوازم", "شراء"],
    "travaux": ["travaux", "realisation", "construction", "amenagement", "rehabilitation", "route",
                "voirie", "reseau", "renovation", "اشغال", "انجاز", "تهيئه", "ترميم", "بناء", "طريق", "تعبيد"],
}

WILAYA_WIDE = "Toute la wilaya"
WILAYA_WIDE_AR = "كامل الولاية"

# Liste à vérifier/compléter avec l'annuaire officiel des communes de la wilaya.
COMMUNES = [
    (WILAYA_WIDE, WILAYA_WIDE_AR),
    ("Sidi Bel Abbès", "سيدي بلعباس"),
    ("Amarnas", "عمارنة"),
    ("Aïn Adden", "عين أذن"),
    ("Aïn Kada", "عين قادة"),
    ("Aïn Thrid", "عين ثريد"),
    ("Aïn Tindamine", "عين تندمين"),
    ("Badredine El Mokrani", "بدر الدين المقراني"),
    ("Belarbi", "بلعربي"),
    ("Ben Badis", "بن باديس"),
    ("Benachiba Chelia", "بن عشيبة شلية"),
    ("Bir El Hammam", "بئر الحمام"),
    ("Boudjebaa El Bordj", "بوجبع البرج"),
    ("Boukhanafis", "بوخنفيس"),
    ("Chettouane Belaila", "شتوان بلايلة"),
    ("Dhaya", "ضاية"),
    ("El Haçaiba", "الحصيبة"),
    ("Hassi Dahou", "حاسي دحو"),
    ("Hassi Zahana", "حاسي زهانة"),
    ("Lamtar", "لمطار"),
    ("Makedra", "مقدرة"),
    ("Marhoum", "مرحوم"),
    ("Mcid", "مسيد"),
    ("Mérine", "مرين"),
    ("Mezaourou", "مزاورو"),
    ("Moulay Slissen", "مولاي سليسن"),
    ("Mostefa Ben Brahim", "مصطفى بن براهيم"),
    ("Oued Sbaa", "وادي السبع"),
    ("Oued Sefioun", "وادي صفيوم"),
    ("Oued Taourira", "وادي تاوريرة"),
    ("Ras El Ma", "رأس الماء"),
    ("Redjem Demouche", "رجم دموش"),
    ("Sehala Thaoura", "سهالة ثاورة"),
    ("Sfisef", "سفيزف"),
    ("Sidi Ali Benyoub", "سيدي علي بن يوب"),
    ("Sidi Ali Boussidi", "سيدي علي بوسيدي"),
    ("Sidi Brahim", "سيدي ابراهيم"),
    ("Sidi Chaib", "سيدي شعيب"),
    ("Sidi Dahou Ed Dairaa", "سيدي دحو الضاية"),
    ("Sidi Hamadouche", "سيدي حمادوش"),
    ("Sidi Lahcene", "سيدي لحسن"),
    ("Sidi Yacoub", "سيدي يعقوب"),
    ("Tabia", "تابية"),
    ("Tafissour", "تفسور"),
    ("Taoudmout", "تودمونت"),
    ("Teghalimet", "تغاليمت"),
    ("Telagh", "تلاغ"),
    ("Tessala", "تسالة"),
    ("Tilmouni", "تلموني"),
    ("Ténira", "تنيرة"),
    ("Zerouala", "زروالة"),
]
COMMUNE_NAMES = [c[0] for c in COMMUNES]
COMMUNE_AR = dict(COMMUNES)

_NORM_COMMUNES = sorted(
    ((normalize_text(fr), fr) for fr, _ in COMMUNES[1:]), key=lambda x: -len(x[0])
) + sorted(
    ((normalize_text(ar), fr) for fr, ar in COMMUNES[1:]), key=lambda x: -len(x[0])
)

_WILAYA_PHRASES = re.compile(
    "|".join(
        [
            r"wilaya (de |d')?sidi bel abbes",
            normalize_text("ولاية سيدي بلعباس"),
        ]
    )
)


def sector_key_from_label(label):
    n = normalize_text(label)
    for key, names in SECTORS.items():
        if n in {key, normalize_text(names["fr"]), normalize_text(names["ar"])}:
            return key
    return None


def commune_from_label(label):
    n = normalize_text(label)
    for fr, ar in COMMUNES:
        if n in {normalize_text(fr), normalize_text(ar)}:
            return fr
    return None


def classify_sector(text):
    n = normalize_text(text)
    for key, words in SECTOR_KEYWORDS.items():
        if any(normalize_text(w) in n for w in words):
            return key
    return "services"


def detect_commune(text):
    """Cherche le nom d'une commune dans un texte FR/AR ; sinon « toute la wilaya »."""
    n = _WILAYA_PHRASES.sub(" ", normalize_text(text))
    for norm, fr in _NORM_COMMUNES:
        if re.search(rf"(?<!\w){re.escape(norm)}(?!\w)", n):
            return fr
    return WILAYA_WIDE


def mentions_wilaya(text):
    n = normalize_text(text)
    if "sidi bel abbes" in n or normalize_text("سيدي بلعباس") in n:
        return True
    return detect_commune(text) != WILAYA_WIDE
