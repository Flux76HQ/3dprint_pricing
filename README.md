# 3D Print Pricing

Zelf-gehoste PWA om de **kostprijs van 3D-prints** uit te rekenen en de voorraad en tarieven bij
te houden waar die prijzen op gebaseerd zijn. Inloggen gaat met **passkeys** (geen wachtwoord).

- **Berekeningen** — filament, onderdelen, USB-kabel/lader, **verpakkingsmateriaal**, printerafschrijving en
  energie → totale kostprijs, optioneel met marge voor een adviesverkoopprijs. Opgeslagen berekeningen
  bewaren de prijzen van het moment van opslaan.
- **Printbestand koppelen** — upload een `.3mf` of `.stl` bij een berekening; het bestand blijft bewaard en is later
  te downloaden. Uit een **gesliced 3MF** (Bambu Studio / Orca, “Export plate sliced file”) leest de app de
  echte **gram per filament** en **printtijd**. Die worden standaard **automatisch** verwerkt in de berekening (uit te
  zetten): filamentregels met de prijs van de passende rol, printtijd naar boven op hele uren, en een printerregel
  met afschrijving en stroom (eerste printer, standaardtarief); handmatig overnemen kan ook met één klik. Uit een **STL** (of een 3MF zonder
  slicer-data) leest de app het volume en **schat** het gewicht (volume × dichtheid × effectieve vulling);
  de printtijd is dan onbekend, want die volgt niet uit de vorm. Daarnaast kun je een **link** naar het model
  bewaren (bijv. MakerWorld); die pagina wordt niet uitgelezen.
- **Filament** — je rollen met prijs per rol, gewicht, diameter, print- en bedtemperatuur en wat er nog over is;
  de **barcode** bewaar je als identifier: scan hem met de camera van je telefoon (of een barcodescanner, die typt
  gewoon in het veld) en bij een bekende barcode neem je met één klik de gegevens van de vorige rol over; verbruik van een
  berekening kun je met één klik van de voorraad afboeken.
- **Verpakking** — je soorten dozen en ander verpakkingsmateriaal met prijs per stuk. In een berekening kies je er
  per product een uit de lijst (of vul je een regel zelf in); de prijs wordt in de berekening bewaard.
- **Printers** — aanschafwaarde, levensduur in uren (afschrijving per uur) en vermogen.
- **Energie** — tarieven per kWh, met een standaardtarief.
- Licht/donker/systeem, eigen accentkleur, installeerbaar op je beginscherm.

De kostprijs volgt de spreadsheet: `filament + onderdelen + lader + verpakking + afschrijving + energie`, elke
regel op hele centen afgerond vóór het optellen. **Machinetijd (afschrijving en stroom) wordt altijd naar boven
afgerond op hele uren**: 3,06 uur rekent als 4 uur.

**Zakelijk verkopen:** over de verkoopprijs (kostprijs + marge) komt **btw** (standaard 21%, per berekening aan te
passen; 0 = geen btw). Inkoopprijzen voer je excl. btw in. Met **“Prijs incl. btw afronden”** (op 5/10/50 cent, hele
euro's of eindigend op ,95/,99) wordt de prijs incl. btw naar boven afgerond en geldt je marge als *minimum*: de app
verhoogt de marge net genoeg en toont de effectieve marge; de btw wordt uit de ronde prijs gehaald. Standaard btw en
afronding stel je in onder *Instellingen → Zakelijk*. Onder *Instellingen → Weergave* kun je kostprijs, subtotalen en
marge **blurren** op de berekeningenpagina (ook met de knop “Kosten verbergen” daar), handig als een klant meekijkt.

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
GIT_COMMIT=$(git rev-parse --short HEAD) docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

(`GIT_COMMIT` verschijnt naast het versienummer; zonder staat er `dev`. CI zet hem automatisch.)

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
| `DATA_PATH` | Map op de host voor de PostgreSQL-data (`postgres/`) en geüploade bestanden (`app/`); blijft bestaan bij herbouwen |
| `MAX_UPLOAD_MB` | Grootste STL/3MF-upload in MB (standaard 50) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Database; gebruik een wachtwoord met alleen letters en cijfers |
| `RP_ID` | Domein waarop de app draait, zonder schema of poort; passkeys zijn eraan gebonden |
| `RP_ORIGINS` | Volledige origin(s), komma-gescheiden, bijv. `https://print.voorbeeld.nl` |
| `RP_NAME` | Naam die in de passkey-prompt staat |
| `SETUP_CODE` | Eenmalige code voor de onboarding, zodat niet de eerste bezoeker de app overneemt |
| `SESSION_SECRET` | Ondertekent sessiecookies, minimaal 32 tekens |
| `SESSION_HOURS` | Levensduur van een sessie (standaard 24) |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | Sleutelpaar voor push-meldingen (`python scripts/generate_vapid.py`); leeg = meldingen uit. De private sleutel is geheim; een ander paar maakt bestaande aanmeldingen onbruikbaar |
| `VAPID_SUBJECT` | Contactadres voor de pushdiensten (`mailto:…` of https-url); leeg = `mailto:admin@<RP_ID>` |
| `PROXY_HOPS` | Aantal reverse proxies ervoor (vertrouwt `X-Forwarded-*`) |
| `WEB_CONCURRENCY` | Aantal Gunicorn-workers (standaard 2) |
| `APP_IMAGE` | Te draaien image (standaard `ghcr.io/flux76hq/3dprint_pricing:latest`) |

**Camerascannen** (barcode) vraagt, net als passkeys, https en toestemming voor de camera. Chrome/Edge/Android gebruiken
hun eigen scanner; Safari/iOS laadt een meegeleverde scanbibliotheek ([ZXing](frontend/vendor/zxing/README.md), Apache-2.0).
Eén barcode hoort bij een *product*: meerdere rollen van hetzelfde filament mogen dezelfde barcode hebben.

**Passkeys vragen https** (behalve op `http://localhost`) en een **domeinnaam**: openen via een IP-adres
werkt niet. Zet er een reverse proxy met TLS voor en stel `RP_ID`/`RP_ORIGINS` in op dat domein. Wijzig
je `RP_ID` later, dan werken bestaande passkeys niet meer; log dan in met een herstelcode.

## Installeren als app (iPhone, iPad en Android)

**Android (Chrome, Edge, Samsung Internet) en computer:** open het https-adres; er verschijnt een melding “Installeer de app”,
of kies *Instellingen → App installeren*. Lang drukken op het icoon geeft snelkoppelingen (nieuwe berekening, filament).
Eenmaal geïnstalleerd verdwijnt de melding; kies je “Niet nu”, dan komt ze pas na twee weken terug.

**iPhone/iPad:** iOS biedt geen installatieknop aan, dus de app legt het uit. Open het https-adres in
**Safari → Deel → Zet op beginscherm**. De app start dan schermvullend zonder Safari-balk,
met een eigen icoon en opstartscherm en reageert als een native app:
- **Geen pinch-zoom en geen dubbeltik-zoom**, en **geen zijwaarts vegen**: de pagina schuift alleen verticaal en de
  rand-veeg van iOS (terug/vooruit) heeft niets om naartoe te gaan, want de geïnstalleerde app voegt bij het navigeren
  geen geschiedenis toe.
- De pagina loopt onder de statusbalk; notch, home-indicator en de zijkanten (liggend) worden gerespecteerd.
- Aandachtspunt toegankelijkheid: zoom is hier bewust geblokkeerd. Tekst volgt wel de tekstgrootte van het systeem
  (iOS: Instellingen → Beeldscherm en helderheid → Tekstgrootte). In een gewone Safari-tab kan iOS zoomen soms toch
  toestaan; het gedrag hierboven geldt voor de geïnstalleerde app.
- iOS bewaart icoon en opstartscherm bij het toevoegen: na een wijziging daarvan verwijder je de app en zet je hem opnieuw
  op het beginscherm. Android/Chrome gebruikt `manifest.webmanifest`.

### Meldingen en updates

**Nieuwe versie.** De app vraagt de server bij het openen, na terugkeren naar de voorgrond en elk kwartier welke versie draait.
Is die nieuwer dan wat de app geladen heeft, dan verschijnt bovenaan “Nieuwe versie beschikbaar: vX.Y.Z (commit)” met
*Nu bijwerken* en *Later* (een uur rust). Heb je een berekening met niet-opgeslagen wijzigingen open, dan vraagt de app
eerst of je die wilt kwijtraken. *Instellingen → Updates* toont de draaiende versie en controleert op verzoek.

**Push-meldingen (voorbereid).** Zet ze aan met VAPID-sleutels. Draai je alleen Docker, dan maak je ze in de image zelf:
`docker compose run --rm --no-deps app python generate_vapid.py` (of `python scripts/generate_vapid.py` met Python op de host,
of `init_env.py` voor een nieuwe `.env`). Plak de `VAPID_*`-regels in `.env` en start opnieuw: `docker compose up -d`. Zonder sleutels staat het uit en zegt *Instellingen → Meldingen* dat.
Per apparaat zet je meldingen aan onder *Instellingen → Meldingen*; op **iPhone/iPad werkt het alleen voor een geïnstalleerde app
(iOS 16.4 of nieuwer)** en pas na een tik. Er is nu één echte melding: “Versie X is beschikbaar” zodra de server na een update
opstart (uit te zetten), plus een testknop. Dit zijn de afleveringsvoorwaarden, vastgelegd in `backend/app/push.py` en
afgedwongen door `backend/tests/test_push.py` (project-baseline §11):

| Voorwaarde | Waarde | Waarom |
|---|---|---|
| TTL | 24 uur | een toestel dat een nacht uit stond krijgt het ’s ochtends nog; een week oud bericht is ruis (`pywebpush` zou standaard 0 sturen: weggegooid als het toestel niet bereikbaar is) |
| Urgency | `low` | niets hier is tijdkritisch; `high` zou een schriftelijke reden en een aangepaste test vragen |
| Topic | per soort (`release`, `test`) | een toestel dat lang onbereikbaar was krijgt alleen het nieuwste bericht per soort |
| Geluid | stil (`silent`) | niet tijdkritisch; Safari op iOS negeert `silent`, vandaar de stille uren |
| Focus / Niet storen | nooit doorbreken | geen `requireInteraction`, geen trilpatroon; dat is jouw instelling op je toestel |
| Stille uren | instelbaar rooster | de app ziet de Focus-stand niet; zet hier hetzelfde rooster als je slaap-Focus. Wandkloktijd + tijdzonenaam (volgt zomer/wintertijd), werkt over middernacht heen, **houdt vast en levert daarna alsnog af**, en bij een onleesbare instelling wordt er juist wél verstuurd |
| Testknop | dezelfde functie en voorwaarden | een test die luider of korter leeft dan het echte werk wordt geloofd |

Een pushadres dat de pushdienst afwijst (404/410) wordt automatisch verwijderd. De server moet uitgaand **https** naar de
pushdiensten kunnen (o.a. `fcm.googleapis.com`, `web.push.apple.com`, `updates.push.services.mozilla.com`, `*.notify.windows.com`).

### Iconen en opstartschermen

De iconen (`apple-touch-icon-*.png`, volledig gevuld en zonder transparantie; iOS rondt de hoeken zelf af) en de
19 opstartschermen (`frontend/splash/`, donker, per apparaatformaat) komen uit `frontend/icons/icon-mark.svg`:
`pip install playwright pillow && python scripts/generate_pwa_assets.py` (zet desnoods `CHROMIUM_PATH`). Het script schrijft
ook de `<link>`-regels in `index.html`; `backend/tests/test_pwa_assets.py` bewaakt dat bestanden, formaten en links kloppen.

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

**Zie je na een update nog de oude app?** Controleer de draaiende versie in de zijbalk (onder de naam, als `vx.x.x (commit)`), onder *Instellingen* (onderaan) of met
`curl http://<host>:<poort>/api/version`, en vergelijk met de laatste release op GitHub. Staat daar een oudere versie:
- `docker compose up -d` pullt een image die al lokaal bestaat **niet** opnieuw; gebruik `docker compose pull && docker compose up -d`.
  Een eerder lokaal gebouwde `…:latest` heeft voorrang tot je pullt.
- Controleer of `APP_IMAGE` in `.env` niet op een oude tag staat; zet hem desnoods op de nieuwste (bijv. `…:0.3.0`).
- Draait alles goed maar toont je browser oude schermen, ververs dan één keer hard (de service worker haalt bestanden
  vanaf versie 0.3.1 eerst van het netwerk).

### Back-up en herstel
```bash
# back-up
docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup-$(date +%F).sql
# herstel (op een lege database, app gestopt)
docker compose exec -T db psql -U "$POSTGRES_USER" "$POSTGRES_DB" < backup-2026-01-01.sql
```
`pg_dump` bevat **niet** de geüploade STL/3MF-bestanden: die staan in `DATA_PATH/app/uploads`. Back die map ook
op (`tar czf uploads.tgz "$DATA_PATH/app"`), of stop de stack en kopieer heel `DATA_PATH` (dat is dan alles in één
keer). Een berekening zonder terugkomend bestand blijft werken; alleen “Downloaden” geeft dan een melding.
De back-up bevat je passkey-publieke sleutels en gehashte herstelcodes, geen geheimen. Bewaar `.env` apart (in je wachtwoordmanager): zonder `SESSION_SECRET` log je gewoon opnieuw
in, maar `RP_ID` moet gelijk blijven.

### Runtime-architectuur
Eén app-container (Gunicorn serveert API **en** de statische PWA) + één PostgreSQL-17-container. Data: PostgreSQL in
`DATA_PATH/postgres` en geüploade printbestanden in `DATA_PATH/app/uploads` (de database bewaart per bestand de metadata
en wat eruit is gelezen). Bestanden die nooit aan een berekening zijn gekoppeld worden na een dag opgeruimd.
De container start als root om de rechten van de gemounte map te zetten en draait daarna als gebruiker `app`.

| Onderdeel | Taak |
|---|---|
| `backend/app/calc.py` | de kostprijsberekening (`Decimal`, afronden per regel) |
| `backend/app/auth.py`, `webauthn.py` | passkeys (ES256), herstelcodes, sessies, step-up |
| `backend/app/api.py` | printers, tarieven, filament, verpakking, berekeningen, voorkeuren |
| `backend/app/files.py`, `printfile.py` | upload/download van STL/3MF en het uitlezen ervan (slicer-gegevens of volume) |
| `backend/app/db.py`, `migrations/` | migratierunner (vooruit-only, checksum-bewaakt) |
| `frontend/` | statische PWA zonder buildstap, plus service worker voor offline schil |

### Limieten buiten de repository
Alles wat een verzoek onderweg naar de app kan weigeren, met de waarde die de app nodig heeft:

| Limiet | Waarde die de app nodig heeft | Beperkt |
|---|---|---|
| Maximale request-body (proxy/CDN) | ≥ `MAX_UPLOAD_MB` + 1 MB (standaard 51 MB) | uploadlimiet van de app; Cloudflare Free stopt bij 100 MB, nginx staat standaard op 1 MB (`client_max_body_size`) |
| Request-timeout (proxy/CDN) | ≥ 120 s | Gunicorn `--timeout 120` in `deploy/entrypoint.sh` (een groot 3MF uitlezen duurt even) |
| `Origin`-header op schrijvende verzoeken doorgeven | verplicht ongewijzigd | origin-check tegen `RP_ORIGINS` |
| `X-Forwarded-For/-Proto/-Host` doorgeven | aantal proxies = `PROXY_HOPS` | rate-limit op de setupcode per client-IP |
| TLS | verplicht (behalve `localhost`) | WebAuthn, installeren, camera en push werken alleen in een secure context |
| Uitgaand https vanaf de app-container | naar de pushdiensten (zie hierboven) | het versturen van push-meldingen; zonder dit falen ze zonder dat de app het merkt, behalve in de testknop |

Er zit geen CDN of proxy in deze repository; wat ervoor staat bepaalt de werkelijke ceilings.

## Wachtwoord en tweestapsverificatie (optioneel)

Standaard **uit**; passkeys blijven de aanbevolen manier van inloggen en werken altijd, ook als je het wachtwoord inschakelt.
Aanzetten kan onder *Instellingen → Wachtwoord en tweestapsverificatie*, ook als er al passkeys actief zijn, en vraagt:
een bevestiging met je passkey, een wachtwoord (minstens 12 tekens) en een authenticator-app (TOTP, 6 cijfers). Er is geen
wachtwoord-login zonder die tweede stap en er komt pas een sessie nadat wachtwoord én code kloppen. Je krijgt 8 back-upcodes
(elk één keer bruikbaar). Na 5 mislukte pogingen blokkeert wachtwoord-login 15 minuten (daarna steeds langer); je passkey
blijft werken. Wijzigen, uitschakelen en nieuwe back-upcodes vragen opnieuw een passkey-bevestiging. Wachtwoorden zijn
met argon2id gehasht; het TOTP-geheim staat versleuteld met een sleutel afgeleid van `SESSION_SECRET`. Wijzig je
`SESSION_SECRET`, dan werkt de tweestapscode niet meer en stel je wachtwoord-login opnieuw in (met je passkey).
