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
- **Bestellingen** — een bestelling van een klant met meerdere prints: besteldatum, leverdatum, naam en adres, een lijst met
  modellen (zoek een berekening op **nummer** of naam; elke berekening heeft een nummer, `#12`), aantallen en de totaalprijs. Per
  bestelling maak je een **factuur** en zet je de status op *nieuw*, *verwerkt*, *verstuurd* of *afgehandeld*. Zie *Bestellingen en
  facturen* hieronder.
- **Filament** — je rollen met prijs per rol, gewicht, diameter, print- en bedtemperatuur en wat er nog over is;
  de **barcode** bewaar je als identifier: scan hem met de camera van je telefoon (of een barcodescanner, die typt
  gewoon in het veld). Een bekende barcode wordt gemeld en de gegevens van de vorige rol worden meteen ingevuld (wat je zelf al
  typte blijft staan), zodat je alleen nog opslaat, met erbij hoeveel rollen je er nog van hebt. Bovenaan staat de
  **voorraad per soort**: de rollen die je nog hebt met hun gewicht, het totaal per soort en per materiaal (een soort is
  één barcode, of merk + materiaal + kleur). Merk (bijvoorbeeld *Bambu Lab*) en **type** (*Matte*, *Basic*, *Silk*) zijn aparte velden; een bestaande rol houdt wat in het merkveld stond en het type is leeg tot je het invult. Pas je bij een rol met barcode merk, type, materiaal, kleur, gewicht, diameter of temperaturen aan, dan vraagt de app bij het opslaan of de andere rollen met dezelfde barcode ook bijgewerkt moeten worden (alleen wat je veranderde; prijs, wat er nog over is en notities zijn per rol en blijven staan). Je kunt de lijst en de voorraad filteren op **soort** (materiaal), **merk** en **type**; elke keuzelijst past zich aan de vorige keuzes aan. Verbruik van een berekening kun je met één klik van de voorraad afboeken.
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
afronding stel je in onder *Instellingen → Zakelijk → Btw en afronding* (het onderdeel *Zakelijk* zet je eerst aan onder *Instellingen → Algemeen*). Onder *Instellingen → Algemeen* kun je kostprijs, subtotalen en
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
of kies *Instellingen → Algemeen → App installeren*. Lang drukken op het icoon geeft snelkoppelingen (nieuwe berekening, filament).
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

**Nieuwe versie.** De versie in de zijbalk is die van de code die de pagina echt geladen heeft (de server vult hem in `js/build.js` in), niet het antwoord van de server van dit moment; elke script- en stijl-URL draagt de release (`?v=0.7.3-abc1234`), zodat een oude cache of proxy geen oude scripts met een nieuwe server kan mengen. De app vraagt de server bij het openen, na terugkeren naar de voorgrond en elk kwartier welke versie draait.
Is die nieuwer dan wat de app geladen heeft, dan verschijnt bovenaan “Nieuwe versie beschikbaar: vX.Y.Z (commit)” met
*Nu bijwerken* en *Later* (een uur rust). Heb je een berekening met niet-opgeslagen wijzigingen open, dan vraagt de app
eerst of je die wilt kwijtraken. *Instellingen → Algemeen → Updates* toont de draaiende versie en controleert op verzoek.

**Push-meldingen (voorbereid).** Zet ze aan met VAPID-sleutels. Draai je alleen Docker, dan maak je ze in de image zelf:
`docker compose run --rm --no-deps app python generate_vapid.py` (of `python scripts/generate_vapid.py` met Python op de host,
of `init_env.py` voor een nieuwe `.env`). Plak de `VAPID_*`-regels in `.env` en start opnieuw: `docker compose up -d`. Zonder sleutels staat het uit en zegt *Instellingen → Notificaties → Meldingen* dat.
**Zodra de app als PWA op het beginscherm staat (iOS en Android) bied de app meldingen meteen aan:** een balk met één knop *Meldingen aanzetten* (de tik is nodig, want iOS en Chrome stellen de toestemmingsvraag alleen na een handeling). Alleen als de server VAPID-sleutels heeft, de browser push kan en dit toestel nog niet is aangemeld; *Niet nu* zet het twee weken uit, en een toestel dat je bewust uitzet onder *Instellingen → Notificaties → Meldingen* wordt nooit uit zichzelf weer aangezet. Is de toestemming al gegeven maar het toestel niet aangemeld (bijvoorbeeld na opnieuw installeren), dan meldt de app het stilletjes aan. Per apparaat zet je meldingen aan onder *Instellingen → Notificaties → Meldingen*; op **iPhone/iPad werkt het alleen voor een geïnstalleerde app
(iOS 16.4 of nieuwer)** en pas na een tik. Er zijn twee echte meldingen: “Versie X is beschikbaar” zodra de server na een update
opstart, en *Filament bijna op* (beide uit te zetten), plus een testknop. Dit zijn de afleveringsvoorwaarden, vastgelegd in `backend/app/push.py` en
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

**Filament bijna op.** Je kiest per soort filament of je een melding wilt: vink bij *Filament → Wijzigen* de optie *Melding als dit bijna op is* aan. Dat geldt voor de hele soort: alle rollen met dezelfde barcode (zonder barcode: hetzelfde merk, type, materiaal en kleur) krijgen dezelfde keuze en tellen samen, dus drie rollen van 1 kg zijn één soort met 3 kg. Een nieuwe rol met een bekende barcode begint met de keuze van die soort. De drempel stel je in onder *Instellingen → Notificaties → Meldingen → Voorraadmelding*: één in gram voor alle soorten (standaard 500 g) en, als je wilt, een eigen drempel per materiaal (PLA, PETG, …; leeg = de standaarddrempel). Zakt het totaal van een gevolgde soort tot of onder zijn drempel, na het opslaan of verwijderen van een rol, het boeken van een print, het doorgeven van een materiaal aan rollen met dezelfde barcode, het aanpassen van een drempel of het terugzetten van een back-up, dan volgt één melding met de soorten die laag zijn (de laagste eerst). Een nieuwe melding komt pas als die soort er tussendoor weer boven de drempel kwam, dus een rol die al bijna leeg is die je nog aanpast, meldt niet opnieuw; zet je de keuze voor een soort die al laag is aan, dan hoor je dat meteen. Gearchiveerde rollen tellen niet mee. De melding gaat via de uitgaande wachtrij (`push_outbox`) en komt binnen een minuut aan, met dezelfde voorwaarden als de rest (stille uren, stil, TTL); het opslaan van een rol wacht dus nooit op een pushdienst. In *Voorraad per soort* staat een gevolgde soort onder zijn drempel rood met *bijna op*. De toestand (welke soort al gemeld is) staat in de tabel `low_stock_alerts`.

Een pushadres dat de pushdienst afwijst (404/410) wordt automatisch verwijderd. De server moet uitgaand **https** naar de
pushdiensten kunnen (o.a. `fcm.googleapis.com`, `web.push.apple.com`, `updates.push.services.mozilla.com`, `*.notify.windows.com`).
*Instellingen → Notificaties → Meldingen → Verbinding met pushdiensten controleren* controleert eerst lokaal je VAPID-sleutels en contactadres (kloppen privé en publiek bij elkaar, is `VAPID_SUBJECT` bruikbaar) en probeert dan vanaf de server de vier pushdiensten (DNS, verbinding op poort 443, https-handshake) en zegt per onderdeel welke stap faalt. Faalt het versturen zelf met een melding als *“Versturen mislukte voordat de pushdienst werd bereikt (…)”*, dan ligt het niet aan het netwerk maar aan die sleutels of aan de aanmelding van het toestel. Zegt de testknop *“De server kan … niet opzoeken (DNS)”* (of *time-out*), dan bereikt de container de pushdienst niet. Vaak staat
het adres op een blocklist van Pi-hole, AdGuard Home of de router: `*.notify.windows.com` (Edge/Windows) staat op veel
privacylijsten, en dan werkt het voor Chrome-op-Android (`fcm.googleapis.com`) wel. Probeer vanaf de server:
`docker compose exec app python -c "import socket; print(socket.gethostbyname('wns2-am3p.notify.windows.com'))"`
en `docker compose exec app python -c "import urllib.request as u; print(u.urlopen('https://fcm.googleapis.com').status)"`
(een 404 is hier goed: de dienst antwoordt). Zet de adressen op de allowlist van je DNS-filter of geef de container een
andere DNS-server (`dns:` bij de service in `docker-compose.yml`). Een melding op een toestel waarvan de pushdienst
geblokkeerd is, komt niet aan; de andere toestellen worden gewoon bediend.

### Iconen en opstartschermen

Het beginschermicoon (`icons/apple-touch-icon.png`, 180 px, volledig gevuld en zonder transparantie; iOS rondt de hoeken zelf af; één `<link>` zonder `sizes`, zoals bij een bewezen werkende PWA, en ook bereikbaar op `/apple-touch-icon.png`), het favicon en de
19 opstartschermen (`frontend/splash/`, donker, per apparaatformaat) komen uit `frontend/icons/icon-mark.svg`:
`pip install playwright pillow && python scripts/generate_pwa_assets.py` (zet desnoods `CHROMIUM_PATH`). De server zet de release achter de icoon-URL (`apple-touch-icon.png?v=…`), want iOS onthoudt het icoon (of het mislukken ervan) per URL en per website: zo haalt een iPhone na een update een nieuwe op, ook als er eerder iets misging (bij een iPad kan het wel lukken en bij een iPhone niet). Zie je op iOS nog een leeg of oud icoon: verwijder de app van het beginscherm, sluit Safari helemaal en voeg hem opnieuw toe; iOS bewaart het icoon van het moment waarop je hem toevoegde. Het script schrijft
ook de `<link>`-regels voor de opstartschermen in `index.html`; het manifest bevat alleen PNG-iconen (een SVG-regel kan iOS kiezen en geeft dan een leeg icoon); `backend/tests/test_pwa_assets.py` bewaakt dat bestanden, formaten en links kloppen.

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
Aanzetten kan onder *Instellingen → Beveiliging → Wachtwoord en tweestapsverificatie*, ook als er al passkeys actief zijn, en vraagt:
een wachtwoord (minstens 12 tekens) en een authenticator-app (TOTP, 6 cijfers). Er is geen
wachtwoord-login zonder die tweede stap en er komt pas een sessie nadat wachtwoord én code kloppen. Je krijgt 8 back-upcodes
(elk één keer bruikbaar). Na 5 mislukte pogingen blokkeert wachtwoord-login 15 minuten (daarna steeds langer); je passkey
blijft werken. Aanzetten vraagt alleen dat je ingelogd bent (het moet ook werken op een toestel zonder passkey); wijzigen, uitschakelen en nieuwe back-upcodes vragen een verse passkey-bevestiging, of, op een toestel waar de passkey niet werkt, je wachtwoord plus een code (authenticator of back-upcode); dat telt voor de blokkade net als inloggen. Wachtwoorden zijn
met argon2id gehasht; het TOTP-geheim staat versleuteld met een sleutel afgeleid van `SESSION_SECRET`. Wijzig je
`SESSION_SECRET`, dan werkt de tweestapscode niet meer en stel je wachtwoord-login opnieuw in (met je passkey).

## Talen (Nederlands en Engels)

De app spreekt Nederlands en Engels. De taal van de browser is de standaard (een onbekende taal wordt Engels); met de vlaggen
in de zijbalk (op een telefoon: *Meer*) en onder *Instellingen → Weergave* kies je zelf. Die keuze wordt bij je account in de
database bewaard, dus ze geldt op al je apparaten; op de inlogschermen onthoudt de browser ze. Alle teksten staan in
taalbestanden en niet in de code: `frontend/lang/nl.json` en `en.json` voor de schermen, `backend/app/lang/nl.json` en
`en.json` voor wat de server meldt (foutmeldingen, de testmelding en "nieuwe versie"-melding). De server kiest de taal uit de
`X-Lang`-kop van de app, anders uit je bewaarde keuze, anders uit `Accept-Language`, anders Nederlands. Een taal toevoegen
is: een bestand per map toevoegen, de taal in `LANGUAGES` (`frontend/js/i18n.js`) en `LANGUAGES` (`backend/app/i18n.py`) zetten
en een vlag in `frontend/js/langswitch.js` tekenen. `backend/tests/test_i18n.py` bewaakt dat beide bestanden dezelfde sleutels
en `{plaatshouders}` hebben, dat elke gebruikte sleutel bestaat en dat er geen Nederlandse zin in de schermcode is blijven staan.
Bewaarde gegevens (een passkeynaam, een regelomschrijving in een berekening) blijven in de taal waarin je ze maakte, en het
bestand `manifest.webmanifest` (naam van de snelkoppelingen) is niet vertaald.

**Pop-ups.** Elke pop-up past op het scherm (de inhoud scrolt, het kruisje rechtsboven blijft staan) en sluit met het kruisje,
Escape of Annuleren. Zou je daarmee iets kwijtraken (een half ingevuld formulier, een niet afgemaakte wachtwoord-installatie,
back-upcodes die je nog niet bewaard hebt), dan vraagt de app eerst om bevestiging.

## Instellingen

*Instellingen* heeft een submenu bovenaan; elk onderdeel heeft een eigen adres (`#/instellingen/<onderdeel>`):

| Onderdeel | Bevat |
|---|---|
| **Algemeen** | kostprijs en marge blurren, de schakelaar **Zakelijk**, app installeren, updates |
| **Weergave** | taal, thema, accentkleur |
| **Beveiliging** | passkeys en herstelcodes, wachtwoord en tweestapsverificatie |
| **Zakelijk** | btw en afronding, bedrijfsgegevens, factuursjabloon; alleen zichtbaar als de schakelaar *Zakelijk* onder *Algemeen* aan staat (de voorkeur `business_mode`, per account) |
| **Notificaties** | meldingen (dit apparaat, nieuwe versie, filament bijna op, testmelding, verbindingscontrole, apparatenlijst) en stille uren |
| **Back-up en herstel** | zie *Back-up in de app* |

*Uitloggen* staat onderaan de zijbalk (op een telefoon onderaan *Meer*). *Zakelijk* verbergt alleen dat onderdeel van de instellingen; het menu
*Bestellingen* blijft gewoon zichtbaar. Een onderdeel dat niet getoond wordt (bijvoorbeeld *Zakelijk* terwijl het uit staat) valt terug op
*Algemeen*.

## Bestellingen en facturen

**Bestellingen** (menu *Bestellingen*): *Nieuwe bestelling* vraagt de besteldatum en leverdatum, de gegevens van de klant (naam,
adres, postcode, plaats, land, e-mail, telefoon) en de modellen. Bij *Model toevoegen* zoek je een berekening op nummer (`2`, `#2`)
of op een deel van de naam; kies je hem nog eens, dan gaat het aantal omhoog. De prijs per stuk is de verkoopprijs **incl. btw** uit
de berekening zoals die er op dat moment uit zag; hij wordt gekopieerd en is per regel aan te passen, een latere wijziging van de
berekening verandert een bestelling dus niet. Met *Eigen regel toevoegen* komt er een regel bij die niet bij een berekening hoort
(bijvoorbeeld verzending). De **totalen rekent de server uit** (`backend/app/orders.py`, nooit de browser): de btw wordt per tarief
uit de som van de regels gehaald, zodat wat de klant betaalt precies de som van de regels is. In de lijst filter je op status
en zoek je op naam, plaats, bestelnummer of factuurnummer; de status zet je daar met één keuzelijst, of in de bestelling zelf.

**Facturen**: *Factuur genereren* maakt de factuur van de bestelling en downloadt hem. De eerste keer krijgt de factuur een
nummer (`JJJJ-0001`, per jaar doorgeteld, nooit tweemaal uitgegeven) en een factuurdatum (vandaag, daarna aan te passen);
daarna levert dezelfde knop (*Factuur opnieuw downloaden*) hetzelfde nummer met wat de bestelling nu zegt, dus een bestelling
bewerken en de factuur opnieuw downloaden kan altijd. Een factuur heeft zijn eigen bestand niet: hij wordt elke keer uit de
bestelling gemaakt. Gegevens van je bedrijf (naam, adres, telefoon, e-mail, website, KvK, btw-nummer, IBAN en BIC, betaaltermijn, taal
van de factuur, een tekst onderaan en of er een betaal-QR op komt) vul je in onder *Instellingen → Zakelijk → Bedrijfsgegevens*, je
**logo** (PNG of JPEG, maximaal 2 MB) onder *Instellingen → Zakelijk → Logo*. Per bestelling vul je ook het **klantnummer** en een
**Betreft**-regel in (leeg: “Bestelling” met het nummer).

**De ingebouwde factuur** heeft de layout van het voorbeeld dat de eigenaar aanleverde (Open Sans, A4): het logo linksboven, rechts de
bedrijfsgegevens (naam en adres, daaronder in kleine letters btw-nummer, KVK, telefoon, e-mail, website, IBAN en BIC), links het
adres van de klant, rechts factuurdatum, vervaldatum en klantnummer, dan *Factuur: nummer* en *Betreft:*, een tabel met aantal,
beschrijving en het bedrag excl. en incl. btw per regel (met het btw-tarief eronder), de totalen per btw-tarief (*Btw hoog (21%)*,
*Btw laag (9%)*), de betaalzin en een **betaal-QR**. Datums staan als `dd/mm/jjjj`. De QR is een SEPA-code (EPC069-12) die bankapps
lezen: bedrag, IBAN, naam en factuurnummer worden ingevuld (dus geen iDEAL-link); hij komt er alleen als IBAN en bedrijfsnaam zijn
ingevuld en je hem niet hebt uitgezet. Per regel zijn netto en btw zo verdeeld dat de regels precies optellen tot de totalen
(`orders._split_net`: afgerond naar beneden, de overgebleven centen naar de grootste resten). Het lettertype (Open Sans, SIL Open Font
License) staat in `backend/app/fonts/` met zijn licentie; ontbreekt het, dan valt de PDF terug op Helvetica.

**Sjabloon** (*Instellingen → Zakelijk → Factuursjabloon*, maximaal 5 MB, één tegelijk; een nieuw bestand vervangt het vorige):

- **Zonder sjabloon** gebruikt de app de ingebouwde PDF hierboven.
- **Word (`.docx`)**: zet velden tussen dubbele accolades in je document (kop, voet en tabellen werken ook). Eén tabelrij met
  `{{regel.omschrijving}}`, `{{regel.aantal}}`, `{{regel.bedrag_excl}}`, `{{regel.bedrag_incl}}`, `{{regel.btw}}` (ook `{{regel.prijs}}`
  per stuk, `{{regel.totaal}}` en `{{regel.nr}}`) wordt voor elke regel van de bestelling herhaald; een sjabloon zonder zo'n rij wordt bij het uploaden geweigerd. Je krijgt een Word-bestand
  terug (de app zet het niet om naar PDF). Een veld dat niet bestaat blijft zichtbaar in de factuur staan, zodat je een typefout ziet.
  `{{logo}}` en `{{betaal_qr}}` worden afbeeldingen (je logo en de betaal-QR; zonder logo of IBAN verdwijnt de tekst). *Voorbeeldsjabloon
  downloaden* geeft een Word-bestand in dezelfde layout als de ingebouwde factuur, om mee te beginnen; het gebruikt Open Sans (Word
  neemt een ander lettertype waar het ontbreekt).
- **PDF als briefpapier**: de eerste pagina van je PDF blijft zoals hij is (logo, bedrijfsgegevens) en de factuur wordt erop gezet,
  tussen de marges boven en onder die je bij het uploaden opgeeft (standaard 55 en 25 mm; later aan te passen met *Marges
  opslaan*). Het logo en de bedrijfsgegevens uit de instellingen worden dan niet nog eens afgedrukt (de betaal-QR wel). Een lange bestelling loopt door op een
  tweede pagina op hetzelfde briefpapier.

Beschikbare velden (ook te zien onder *Beschikbare velden* bij het sjabloon): `logo`, `betaal_qr`, `factuurnummer`, `factuurdatum`,
`vervaldatum`, `betreft`, `bestelnummer`, `besteldatum`, `leverdatum`, `opmerking` (de notities van de bestelling), `klant.naam`,
`klant.nummer`, `klant.adres`,
`klant.postcode`, `klant.plaats`, `klant.postcode_plaats`, `klant.land`, `klant.email`, `klant.telefoon`, `klant.adresblok` (naam, adres,
postcode en plaats, land onder elkaar), `bedrijf.naam`, `bedrijf.adres`, `bedrijf.postcode`, `bedrijf.plaats`, `bedrijf.land`,
`bedrijf.email`, `bedrijf.telefoon`, `bedrijf.website`, `bedrijf.kvk`, `bedrijf.btw_nummer`, `bedrijf.iban`, `bedrijf.bic`,
`bedrijf.tekst`, `totaal_excl`, `btw_totaal`, `totaal`, `btw_overzicht` (per tarief, labels en bedragen samen), `btw_labels` en
`btw_bedragen` (dezelfde regels apart, om in twee kolommen te zetten), `betaaltekst` (bedrag, vervaldatum en factuurnummer) en de
regelvelden hierboven. Het sjabloonbestand en het logo staan, net als elke upload, onder `UPLOAD_DIR`; ze worden met de rest meegenomen in de
back-up van de app. Word- en PDF-bestanden worden als onbetrouwbaar behandeld: grootte en uitgepakte grootte zijn begrensd, Word
wordt gelezen met `python-docx` (zonder XML-entiteiten) en PDF alleen met `pypdf`; er wordt niets uitgevoerd.

## Back-up in de app

*Instellingen → Back-up en herstel* downloadt al je gegevens als één JSON-bestand (`printpricing-backup-JJJJ-MM-DD.json`):
je instellingen (thema, taal, btw, afronding, stille uren, bedrijfsgegevens…), printers, energietarieven, verpakkingen, filamentrollen,
berekeningen (met hun nummers), bestellingen met hun factuurnummers, het factuursjabloon en het logo, op wens ook de geüploade printbestanden (groter). **Niet** in het bestand: passkeys, herstelcodes, het wachtwoord
met zijn authenticatorgeheim en meldingsaanmeldingen. Het zijn sleutels of horen bij één apparaat; een bestand dat je kunt
mailen of bewaren mag de app niet kunnen openen. Na herstellen op een lege installatie log je dus gewoon in met je passkey.

*Herstellen uit back-up…* kiest zo'n bestand, controleert het eerst helemaal (met dezelfde regels als handmatig invoeren; de
berekeningen worden opnieuw uitgerekend, een aangepast totaal in het bestand telt dus niet, en printbestanden worden opnieuw
gelezen en tegen hun controlesom gehouden) en laat zien wat er terugkomt. Pas na jouw bevestiging **vervangt** het alles wat er
nu staat, in één keer: lukt iets niet, dan verandert er niets. Een bestand uit een nieuwere versie van de app wordt geweigerd; een back-up van een oudere versie (zonder bestellingen) werkt
nog steeds en laat de bestellingen dan leeg. Het volgende bestel- en factuurnummer gaat door na de hoogste uit de back-up.
Zo'n back-up past binnen `MAX_UPLOAD_MB` (standaard 50 MB); met printbestanden kan dat te klein zijn, verhoog het dan in `.env`.
Een volledige kopie van de database (`pg_dump`) en de map met uploads blijft de manier voor een back-up van de hele server, zie
*Back-up en herstel* (onder Beheer) hierboven.
