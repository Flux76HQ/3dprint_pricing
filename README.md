# 3D Print Pricing

Zelf-gehoste PWA om de **kostprijs van 3D-prints** uit te rekenen en de voorraad en tarieven bij
te houden waar die prijzen op gebaseerd zijn. Inloggen gaat met **passkeys** (geen wachtwoord).

- **Berekeningen** — filament, onderdelen, USB-kabel/lader, printerafschrijving en energie → totale
  kostprijs, optioneel met marge voor een adviesverkoopprijs. Opgeslagen berekeningen bewaren de prijzen
  van het moment van opslaan.
- **Filament** — je rollen met prijs per rol, gewicht en wat er nog over is; verbruik van een
  berekening kun je met één klik van de voorraad afboeken.
- **Printers** — aanschafwaarde, levensduur in uren (afschrijving per uur) en vermogen.
- **Energie** — tarieven per kWh, met een standaardtarief.
- Licht/donker/systeem, eigen accentkleur, installeerbaar op je beginscherm.

De kostprijs volgt de spreadsheet: `filament + onderdelen + lader + afschrijving + energie`, elke
regel op hele centen afgerond vóór het optellen.

## Starten (Docker)

```bash
python scripts/init_env.py --port 6090 --domain print.voorbeeld.nl   # maakt .env met verse geheimen
docker compose up -d
```

Op een server heb je alleen `docker-compose.yml` en `.env` nodig: de app-image wordt van GHCR gepulld
(`ghcr.io/flux76hq/3dprint_pricing`). Is dat package **privaat**, log dan eerst in met een token met
`read:packages` (`echo $TOKEN | docker login ghcr.io -u <gebruiker> --password-stdin`), of maak het package
publiek onder *GitHub → Packages → Package settings → Change visibility*. Zonder toegang faalt de pull met
`denied`/`unauthorized`.

Bouwen uit een checkout (met de `Dockerfile`) kan ook:

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

Zonder `--domain` wordt `http://localhost:<poort>` ingesteld, genoeg om het uit te proberen.
Handmatig kan ook: `cp .env.example .env` en de waarden invullen.

Open daarna het adres en doorloop de **onboarding**:

1. Vul de **setupcode** in (`SETUP_CODE` uit `.env`; `init_env.py` toont hem) en je naam.
2. Maak je **passkey** aan (vingerafdruk, gezicht of apparaatcode).
3. **Bewaar de 8 herstelcodes** — ze worden één keer getoond en werken elk één keer.

Daarna is de onboarding gesloten. Meer passkeys voeg je toe onder *Instellingen → Beveiliging*;
verwijderen of nieuwe herstelcodes vraagt een verse passkey-bevestiging.

### Instellingen (`.env`)

| Variabele | Betekenis |
|---|---|
| `WEB_PORT` | Poort van de app; compose publiceert en de app luistert op deze ene waarde |
| `DATA_PATH` | Map op de host voor de PostgreSQL-data (blijft bestaan bij herbouwen) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Database; gebruik een wachtwoord met alleen letters en cijfers |
| `RP_ID` | Domein waarop de app draait, zonder schema of poort; passkeys zijn eraan gebonden |
| `RP_ORIGINS` | Volledige origin(s), komma-gescheiden, bijv. `https://print.voorbeeld.nl` |
| `RP_NAME` | Naam die in de passkey-prompt staat |
| `SETUP_CODE` | Eenmalige code voor de onboarding, zodat niet de eerste bezoeker de app overneemt |
| `SESSION_SECRET` | Ondertekent sessiecookies, minimaal 32 tekens |
| `SESSION_HOURS` | Levensduur van een sessie (standaard 24) |
| `PROXY_HOPS` | Aantal reverse proxies ervoor (vertrouwt `X-Forwarded-*`) |
| `WEB_CONCURRENCY` | Aantal Gunicorn-workers (standaard 2) |
| `APP_IMAGE` | Te draaien image (standaard `ghcr.io/flux76hq/3dprint_pricing:latest`) |

**Passkeys vragen https** (behalve op `http://localhost`) en een **domeinnaam**: openen via een IP-adres
werkt niet. Zet er een reverse proxy met TLS voor en stel `RP_ID`/`RP_ORIGINS` in op dat domein. Wijzig
je `RP_ID` later, dan werken bestaande passkeys niet meer; log dan in met een herstelcode.

## Lokaal ontwikkelen

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements-dev.txt
python scripts/setup_hooks.py                # pre-commit: versiecheck + agent-instructions
cd backend && PYTHONPATH=. python -m pytest -q
```

De databasetests hebben PostgreSQL nodig: zet `TEST_DATABASE_URL`, of draai als root met PostgreSQL
geïnstalleerd; dan start de testsuite een tijdelijke cluster. Zie [`AGENTS.md`](AGENTS.md) voor de werkafspraken.

## Operationele documentatie

### Draaien en stoppen
`docker compose up -d` · `docker compose down` (data blijft in `DATA_PATH`) · logs: `docker compose logs -f app`.

### Health checks
- `GET /healthz` — proces leeft (gebruikt door de container-healthcheck).
- `GET /readyz` — proces draait **en** de database antwoordt (503 anders).
- `GET /api/version` — draaiende versie.

### Deploy en update
```bash
docker compose pull && docker compose up -d
```
CI publiceert bij elke merge naar `main` `:latest`, en `:X.Y.Z` plus een GitHub Release (met notities) wanneer
`VERSION` een nieuwe versie heeft. Een versie-image wordt nooit overschreven. Migraties draaien bij het opstarten
vóór de server verkeer krijgt; de container stopt als een migratie faalt of een toegepaste migratie is gewijzigd.
Hosten op de gedeelde Flux76-server: zie `shared/infrastructure/adding-an-app.md` in App-Guidance.

### Back-up en herstel
```bash
# back-up
docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup-$(date +%F).sql
# herstel (op een lege database, app gestopt)
docker compose exec -T db psql -U "$POSTGRES_USER" "$POSTGRES_DB" < backup-2026-01-01.sql
```
Alternatief: stop de stack en kopieer `DATA_PATH`. De back-up bevat je passkey-publieke sleutels en gehashte
herstelcodes, geen geheimen. Bewaar `.env` apart (in je wachtwoordmanager): zonder `SESSION_SECRET` log je gewoon opnieuw
in, maar `RP_ID` moet gelijk blijven.

### Runtime-architectuur
Eén app-container (Gunicorn serveert API **en** de statische PWA) + één PostgreSQL-17-container. Data: alleen
PostgreSQL, in `DATA_PATH/postgres`. Er is geen andere opslag.

| Onderdeel | Taak |
|---|---|
| `backend/app/calc.py` | de kostprijsberekening (`Decimal`, afronden per regel) |
| `backend/app/auth.py`, `webauthn.py` | passkeys (ES256), herstelcodes, sessies, step-up |
| `backend/app/api.py` | printers, tarieven, filament, berekeningen, voorkeuren |
| `backend/app/db.py`, `migrations/` | migratierunner (vooruit-only, checksum-bewaakt) |
| `frontend/` | statische PWA zonder buildstap, plus service worker voor offline schil |

### Limieten buiten de repository
Alles wat een verzoek onderweg naar de app kan weigeren, met de waarde die de app nodig heeft:

| Limiet | Waarde die de app nodig heeft | Beperkt |
|---|---|---|
| Maximale request-body (proxy/CDN) | ≥ 1 MB | `MAX_CONTENT_LENGTH` in `backend/app/__init__.py` (1 MB; alleen JSON) |
| Request-timeout (proxy/CDN) | ≥ 30 s | Gunicorn `--timeout 30` in `deploy/entrypoint.sh` |
| `Origin`-header op schrijvende verzoeken doorgeven | verplicht ongewijzigd | origin-check tegen `RP_ORIGINS` |
| `X-Forwarded-For/-Proto/-Host` doorgeven | aantal proxies = `PROXY_HOPS` | rate-limit op de setupcode per client-IP |
| TLS | verplicht (behalve `localhost`) | WebAuthn werkt alleen in een secure context |

Er zit geen CDN of proxy in deze repository; wat ervoor staat bepaalt de werkelijke ceilings.
