# 3D Print Pricing: handleiding en beheer

> Dit is de uitgebreide handleiding (Nederlands): functies in detail, installatie, instellingen, meldingen, back-up en beheer.
> Een korte presentatie met schermafbeeldingen staat in de [README](../README.nl.md) ([English](../README.md)).

Zelf-gehoste PWA om de **kostprijs van 3D-prints** uit te rekenen en de voorraad en tarieven bij
te houden waar die prijzen op gebaseerd zijn. Inloggen gaat met **passkeys** (geen wachtwoord).

- **3D Modellen** (menu; voorheen *Berekeningen*) — de berekening per model: filament, onderdelen, accessoires (kabels/laders), printerafschrijving en
  energie → totale kostprijs, optioneel met marge voor een adviesverkoopprijs. Opgeslagen berekeningen
  bewaren de prijzen van het moment van opslaan.
- **Printbestand koppelen** — upload een `.3mf` of `.stl` bij een berekening; het bestand blijft bewaard en is later
  te downloaden. Uit een **gesliced 3MF** (Bambu Studio / Orca, “Export plate sliced file”) leest de app de
  echte **gram per filament** en **printtijd**. Die worden standaard **automatisch** verwerkt in de berekening (uit te
  zetten): filamentregels met de prijs van de passende rol, printtijd naar boven op hele uren, en een printerregel
  met afschrijving en stroom (eerste printer, standaardtarief); handmatig overnemen kan ook met één klik. Bevat het bestand meerdere platen, dan kies je in het menu *Plaat* één plaat of *Alle platen*: dan worden uren en gram van alle platen bij elkaar opgeteld (hetzelfde filament telt als één regel). Uit een **STL** (of een 3MF zonder
  slicer-data) leest de app het volume en **schat** het gewicht (volume × dichtheid × effectieve vulling);
  de printtijd is dan onbekend, want die volgt niet uit de vorm. Daarnaast kun je een **link** naar het model
  bewaren (bijv. MakerWorld); die pagina wordt niet uitgelezen.
- **Klanten en bestellingen** — klanten met klantnummer, en een bestelling van een klant met meerdere prints: besteldatum, leverdatum, de klant, een lijst met
  modellen (zoek een berekening op **nummer** of naam; elke berekening heeft een nummer, `#12`), aantallen en de totaalprijs. Per
  bestelling maak je een **factuur** en zet je de status op *nieuw*, *verwerkt*, *verstuurd* of *afgehandeld*. Zie *Bestellingen en
  facturen* hieronder.
- **Navigatiebalk (telefoon)** — de balk onderaan gebruikt Material Design-iconen (Pictogrammers, Apache-2.0, mee te leveren onder `frontend/vendor/mdi/`; ingevuld als het onderdeel actief is, anders als omtrek). Onder *Instellingen → Weergave → Navigatiebalk* kies je **iOS-achtig** (zwevend, afgerond, met een schuifregelaar voor het **glaseffect**: 0 is ondoorzichtig, 100 is het doorzichtigst en meest vervaagd) of **Android-achtig** (over de volle breedte aan de onderrand, met een pil achter het actieve icoon). Standaard staat de keuze op **Automatisch**: de app herkent het toestel en kiest Android-achtig op Android en iOS-achtig op andere apparaten. De keuze staat bij je account (`navbar_style`, `navbar_glass`) en geldt op al je apparaten.
- **Titelbalk** — bovenaan elke pagina blijft een balk staan met de titel en de hoofdknop (nieuwe bestelling, klant, rol, …) terwijl je scrolt; op een telefoon houdt hij rekening met de uitsparing van camera en notch (`viewport-fit=cover`, `env(safe-area-inset-top)`).
- **Filament** — je rollen met prijs per rol, gewicht, diameter, print- en bedtemperatuur en wat er nog over is;
  de **barcode** bewaar je als identifier: scan hem met de camera van je telefoon (of een barcodescanner, die typt
  gewoon in het veld). Een bekende barcode wordt gemeld en de gegevens van de vorige rol worden meteen ingevuld (wat je zelf al
  typte blijft staan), zodat je alleen nog opslaat, met erbij hoeveel rollen je er nog van hebt. Bovenaan staat de
  **voorraad per soort**: de rollen die je nog hebt met hun gewicht, het totaal per soort en per materiaal (een soort is
  één barcode, of merk + materiaal + kleur). Merk (bijvoorbeeld *Bambu Lab*) en **type** (*Matte*, *Basic*, *Silk*) zijn aparte velden; een bestaande rol houdt wat in het merkveld stond en het type is leeg tot je het invult. Pas je bij een rol met barcode merk, type, materiaal, kleur, gewicht, diameter of temperaturen aan, dan vraagt de app bij het opslaan of de andere rollen met dezelfde barcode ook bijgewerkt moeten worden (alleen wat je veranderde; prijs, wat er nog over is en notities zijn per rol en blijven staan). Je kunt de lijst en de voorraad filteren op **soort** (materiaal), **merk** en **type**; elke keuzelijst past zich aan de vorige keuzes aan. Verbruik van een berekening kun je met één klik van de voorraad afboeken.
  Het menu *Filament* heeft twee onderdelen: **Voorraad** (de soorten als tegels met een spoel-icoon in de kleur van de rol: twee naast elkaar op een telefoon, meer op een breder scherm, hooguit drie rijen met een chevron voor de rest) en **Rollen** (de rolinfo met sorteerknoppen bovenaan: naam, materiaal, resterend, prijs per kg, nieuwste; tik nog eens om om te draaien). De kleur kies je per rol (*Kleur van de rol*); kies je niets, dan wordt hij uit de naam geraden (*zwart*, *Red*, …). Het icoon is in de stijl van de Material Design-iconen getekend, want die hebben geen filamentspoel.
- **Verpakking** — je soorten dozen en ander verpakkingsmateriaal met prijs per stuk. Verpakking hoort bij de **bestelling**, niet bij het model: met
  *Verpakking toevoegen* in de bestelling kies je er een uit de lijst (zie *Verpakking op een bestelling*). Een berekening die al verpakking bevatte, houdt die
  (en de kosten ervan) tot je de regel verwijdert; nieuwe verpakking kun je er niet meer aan toevoegen.
- **Onderdelen** — twee lijsten onder één menu. **Onderdelen** zijn extra onderdelen zoals kabeltjes, connectoren en chips;
  **Accessoires** zijn kabels en laders die bij een product horen. Elk item heeft een prijs per eenheid (per stuk, per meter
  of per kg). In een berekening kies je ze per product uit de lijst bij *Andere onderdelen* of *Accessoires* (of vul je een
  regel zelf in); de prijs wordt in de berekening bewaard.
- **Printers** — aanschafwaarde, levensduur in uren (afschrijving per uur) en vermogen.
- **Energie** — tarieven per kWh, met een standaardtarief.
- Licht/donker/systeem, eigen accentkleur, installeerbaar op je beginscherm.

De kostprijs volgt de spreadsheet: `filament + onderdelen + accessoires + afschrijving + energie` (plus de verpakking van een oudere berekening die er nog in staat), elke
regel op hele centen afgerond vóór het optellen. **Machinetijd (afschrijving en stroom) wordt altijd naar boven
afgerond op hele uren**: 3,06 uur rekent als 4 uur.

**Zakelijk verkopen:** over de verkoopprijs (kostprijs + marge) komt **btw** (standaard 21%, per berekening aan te
passen; 0 = geen btw). Inkoopprijzen voer je excl. btw in. De marge van een berekening is de standaard voor bestellingen; de
**afronding** van de prijs incl. btw (op 5/10/50 cent, hele euro's of eindigend op ,95/,99) en een afwijkende marge stel je **per bestelling**
in (zie *Bestellingen en facturen*): de prijs incl. btw wordt dan naar boven afgerond, je marge geldt als *minimum* en de btw wordt uit de ronde prijs gehaald. Standaard btw en
standaard afronding voor nieuwe bestellingen stel je in onder *Instellingen → Zakelijk → Btw en afronding* (het onderdeel *Zakelijk* zet je eerst aan onder *Instellingen → Algemeen*). Onder *Instellingen → Algemeen* kun je kostprijs, subtotalen en
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
| `AI_IMAGES_ENABLED` | `TRUE` toont de optionele functie *AI-afbeeldingen* (zie [AI-afbeeldingen](#ai-afbeeldingen-optioneel)); alles anders, of leeg, laat haar uit. Standaard `FALSE` |
| `PROXY_HOPS` | Aantal reverse proxies ervoor (vertrouwt `X-Forwarded-*`) |
| `WEB_CONCURRENCY` | Aantal Gunicorn-workers (standaard 2) |
| `APP_IMAGE` | Te draaien image (standaard `ghcr.io/flux76hq/3dprint_pricing:latest`) |

**Camerascannen** (barcode) vraagt, net als passkeys, https en toestemming voor de camera. Chrome/Edge/Android gebruiken
hun eigen scanner; Safari/iOS laadt een meegeleverde scanbibliotheek ([ZXing](../frontend/vendor/zxing/README.md), Apache-2.0).
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
`pip install playwright pillow && python scripts/generate_pwa_assets.py` (zet desnoods `CHROMIUM_PATH`). De server zet de release en bij elke paginalaad een tijdstempel achter de icoon-URL (`apple-touch-icon.png?v=…`), want iOS onthoudt het icoon (of het mislukken ervan) per URL en per website: zo gebruikt een pin op het beginscherm altijd het icoon van het moment, en haalt een iPhone na een update een nieuwe op, ook als er eerder iets misging (bij een iPad kan het wel lukken en bij een iPhone niet). Zie je op iOS nog een leeg of oud icoon: verwijder de app van het beginscherm, sluit Safari helemaal en voeg hem opnieuw toe; iOS bewaart het icoon van het moment waarop je hem toevoegde. Het script schrijft
ook de `<link>`-regels voor de opstartschermen in `index.html`; het manifest bevat alleen PNG-iconen (een SVG-regel kan iOS kiezen en geeft dan een leeg icoon); `backend/tests/test_pwa_assets.py` bewaakt dat bestanden, formaten en links kloppen.

## Lokaal ontwikkelen

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements-dev.txt
python scripts/setup_hooks.py                # pre-commit: versiecheck + agent-instructions
cd backend && PYTHONPATH=. python -m pytest -q
```

De databasetests hebben PostgreSQL nodig: zet `TEST_DATABASE_URL`, of draai als root met PostgreSQL
geïnstalleerd; dan start de testsuite een tijdelijke cluster. Zie [`AGENTS.md`](../AGENTS.md) voor de werkafspraken.

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
De back-up bevat je passkey-publieke sleutels en gehashte herstelcodes, geen geheimen (ook de OpenAI-sleutel van de optionele AI-afbeeldingen niet). Bewaar `.env` apart (in je wachtwoordmanager): zonder `SESSION_SECRET` log je gewoon opnieuw
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
| `backend/app/api.py` | printers, tarieven, filament, verpakking, onderdelen, accessoires, berekeningen, voorkeuren |
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
| **Filamenten** | de filamentbibliotheek: specificaties van filamenten, een Bambu Lab-factuur inlezen, JSON-export en -import en synchroniseren met GitHub; zie *Filamentbibliotheek* |
| **Notificaties** | meldingen (dit apparaat, nieuwe versie, filament bijna op, testmelding, verbindingscontrole, apparatenlijst) en stille uren |
| **Back-up en herstel** | zie *Back-up in de app* |

*Uitloggen* staat onderaan de zijbalk (op een telefoon onderaan *Meer*). *Zakelijk* verbergt alleen dat onderdeel van de instellingen; het menu
*Bestellingen* blijft gewoon zichtbaar. Een onderdeel dat niet getoond wordt (bijvoorbeeld *Zakelijk* terwijl het uit staat) valt terug op
*Algemeen*.

## AI-afbeeldingen (optioneel)

Uit een foto van een print laat de app met OpenAI **GPT Image** een paar realistische productafbeeldingen maken (geen 3D-render), om bij de
berekening te bewaren of als foto voor een webshop of marktplaats te downloaden. De functie bestaat alleen als `AI_IMAGES_ENABLED=TRUE` in
`.env` staat (daarna `docker compose up -d`): zonder die waarde geven de routes `/api/ai-images/…` en `/api/projects/<id>/images…` een 404 en
zie je in de app niets. De server beslist, niet de browser.

1. **API-sleutel**: *Instellingen → AI-afbeeldingen*. Maak een sleutel op platform.openai.com (het account moet bij het afbeeldingsmodel kunnen
   en tegoed hebben). De sleutel wordt versleuteld in de database bewaard (met een sleutel afgeleid van `SESSION_SECRET`) en nooit meer getoond,
   alleen de laatste vier tekens. Wijzig je `SESSION_SECRET`, dan is de sleutel niet meer leesbaar en voer je hem opnieuw in. *Verbinding testen*
   controleert sleutel en model. Het model (standaard `gpt-image-2`) en de kwaliteit (laag/gemiddeld/hoog; hoger kost meer) zijn instelbaar.
2. **Omschrijving**: elke berekening heeft een veld *Omschrijving van het object* (bijvoorbeeld “plantenbak voor op een vensterbank”). Daarmee kiest het
   model een passende achtergrond. Dit veld staat altijd in de berekening, ook als de functie uit staat, en zit in de back-up.
3. **Maken**: open een opgeslagen berekening, kaart *Productafbeeldingen*: upload een foto van het object (JPEG, PNG of WebP, maximaal 8 MB; hij wordt
   opnieuw opgeslagen en tot 2048 px verkleind, zonder metadata) en kies *Afbeeldingen maken*. Er worden vier varianten gemaakt, een voor een: vierkant 1:1,
   liggend 3:2, staand 2:3 en een studiofoto met neutrale achtergrond. Elke afbeelding kost API-tegoed bij OpenAI; de app vraagt eerst bevestiging,
   begrenst het aantal per uur en bewaart er hooguit 12 per berekening. Per afbeelding kun je *Downloaden*, *Als omslag* gebruiken (verschijnt in de lijst met
   berekeningen) of verwijderen.
4. **Op de achtergrond**: het maken gebeurt op de server, niet in je browser. Een draaiende cirkel en grijze plekhouders in de vorm van de komende afbeelding laten de
   voortgang zien (“1 van 4 klaar”); je kunt de pagina verlaten of de browser sluiten, het maken gaat door. In de lijst met berekeningen staat intussen een
   *Afbeeldingen worden gemaakt*-label, en terug in de berekening zie je de voortgang of het resultaat. Per berekening loopt er één reeks tegelijk. Zakt de server
   er tussendoor uit (herstart), dan geeft de app een afbeelding die ruim vijf minuten niet verder kwam op als *onderbroken* en kun je het opnieuw proberen. Wat niet
   lukte staat onder de kaart, met een knop naar het logboek. Een probleem met sleutel, tegoed of model stopt de rest van de reeks meteen; een time-out of
   inhoudsfilter niet.
5. **Logboek**: *Instellingen → AI-afbeeldingen* heeft onder de sleutel een *Logboek* met wat er gebeurde: foto geüpload, reeks in de wachtrij, afbeelding gestart en
   klaar (met de duur), een gewijzigde sleutel of gewijzigde instellingen, en elke fout met de melding en wat OpenAI zelf zei (bijvoorbeeld `HTTP 429
   insufficient_quota`). Stukjes die op een sleutel lijken worden eruit gehaald. De nieuwste regel staat bovenaan, het logboek ververst zichzelf, de laatste 500 regels blijven
   bewaard en het is leeg te maken. Het logboek en de voortgang zitten niet in de back-up.

De foto en de gemaakte afbeeldingen staan in de database (tabel `project_images`) en zitten in de back-up; de API-sleutel zit er bewust niet in. De wachtrij en het logboek
(`ai_image_jobs`, `ai_image_log`) beschrijven lopend werk en geschiedenis en zitten er niet in. De foto en
je omschrijving gaan naar OpenAI; wat daar mee gebeurt volgt hun voorwaarden.

## Bestellingen en facturen

**Klanten** (menu *Klanten*): een klant heeft een klantnummer, naam, adres, postcode, plaats, land, e-mail, telefoon en een notitie (alleen voor jezelf). Laat je het klantnummer leeg, dan krijgt de klant het volgende vrije hele getal (`1`, `2`, …); een eigen nummer (`K9999`) mag ook, maar is uniek (hoofdletters tellen niet). Een klant met bestellingen kan niet verwijderd worden. Bestaande bestellingen kregen bij het bijwerken automatisch een klant: één per naam + klantnummer, met een vrij nummer als het klantnummer leeg of dubbel was.

**Bestellingen** (menu *Bestellingen*): *Nieuwe bestelling* vraagt de besteldatum en leverdatum, de **klant** (kies een bestaande klant of maak er op dat moment een aan; een bestelling hoort altijd bij een klant; de gegevens staan bij de klant) en de modellen. De bestelling bewaart een kopie van de klantgegevens: bewerk je een klant, dan verandert die kopie in zijn bestellingen **zonder factuur**; een factuur die al een nummer heeft blijft zoals hij was, tot je de bestelling opnieuw opslaat. Bij *Model toevoegen* zoek je een berekening op nummer (`2`, `#2`)
of op een deel van de naam; kies je hem nog eens, dan gaat het aantal omhoog. Een model op een bestelling bewaart de **kostprijs** (excl. btw) van de
berekening zoals die er op dat moment uit zag, en heeft een eigen **marge** (standaard die van de berekening, per regel aan te passen). De **afronding** van de prijs
incl. btw (op 5/10/50 cent, hele euro's of eindigend op ,95/,99) kies je **per bestelling**, boven de modellen; ze geldt voor alle modellen in die
bestelling, de marge is dan het *minimum* en de app toont onder de regel de marge die het echt wordt. De prijs per stuk volgt uit kostprijs, marge, btw en afronding en wordt
door de server uitgerekend; een latere wijziging van de berekening verandert een bestelling niet, tenzij je op de **sync-knop** naast het model klikt: die haalt de kostprijs van de berekening zoals die nu is opnieuw op (marge, btw en aantal van de regel blijven; sla de bestelling daarna op). De accessoireregels van die berekening worden niet meegenomen. Bestellingen van vóór deze functie, en eigen regels, houden de prijs die erbij stond of die je typt. Met *Eigen regel toevoegen* komt er een regel bij die niet bij een berekening hoort
(bijvoorbeeld verzending). De **totalen rekent de server uit** (`backend/app/orders.py`, nooit de browser): de btw wordt per tarief
uit de som van de regels gehaald, zodat wat de klant betaalt precies de som van de regels is. In de lijst filter je op status
en zoek je op naam, klantnummer, plaats, bestelnummer of factuurnummer; de status zet je daar met één keuzelijst, of in de bestelling zelf.

**Losse accessoires op een bestelling**: met *Accessoire toevoegen* kies je een accessoire uit je lijst (*Onderdelen → Accessoires*, gearchiveerde staan er niet bij) en komt het als optionele regel tegen inkoopprijs (marge 0, aanpasbaar) op de bestelling, ook zonder berekening. Kies je hetzelfde nog eens, dan gaat het aantal omhoog. Een accessoire per meter of per kg krijgt dat achter de omschrijving.

**Verpakking op een bestelling**: met *Verpakking toevoegen* kies je verpakkingsmateriaal uit je lijst (*Verpakking*, gearchiveerde staan er niet bij) en komt het als gewone regel (niet optioneel) tegen inkoopprijs (marge 0, aanpasbaar) op de bestelling, zodat het in het totaal en op de factuur zit. Kies je hetzelfde nog eens, dan gaat het aantal omhoog. Wat je per bestelling nodig hebt (één doos voor drie modellen) bepaal je dus zelf, in plaats van per model.

**Accessoires op een bestelling**: kies je een berekening die accessoires (kabels, laders) heeft, dan komt het model op één regel en elke accessoire op een eigen regel, aangevinkt als *Optioneel (accessoire)* en tegen **inkoopprijs** (marge 0; de btw en afronding van de bestelling gelden wel). Het model houdt de rest van de kostprijs en de marge. Zo'n regel kun je aanpassen of weghalen als de klant hem niet wil, en je kunt elke regel zelf als optioneel markeren. Optionele regels tellen gewoon mee in het totaal, maar de factuur zet ze **apart onder het kopje *Accessoires (optioneel)*** na de andere regels, want het product werkt ook zonder. In een Word-sjabloon, waar één rij voor elke regel wordt herhaald, staat achter de omschrijving *(optioneel)*.

**Facturen**: *Factuur genereren (PDF)* maakt de factuur van de bestelling als **PDF**, bewaart hem op de server en downloadt hem. De eerste keer krijgt de factuur een
nummer (`JJJJ-0001`, per jaar doorgeteld, nooit tweemaal uitgegeven) en een factuurdatum (vandaag, daarna aan te passen);
daarna maakt dezelfde knop (*Factuur opnieuw genereren*) hem opnieuw met hetzelfde nummer en wat de bestelling nu zegt, en vervangt de bewaarde PDF. *Factuur downloaden (PDF)* geeft de bewaarde PDF zoals hij gemaakt is, zonder opnieuw te genereren. De PDF’s staan in de database (en in de back-up van de app). Gegevens van je bedrijf (naam, adres, telefoon, e-mail, website, KvK, btw-nummer, IBAN en BIC, betaaltermijn, taal
van de factuur, een tekst onderaan en of er een betaal-QR op komt) vul je in onder *Instellingen → Zakelijk → Bedrijfsgegevens*, je
**logo** (PNG of JPEG, maximaal 2 MB) onder *Instellingen → Zakelijk → Logo*. Per bestelling vul je ook het **klantnummer** en een
**Betreft**-regel in (leeg: “Bestelling” met het nummer).

**De ingebouwde factuur** heeft de layout van het voorbeeld dat de eigenaar aanleverde (Open Sans, A4): het logo linksboven, rechts de
bedrijfsgegevens (naam en adres, daaronder in kleine letters btw-nummer, KVK, telefoon, e-mail, website, IBAN en BIC), links het
adres van de klant, rechts factuurdatum, vervaldatum en klantnummer, dan *Factuur: nummer* en *Betreft:*, een tabel met aantal,
beschrijving en het bedrag excl. en incl. btw per regel (met het btw-tarief eronder), de totalen per btw-tarief (*Btw hoog (21%)*,
*Btw laag (9%)*), de betaalzin en een **betaal-QR**. Datums staan als `dd/mm/jjjj`. De QR is een SEPA-code (EPC069-12) die bankapps
lezen: bedrag, IBAN, naam en factuurnummer worden ingevuld (dus geen iDEAL-link); hij komt er alleen als IBAN en bedrijfsnaam zijn
ingevuld en je hem niet hebt uitgezet. Onder *Instellingen → Zakelijk → Betaal-QR* zet je de QR-code **uit** (dan staat er niets op de factuur en verdwijnt `{{betaal_qr}}` uit een Word-sjabloon) of vul je een **eigen betaallink** in: een https-adres met de velden `{bedrag}` (29.20), `{bedrag_cent}` (2920), `{factuurnummer}`, `{klantnummer}`, `{betreft}`, `{iban}` en `{bestelnummer}` (elk veilig voor een adres gemaakt), bijvoorbeeld `https://betaal.voorbeeld.nl/factuur/{factuurnummer}?bedrag={bedrag}`. Die link komt dan in de QR-code, ook zonder IBAN; leeg laten geeft de SEPA-code. Per regel zijn netto en btw zo verdeeld dat de regels precies optellen tot de totalen
(`orders._split_net`: afgerond naar beneden, de overgebleven centen naar de grootste resten). Het lettertype (Open Sans, SIL Open Font
License) staat in `backend/app/fonts/` met zijn licentie; ontbreekt het, dan valt de PDF terug op Helvetica.

**Sjabloon** (*Instellingen → Zakelijk → Factuursjabloon*, maximaal 5 MB, één tegelijk; een nieuw bestand vervangt het vorige):

- **Zonder sjabloon** gebruikt de app de ingebouwde PDF hierboven.
- **Word (`.docx`)**: zet velden tussen dubbele accolades in je document (kop, voet en tabellen werken ook). Eén tabelrij met
  `{{regel.omschrijving}}`, `{{regel.aantal}}`, `{{regel.bedrag_excl}}`, `{{regel.bedrag_incl}}`, `{{regel.btw}}` (ook `{{regel.prijs}}`
  per stuk, `{{regel.totaal}}`, `{{regel.nr}}` en `{{regel.optioneel}}`, dat *optioneel* zegt bij een accessoire en anders leeg is) wordt voor elke regel van de bestelling herhaald; een sjabloon zonder zo'n rij wordt bij het uploaden geweigerd. De factuur is altijd een PDF: de app zet
  het Word-bestand met LibreOffice (zit in de Docker-image) om, met de lettertypen die op de server staan (Open Sans zit erbij; een ander lettertype in je sjabloon wordt vervangen als het ontbreekt, controleer dat in de PDF). Een veld dat niet bestaat blijft zichtbaar in de factuur staan, zodat je een typefout ziet.
  `{{logo}}` en `{{betaal_qr}}` worden afbeeldingen (je logo en de betaal-QR; zonder logo of IBAN verdwijnt de tekst). *Voorbeeldsjabloon
  downloaden* geeft een Word-bestand in dezelfde layout als de ingebouwde factuur, om mee te beginnen; het gebruikt Open Sans (Word
  neemt een ander lettertype waar het ontbreekt).
- **PDF als briefpapier**: de eerste pagina van je PDF blijft zoals hij is (logo, bedrijfsgegevens) en de factuur wordt erop gezet,
  tussen de marges boven en onder die je bij het uploaden opgeeft (standaard 55 en 25 mm; later aan te passen met *Marges
  opslaan*). Het logo en de bedrijfsgegevens uit de instellingen worden dan niet nog eens afgedrukt (de betaal-QR wel). Een lange bestelling loopt door op een
  tweede pagina op hetzelfde briefpapier.

**Factuurnummer-sjabloon:** onder *Instellingen → Zakelijk → Bedrijfsgegevens* stel je in hoe factuurnummers eruitzien: een voorvoegsel naar keuze en daarachter het volgnummer, standaard `{JJJJ}-{NNNN}` (2026-0001). `FLX-{JJJJ}-{NNNN}` geeft FLX-2026-0001; `{JJJJ}`/`{YYYY}` is het jaar en `{JJ}`/`{YY}` het jaar in twee cijfers (de teller begint dan elk jaar opnieuw bij 1); het aantal N's is het minimum aantal cijfers; zonder jaar telt het gewoon door. Precies één volgnummer, daaromheen alleen letters, cijfers, spatie en `. _ / -` (max. 40 tekens). Een wijziging geldt voor nieuwe facturen; een factuur die al een nummer heeft houdt dat. Een nummer dat al bestaat wordt overgeslagen.

Beschikbare velden (ook te zien onder *Beschikbare velden* bij het sjabloon): `logo`, `betaal_qr`, `factuurnummer`, `factuurdatum`,
`vervaldatum`, `betreft`, `bestelnummer`, `besteldatum`, `leverdatum`, `opmerking` (de notities van de bestelling), `klant.naam`,
`klant.nummer`, `klant.adres`,
`klant.postcode`, `klant.plaats`, `klant.postcode_plaats`, `klant.land`, `klant.email`, `klant.telefoon`, `klant.adresblok` (naam, adres,
postcode en plaats, land onder elkaar), `bedrijf.naam`, `bedrijf.adres`, `bedrijf.postcode`, `bedrijf.plaats`, `bedrijf.land`,
`bedrijf.email`, `bedrijf.telefoon`, `bedrijf.website`, `bedrijf.kvk`, `bedrijf.btw_nummer`, `bedrijf.iban`, `bedrijf.bic`,
`bedrijf.tekst`, `totaal_excl`, `btw_totaal`, `totaal`, `btw_overzicht` (per tarief, labels en bedragen samen), `btw_labels` en
`btw_bedragen` (dezelfde regels apart, om in twee kolommen te zetten), `betaaltekst` (bedrag, vervaldatum en factuurnummer) en de
regelvelden hierboven. Het sjabloonbestand, het logo en de gemaakte factuur-PDF’s staan in de **database** (niet onder `UPLOAD_DIR`), dus ze blijven bestaan als je de container opnieuw bouwt of de uploads-map kwijtraakt; ze worden met de rest meegenomen in de
back-up van de app. Een sjabloon of logo van een eerdere versie (nog als bestand onder `UPLOAD_DIR`) wordt de eerste keer dat het gebruikt wordt in de database gezet; is dat bestand al weg, upload het dan één keer opnieuw. Word- en PDF-bestanden worden als onbetrouwbaar behandeld: grootte en uitgepakte grootte zijn begrensd, Word
wordt gelezen met `python-docx` (zonder XML-entiteiten) en PDF alleen met `pypdf`; er wordt niets uitgevoerd.

## Filamentbibliotheek

*Instellingen → Filamenten* bevat de **bibliotheek**: de gegevens van filamenten (merk, type, materiaal, kleur en kleurcode, **filament-ID**
van de leverancier, artikelnummer (SKU), barcode, bijvulling of met spoel, gewicht, diameter, temperaturen en een richtprijs excl. btw), los van de
rollen in je voorraad. Voeg je onder *Filament* een **nieuwe rol** toe, dan kies je bovenaan het formulier een filament uit de bibliotheek: merk, type,
kleur, gewicht, diameter, temperaturen, barcode en prijs worden ingevuld, de rol begint vol en je kunt alles nog aanpassen. Zonder bibliotheek
(of met *Niet uit de bibliotheek*) werkt het formulier als altijd.

Drie manieren om de bibliotheek te vullen zonder te typen:

- **Bambu Lab-factuur importeren.** Kies de PDF-factuur uit de Bambu Lab-webshop. De app leest hem (alleen met `pypdf`, met een grens aan grootte en aantal
  pagina’s) en laat eerst zien wat erin staat: per filamentregel het merk, materiaal en type (*PLA* + *Basic*), de kleur, het filament-ID (het nummer tussen
  haakjes achter de kleur), de SKU, het gewicht en de diameter (uit de SKU), of het een bijvulling is (SKU eindigt op `FREE`), de **richtprijs** (de lijstprijs; op de
  factuur staat hij incl. btw, de app rekent om naar excl. btw; een korting is een actie en geen prijs) en de barcode. Per regel kies je of het filament in de bibliotheek komt. **De voorraad verandert
  hier nooit**: de bibliotheek is een losstaande lijst van de filamenten die bestaan, geen lijst van wat je hebt. Een filament dat er al staat krijgt de nieuwe richtprijs en
  wat het nog mist (SKU, filament-ID, barcode), maar zijn eigen gegevens worden nooit overschreven. Regels die geen filament zijn worden overgeslagen en genoemd; kloppen de regels niet met het factuurtotaal, dan staat er een waarschuwing. Andere webshops dan Bambu Lab worden niet herkend.

  **Barcode uit de webshop.** Bij het inlezen zoekt de server elk filament op in de Bambu Lab-webshop en neemt het **ID uit de productaddress** over als *barcode*
  (`…/nl/products/pla-matte?id=43992833229019`: `43992833229019`). Dat is het nummer van één kleur, als bijvulling of met spoel, in één gewicht. De pagina’s van de webshop vermelden
  hun varianten als JSON-LD; een regel van de factuur wordt gevonden op zijn filament-ID tussen haakjes, bijvulling of spoel, en gewicht. Het zijn de ID’s van de **EU-webshop**
  (`eu.store.bambulab.com`): stuurt de webshop de server door naar de winkel van een andere regio (waar de ID’s anders zijn) of is hij niet bereikbaar, dan wordt er niets opgeslagen en staat er een
  waarschuwing; de import werkt dan gewoon door zonder barcodes. Er wordt alleen die ene host benaderd, nooit een adres uit een verzoek. Let op: rollen met een barcode vormen in de voorraad één soort per
  barcode; een rol die je eerder zonder barcode invoerde, is dus een andere soort dan een rol met die barcode.
- **Exporteren en importeren (JSON).** *Exporteren (JSON)* downloadt de bibliotheek (`printpricing-filaments-JJJJ-MM-DD.json`, zonder id’s, met getallen als getallen,
  dus ook met de hand te bewerken). *Importeren (JSON)* leest zo’n bestand, controleert het helemaal met dezelfde regels als handmatig invoeren (één fout regel stopt alles en
  noemt het regelnummer) en laat eerst zien hoeveel nieuw, bijgewerkt en ongewijzigd is. Wat het bestand voor een bekend filament vermeldt, wordt overschreven; wat het niet vermeldt blijft, en er wordt **nooit iets verwijderd**. Zou een regel een filament een kopie van een ander maken, dan stopt de import met dat regelnummer.
- **Synchroniseren.** De knop *Synchroniseren* haalt de gedeelde bibliotheek op van GitHub en voegt op dezelfde manier toe en werkt bij (eerst een bevestiging met de aantallen). De
  **server** haalt het bestand op, niet de browser. Het adres staat in `FILAMENT_LIBRARY_URL` (standaard `library/filaments.json` van deze repository): alleen `https` op
  `raw.githubusercontent.com` of `gist.githubusercontent.com`, een doorverwijzing wordt niet gevolgd, het bestand mag hoogstens 2 MB zijn en het adres komt nooit uit een verzoek. Leeg zet de
  knop uit. De container moet GitHub kunnen bereiken; lukt dat niet, dan zegt de app dat de bron niet bereikbaar is.

**Nooit hetzelfde filament twee keer.** Eén regel bepaalt wanneer twee filamenten *hetzelfde* zijn: ze delen de **SKU**, of de **barcode**, of het **filament-ID** (bijvulling en met spoel
hebben hetzelfde ID, dus tellen die apart), of merk, materiaal, type, kleur, gewicht, diameter en bijvulling (hoofdletters en spaties tellen niet). Handmatig toevoegen, wijzigen, importeren,
synchroniseren, de factuur, een nieuwe rol en het terugzetten van een back-up gaan er allemaal doorheen: een kopie wordt geweigerd (*Dit filament staat al in de bibliotheek*), en schrijven
gebeurt onder een slot, zodat twee verzoeken tegelijk er niet toch twee van maken. Twee dubbele vermeldingen die er al stonden (uit een oudere versie) blijven bewerkbaar; alleen een *nieuwe* overeenkomst wordt geweigerd.

**Merk kiezen en Bambu Lab-kleuren.** Bij een nieuwe rol is *Merk* een keuzelijst met de merken die er al zijn (op rollen en in de bibliotheek, plus altijd Bambu Lab); staat een merk er nog niet bij, dan kies je
*Nieuw merk…* en typ je de naam. Kies je **Bambu Lab**, dan verschijnt eronder een paneel waar je de **soort** (PLA Basic, PLA Matte, PETG HF, …; een vaste lijst in de code, `bambu_store.CATALOG`) en daarna de **kleur** kiest. De
kleuren worden door de server uit de Bambu Lab-webshop gehaald (`GET /api/bambu/products/<soort>`; dezelfde EU-webshop en voorzorgen als bij de factuur, een soort die niet in de lijst staat wordt nooit opgevraagd) en een keuze vult
het formulier in: type, materiaal, kleur, gewicht (1 kg, 0,5 kg, …), diameter (1,75 mm) en als **barcode** het winkel-ID van die kleur (bijvulling en met spoel hebben elk een eigen ID). De webshop noemt **geen temperaturen en geen prijs**; die komen uit
de bibliotheek als die dit filament kent, anders uit een eerdere rol met dezelfde barcode, anders vul je ze zelf in. Is de webshop niet bereikbaar, dan staat er een melding en vul je het formulier gewoon met de hand in. Het filament-ID en of het een bijvulling is gaan mee naar de bibliotheek als je *Ook aan de bibliotheek toevoegen* laat aanstaan.

**Een rol met de hand toevoegen.** Onder *Filament → Nieuwe rol* staat de keuze *Ook aan de bibliotheek toevoegen* (standaard aan, alleen bij een nieuwe rol). Staat het filament er nog niet in, dan komt het erin met wat de rol
over het filament zegt (merk, type, materiaal, kleur, kleurcode, barcode, gewicht, diameter, temperaturen; niet de prijs of wat er nog over is). Staat het er al in, dan krijgt dat filament wat het nog mist (een barcode, een kleurcode,
temperaturen), zonder iets te overschrijven. Dezelfde barcode is hetzelfde filament; zonder barcode dezelfde naam, hetzelfde gewicht en dezelfde diameter. Past de rol bij meer dan één vermelding (bijvulling én met spoel), dan blijft de bibliotheek ongemoeid.

De bibliotheek zit in de back-up (formaat 5; een oudere back-up laat haar leeg bij herstellen).

## Back-up in de app

*Instellingen → Back-up en herstel* downloadt al je gegevens als één JSON-bestand (`printpricing-backup-JJJJ-MM-DD.json`):
je instellingen (thema, taal, btw, afronding, stille uren, bedrijfsgegevens…), printers, energietarieven, verpakkingen, onderdelen, accessoires, de filamentbibliotheek, filamentrollen,
berekeningen (met hun nummers), klanten, bestellingen met hun factuurnummers en bewaarde factuur-PDF’s, het factuursjabloon en het logo, op wens ook de geüploade printbestanden (groter). **Niet** in het bestand: passkeys, herstelcodes, het wachtwoord
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
