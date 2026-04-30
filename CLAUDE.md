# Bahn-Ausfall-Tracker — CLAUDE.md

## Projekt-Übersicht

App beobachtet alle ICE/IC-Verbindungen zwischen zwei Bahnhöfen über einen
wählbaren Zeitraum und berechnet die Wahrscheinlichkeit eines Ausfalls oder
verpassten Anschlusses. Hintergrund: bei Sparpreis-Tickets entfällt die
Zugbindung bei Ausfall — die Statistik hilft, diese Wahrscheinlichkeit
einzuschätzen.

**Stack**: Python 3.12 + Streamlit + MariaDB, Docker-Compose auf Ubuntu-Mini-PC.

---

## Architektur

```
streamlit (:8501)  ←→  mariadb (:3306)  ←→  tracker (APScheduler)
                                                    ↓ HTTPS
                                          v6.db.transport.rest  (Routing, kein Auth)
                                          apis.deutschebahn.com (Timetables API, Header-Auth)
```

Drei Docker-Services: `mariadb`, `tracker`, `streamlit`.

---

## Verzeichnisstruktur

```
bahnapp/
├── docker-compose.yml
├── Dockerfile
├── .env.example          # Vorlage — echte Werte in .env (gitignored)
├── pyproject.toml
├── src/bahnapp/
│   ├── config.py         # pydantic Settings aus .env
│   ├── auth/
│   │   └── google_oidc.py    # Google OAuth OIDC + E-Mail-Allowlist
│   ├── db/
│   │   ├── models.py         # SQLAlchemy-Modelle
│   │   ├── session.py        # Engine + session_scope()
│   │   └── migrations.sql    # Initiales Schema (via docker-entrypoint)
│   ├── db_api/
│   │   ├── auth.py           # DB-Client-Id / DB-Api-Key Header-Auth
│   │   ├── timetables.py     # /plan + /fchg XML-Parser (lxml)
│   │   └── stations.py       # Stations-Suche (transport.rest)
│   ├── routing/
│   │   ├── transport_rest.py # /journeys (paginiert) + /locations
│   │   └── normalize.py      # HAFAS-JSON → NormalizedReise/Etappe
│   ├── tracker/
│   │   ├── main.py           # APScheduler-Entrypoint
│   │   ├── discovery.py      # Tages-Discovery + rollierendes Fenster
│   │   ├── scheduler.py      # Etappe → poll_tasks (15-Min-Bucket)
│   │   ├── poller.py         # Poll-Worker (fällige Tasks abarbeiten)
│   │   ├── classifier.py     # Etappen-Status aus StopEvents
│   │   └── aggregator.py     # Reise-Outage aus Etappen
│   └── ui/
│       ├── app.py            # Streamlit-Startseite + Login-Gate
│       ├── _shared.py        # gate()-Helper für Pages
│       └── pages/
│           ├── 01_neuer_job.py
│           ├── 02_aktive_jobs.py
│           └── 03_statistik.py
└── tests/
    ├── test_xml_parser.py
    ├── test_classifier.py
    ├── test_aggregator.py
    ├── test_normalize.py
    └── test_scheduler.py
```

---

## Datenmodell (Kurzform)

| Tabelle | Zweck |
|---|---|
| `stations` | EVA-Nr + Name |
| `tracking_jobs` | Verbindung A→B, Zeitraum, Filter |
| `reisen` | eine konkrete Verbindung an einem Tag |
| `reise_etappen` | ein Zug innerhalb einer Reise |
| `poll_tasks` | geplante Polls (dedupliziert per 15-Min-Bucket) |
| `poll_task_etappen` | m:n: Etappe ↔ PollTask |

`reisen.outage_state`: `pending` → `on_time` / `delayed` / `outage`
`reisen.outage_reason`: `etappe_cancelled` / `stop_cancelled` / `arr_delay_60` / `anschluss_verpasst`

---

## Tracking-Logik

- **Discovery** läuft täglich 04:00 Uhr lokal + beim Anlegen eines Jobs sofort
- **Rollierendes Fenster**: heute + `DISCOVERY_LOOKAHEAD_DAYS` (Default 2) Tage,
  begrenzt auf `[job.start_date, job.end_date]`
- **Poll-Tasks**: pro Etappe 6 Tasks (pre_dep_60, pre_dep_5, post_dep_5,
  pre_arr_5, post_arr_5, post_arr_30), auf 15-Min-Bucket gerundet,
  stationsübergreifend dedupliziert
- **Poll-Worker**: läuft alle 60 s, nimmt fällige Tasks, ruft /plan + /fchg
  der DB Timetables API, aktualisiert Etappen-Status + Reise-Aggregat

---

## Konfiguration (.env)

```
DB_API_CLIENT_ID=          # DB API Marketplace → App → Consumer Key
DB_API_CLIENT_SECRET=      # DB API Marketplace → App → Consumer Secret
DB_API_BASE_URL=https://apis.deutschebahn.com
TRANSPORT_REST_BASE_URL=https://v6.db.transport.rest

MARIADB_HOST=mariadb
MARIADB_DATABASE=bahnapp
MARIADB_USER=bahnapp
MARIADB_PASSWORD=
MARIADB_ROOT_PASSWORD=

POLL_WORKER_INTERVAL_SECONDS=60
DISCOVERY_HOUR_LOCAL=4
DISCOVERY_LOOKAHEAD_DAYS=2
DEFAULT_MAX_UMSTIEGE=2

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8501/
ALLOWED_EMAILS=           # kommagetrennte Gmail-Adressen
SESSION_SECRET_KEY=       # openssl rand -hex 32
LOG_LEVEL=INFO
TZ=Europe/Berlin
```

Wenn `GOOGLE_CLIENT_ID` leer ist → Dev-Modus (Login wird übersprungen,
User ist `dev@local`).

---

## Lokale Entwicklung

```bash
# Tests ausführen
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
PYTHONPATH=src .venv/bin/pytest -q

# App starten
docker compose up --build -d
docker compose logs -f tracker     # Tracker-Logs
docker compose logs -f streamlit   # UI-Logs

# Nach Code-Änderungen
git pull
docker compose restart streamlit tracker
```

---

## Bekannte Fixes (bereits eingespielt)

| Problem | Fix | Datei |
|---|---|---|
| `src/` fehlte beim `pip install .` im Docker-Build | COPY-Reihenfolge korrigiert | `Dockerfile` |
| `type == "stop"` filterte alle Treffer weg | Filter auf `id + name` gelockert | `routing/transport_rest.py`, `db_api/stations.py` |

---

## Offene Punkte / nächste Schritte

- [ ] Ersten Job anlegen und Discovery-Lauf prüfen
      (`docker compose logs -f tracker`)
- [ ] Verifikation: `reisen` + `poll_tasks` in DB nach Discovery
      (`docker compose exec mariadb mysql -u bahnapp -pPASSWORD bahnapp -e "SELECT COUNT(*) FROM reisen;"`)
- [ ] Google OAuth testen (wenn `GOOGLE_CLIENT_ID` gesetzt)
- [ ] Statistik-Seite nach einigen finalisieren Reisen prüfen
- [ ] HTTPS / Reverse-Proxy für Zugriff aus dem Heimnetz (optional)

---

## Git-Branch

Aktiver Branch: `claude/train-outage-tracker-QTMia`
Remote: `hirsekekx/bahnapp`

```bash
git checkout claude/train-outage-tracker-QTMia
git pull
```

---

## Sicherheitshinweis

DB-API-Credentials die vor Projektbeginn geteilt wurden gelten als
kompromittiert → im DB API Marketplace rotieren.
Credentials ausschließlich über `.env` (gitignored) verwenden, nie committen.
