# -*- coding: utf-8 -*-
"""Moteur de pertinence : score offre ↔ profil, et correspondance offre ↔ alerte."""
from constants import WILAYA_WIDE
from utils import normalize_text


def _haystack(tender):
    return normalize_text(f"{tender.title} {tender.agency} {tender.description or ''}")


def keyword_hits(keywords, tender):
    hay = _haystack(tender)
    hits = []
    for kw in keywords:
        nk = normalize_text(kw)
        if len(nk) >= 3 and nk in hay:
            hits.append(kw)
    return hits


def score_tender(user, tender):
    """Score 0-100 expliqué. Seuls les critères renseignés dans le profil comptent.

    Secteur 40 pts · commune 30 pts (20 si l'offre couvre toute la wilaya) · mots-clés 30 pts.
    Retourne (None, []) si le profil est vide.
    """
    max_pts, pts, reasons = 0, 0, []
    if user.activity:
        max_pts += 40
        if user.activity == tender.sector:
            pts += 40
            reasons.append(("sector", None))
    if user.commune and user.commune != WILAYA_WIDE:
        max_pts += 30
        if tender.commune == user.commune:
            pts += 30
            reasons.append(("commune", None))
        elif tender.commune == WILAYA_WIDE:
            pts += 20
            reasons.append(("wilaya", None))
    kws = user.keyword_list
    if kws:
        max_pts += 30
        hits = keyword_hits(kws, tender)
        if hits:
            pts += 20 if len(hits) == 1 else 30
            reasons.append(("keyword", ", ".join(hits)))
    if max_pts == 0:
        return None, []
    return round(100 * pts / max_pts), reasons


def alert_matches(alert, tender):
    if alert.sector and alert.sector != tender.sector:
        return False
    if alert.commune and alert.commune != WILAYA_WIDE:
        if tender.commune not in (alert.commune, WILAYA_WIDE):
            return False
    kws = alert.keyword_list
    if kws and not keyword_hits(kws, tender):
        return False
    return True
