# Safqa Belabbès — صفقة بلعباس

Plateforme de **veille des marchés publics de la wilaya de Sidi Bel Abbès** (projet de fin d'études / startup).
Interface bilingue **français / arabe** (RTL automatique), responsive.

## Ce qui rend le projet différent

| Fonction | Intérêt |
|---|---|
| **Alertes sur mesure** (secteur + commune + mots-clés) | L'utilisateur est prévenu dès qu'une offre correspond à son métier, plus besoin de surveiller les journaux. |
| **Score de pertinence** (0-100, expliqué) | Chaque offre est notée selon le profil de l'entreprise (secteur, commune, mots-clés). |
| **Détection automatique** du secteur et de la commune (FR + AR) | Les offres importées sont classées toutes seules ; les 52 communes de la wilaya sont gérées. |
| **Groupements** : annonces de recherche de partenaires + annuaire local | Aide les petites entreprises à soumissionner ensemble (contact tel / WhatsApp). |
| **Freemium** : offres récentes différées de 48 h (gratuit) vs accès immédiat + Telegram (Premium) | Modèle économique clair pour le business plan. |
| Statistiques locales, annonces gratuites modérées, récupération du mot de passe par SMS | |

## Lancer le projet (GitHub Codespaces ou en local)

```bash
cp .env.example .env          # (Codespaces le fait automatiquement)
pip install -r requirements.txt
python app.py                 # http://localhost:5000
```

Dans **Codespaces** : ouvrez l'onglet *Ports* → port 5000 → ouvrir dans le navigateur.
Au premier lancement, le compte admin est créé (`ADMIN_EMAIL` dans `.env`). Si `ADMIN_PASSWORD` est vide, un mot de passe est
généré et **affiché dans le terminal**.

Des offres de **démonstration** (marquées « DÉMO ») sont ajoutées si la base est vide. Désactivez-les avec `DEMO_DATA=false`.

Tests : `python -m pytest -q`

## Alimenter la plateforme en vraies offres

1. **Saisie manuelle** : *Admin → Ajouter une offre* (secteur/commune auto-détectés).
2. **Import CSV** : *Admin → Importer un CSV* — colonnes `title, agency, deadline, sector, commune, budget, source_url, description, reference`.
3. **Collecte automatique** : renseignez `SCRAPE_URL` et les sélecteurs CSS dans `.env`, puis *Admin → Lancer la collecte*
   (ou `flask --app app:create_app sync-source`). ⚠️ Les sélecteurs doivent être adaptés à la structure réelle du site visé ;
   respectez ses conditions d'utilisation. Planifiez la commande avec un cron / GitHub Actions.

Chaque nouvelle offre déclenche les alertes : notification in-app (différée de 48 h pour les comptes gratuits) et message Telegram
pour les Premium.

## Configuration importante

- **SMS** : `SMS_MODE=demo` affiche le code à l'écran (démo uniquement). En production : `webhook` + `SMS_WEBHOOK_URL`
  vers votre passerelle SMS.
- **Paiement** : `PAYMENT_MODE=simulation` active Premium immédiatement (démo). `manual` : l'admin valide les demandes.
- **Telegram** : créez un bot avec @BotFather, mettez `TELEGRAM_TOKEN`. Chaque Premium saisit son chat ID dans son espace.
- **Production** : `APP_ENV=production`, `SECRET_KEY` aléatoire, `DEMO_DATA=false`, base PostgreSQL via `DATABASE_URL`,
  démarrage `gunicorn wsgi:app` (voir `Procfile`).

## Structure

```
app.py          fabrique Flask, erreurs, commandes CLI      views.py     routes
models.py       base de données                             matching.py  score & correspondance alertes
sources.py      saisie / CSV / collecte / démo              notifier.py  Telegram, SMS, notifications
constants.py    secteurs, communes (FR/AR), détection       i18n.py      traductions FR/AR
templates/ static/ tests/
```

## Sécurité (corrigée par rapport aux versions précédentes)

CSRF sur tous les formulaires · actions admin en POST · mot de passe ≥ 8 caractères · codes SMS hachés, 5 essais, 15 min ·
limitation des tentatives de connexion · pas d'énumération de comptes · redirections internes uniquement ·
plus d'identifiants affichés sur la page de connexion · offres verrouillées jamais exposées (HTML, recherche, API).

## Limites connues / pistes

- La liste des communes (`constants.py`) est à vérifier avec l'annuaire officiel.
- Le limiteur de tentatives est en mémoire (par processus) : utilisez Redis si vous déployez plusieurs workers.
- Pas de passerelle de paiement réelle (CIB/Edahabia à intégrer via un prestataire agréé).
- Pistes : export iCal des échéances, application mobile (PWA), résumé hebdomadaire par email, IA pour résumer les cahiers des charges.
