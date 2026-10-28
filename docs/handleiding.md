# 3D Print Pricing: handleiding en beheer

> Dit is de uitgebreide handleiding (Nederlands): functies in detail, installatie, instellingen, meldingen, back-up en beheer.
> Een korte presentatie met schermafbeeldingen staat in de [README](../README.nl.md) ([English](../README.md)).

Zelf-gehoste PWA om de **kostprijs van 3D-prints** uit te rekenen en de voorraad en tarieven bij
te houden waar die prijzen op gebaseerd zijn. Inloggen gaat met **passkeys** of, waar die niet kunnen (bijvoorbeeld op een IP-adres in je eigen netwerk), met een **wachtwoord**.

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

Zonder `--domain` blijven `RP_ID` en `RP_ORIGINS` leeg: de app volgt dan het adres waarop je hem opent, ook een IP-adres, genoeg om het uit te proberen. Een passkey vraagt wel een domein met https (zie hieronder).
Handmatig kan ook: `cp .env.example .env` en de waarden invullen.

Open daarna het adres en doorloop de **onboarding**:

1. Vul de **setupcode** en je naam in.
   - *Wat is het?* Een korte eenmalige code die bewijst dat jij de eigenaar bent, zodat niet de eerste bezoeker de app overneemt.
   - *Waar staat hij?* Op de server, in het bestand `.env` naast `docker-compose.yml`, op de regel `SETUP_CODE=…`. Alles achter het is-teken is de code. `init_env.py` toonde hem na het aanmaken; opnieuw tonen kan met `grep SETUP_CODE .env`.
   - *Waar vul je hem in?* In het veld **Setupcode** op het eerste scherm van de app (dat scherm legt het ook uit), samen met je naam. Je hebt hem alleen voor deze eerste keer nodig.
   - Heb je `SETUP_CODE` in `.env` aangepast terwijl de app al draaide? Voer `docker compose up -d` uit, zodat de app de nieuwe waarde leest.
2. Kies hoe je inlogt: maak een **passkey** aan (vingerafdruk, gezicht of apparaatcode), of kies **een wachtwoord** (minstens 12 tekens). Werkt een passkey niet op het adres dat je gebruikt (een IP-adres, of zonder https), dan zegt het scherm dat en staat het wachtwoord al open.
3. **Bewaar de 8 herstelcodes** — ze worden één keer getoond en werken elk één keer.

Daarna is de onboarding gesloten. Meer passkeys voeg je toe onder *Instellingen → Beveiliging*;
verwijderen of nieuwe herstelcodes vraagt een verse bevestiging (een passkey, of je wachtwoord als je geen passkey hebt).

### Instellingen (`.env`)

| Variabele | Betekenis |
|---|---|
| `WEB_PORT` | Poort van de app; compose publiceert en de app luistert op deze ene waarde |
| `DATA_PATH` | Map op de host voor alle data: de database (`postgres/`) en de geüploade bestanden (`uploads/`); blijft bestaan bij herbouwen en updaten. Zie *Waar de data staat* |
| `MAX_UPLOAD_MB` | Grootste STL/3MF-upload in MB (standaard 50) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Database; gebruik een wachtwoord met alleen letters en cijfers |
| `RP_ID` | Optioneel. Domein waarop de app draait, zonder schema of poort; passkeys zijn eraan gebonden. Leeg = het adres waarop de app wordt geopend |
| `RP_ORIGINS` | Optioneel. Volledige origin(s), komma-gescheiden, bijv. `https://print.voorbeeld.nl`. Gezet: schrijvende verzoeken van een andere origin worden geweigerd. Leeg = het adres waarop de app wordt geopend |
| `RP_NAME` | Naam die in de passkey-prompt staat |
| `SETUP_CODE` | Eenmalige code voor de onboarding, zodat niet de eerste bezoeker de app overneemt |
| `SESSION_SECRET` | Ondertekent sessiecookies, minimaal 32 tekens |
| `SESSION_HOURS` | Levensduur van een sessie (standaard 24) |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | Sleutelpaar voor push-meldingen (`python scripts/generate_vapid.py`); leeg = meldingen uit. De private sleutel is geheim; een ander paar maakt bestaande aanmeldingen onbruikbaar |
| `VAPID_SUBJECT` | Contactadres voor de pushdiensten (`mailto:…` of https-url); leeg = `mailto:admin@<RP_ID>` (zonder `RP_ID`: `mailto:admin@localhost`; zet het zelf als je meldingen gebruikt) |
| `AI_IMAGES_ENABLED` | `TRUE` toont de optionele functie *AI-afbeeldingen* (zie [AI-afbeeldingen](#ai-afbeeldingen-optioneel)); alles anders, of leeg, laat haar uit. Standaard `FALSE` |
| `PROXY_HOPS` | Aantal reverse proxies ervoor (vertrouwt `X-Forwarded-*`) |
| `WEB_CONCURRENCY` | Aantal Gunicorn-workers (standaard 2) |
| `PRINTPRICING_UPDATE_CHECK` | De updatecontrole (zie *Meldingen en updates*). Standaard aan; `false` (ook `0`, `no`, `off`) zet hem uit, voor een installatie die niet naar buiten mag bellen |
| `PRINTPRICING_TAG` | Welke build draait: `latest` (stabiel, standaard), `beta` of een versienummer als `0.26.15`; vervangt `APP_IMAGE`. Dezelfde waarde gaat naar de app, die op `beta` een beta-label toont |

**Camerascannen** (barcode) vraagt, net als passkeys, https en toestemming voor de camera. Chrome/Edge/Android gebruiken
hun eigen scanner; Safari/iOS laadt een meegeleverde scanbibliotheek ([ZXing](../frontend/vendor/zxing/README.md), Apache-2.0).
Weigert de telefoon de camera, dan toont het scanvenster de stappen om dat te herstellen (op Android: app-icoon ingedrukt houden → App-info →
Rechten → Camera → *Alleen tijdens gebruik van de app*) en een knop *Opnieuw proberen*; de barcode intypen blijft altijd mogelijk.
Eén barcode hoort bij een *product*: meerdere rollen van hetzelfde filament mogen dezelfde barcode hebben.

**Passkeys vragen https** (behalve op `http://localhost`) en een **domeinnaam**: openen via een IP-adres
werkt niet, en dan log je in met een wachtwoord. Wil je passkeys, zet er dan een reverse proxy met TLS voor en stel `RP_ID`/`RP_ORIGINS` in op
dat domein: een passkey is aan `RP_ID` gebonden, dus zet het vast zodra je passkeys gebruikt. Zonder `RP_ID` en `RP_ORIGINS` volgt de app het adres waarop hij wordt
geopend (`X-Forwarded-Host` en `X-Forwarded-Proto` van je proxy tellen mee); schrijvende verzoeken moeten dan van een pagina komen die de app zelf van dat adres heeft
geleverd. Wijzig je `RP_ID` later, dan werken bestaande passkeys niet meer; log dan in met een herstelcode.

## Home Assistant-app

De app is ook als Home Assistant-app (voorheen add-on) te installeren, voor Home Assistant OS en Supervised. Voeg onder
**Instellingen > Apps > App installeren > Repositories** het adres `https://github.com/Flux76HQ/3dprint_pricing` toe en installeer *3D Print Pricing*.
Home Assistant bouwt de app dan op het apparaat (`homeassistant/Dockerfile`, op de image van dezelfde versie); de stappen voor de gebruiker staan op het
tabblad Documentatie van de app (`homeassistant/DOCS.md`: tweetalig, Nederlands eerst, en een test controleert dat elke optie erin staat). De knop *Webinterface openen* wijst naar poort 6080 (`webui` in `config.yaml`); er is geen Ingress.

- **Eén container, twee processen.** Home Assistant draait één container per app, dus `homeassistant/run.py` start PostgreSQL 17 (alleen op `127.0.0.1`)
  en daarna de eigen `entrypoint.sh` van de image (migraties, gunicorn). Stopt een van beide, dan stopt het andere en eindigt `run.py`, zodat de watchdog van
  Home Assistant de app herstart. De map `/data` van de app is `DATA_PATH`, ingedeeld als in `docker-compose.yml`: de database in `/data/postgres`, de
  uploads in `/data/uploads`. De geheimen die in `.env` zouden staan (sessiesleutel, databasewachtwoord, push-sleutels) maakt `run.py` één keer en bewaart
  ze in `/data/secrets.json`; de opties van de app (`rp_id`, `rp_origins`, `setup_code`, `proxy_hops`, `max_upload_mb`, `ai_images_enabled`, `spoolman_url`,
  `update_check`) zijn de variabelen uit `.env.example` met dezelfde betekenis. Een nieuwe variabele in `.env.example` die in Home Assistant instelbaar moet
  zijn, wordt dus ook een optie in `homeassistant/config.yaml`, `run.py` en beide `translations/`.
- **Back-up.** `backup: cold`: Home Assistant stopt de app tijdens een back-up, want een draaiende database is geen consistente kopie. Verplaatsen tussen
  Docker Compose en Home Assistant gaat met de back-up in de app (Instellingen > Systeem).
- **Versie.** `version` in `homeassistant/config.yaml` is de versie van de image waarop de app gebouwd wordt. Die zet de pijplijn (`scripts/bump_version.py`)
  gelijk met `VERSION`; een pull request raakt hem niet aan. Een wijziging in `homeassistant/` telt als code en verhoogt het versienummer bij de promotie.
- **PostgreSQL 17.** Hetzelfde hoofdnummer als `postgres:17-alpine` in de compose-file; de Dockerfile vraagt `postgresql-17` met name. Een datamap van een
  ander hoofdnummer opent PostgreSQL niet, en `run.py` weigert te starten in plaats van eraan te komen.
- **Geen Ingress.** Passkeys zijn gebonden aan het domein waarop de app staat, en de app is gemaakt om op de root van een eigen domein te draaien. Gebruikers
  zetten er voor passkeys een reverse proxy met https voor (poort 6080) en vullen `rp_id` in; met een wachtwoord werkt de app ook op `http://<adres van Home Assistant>:6080`.
- **amd64 en aarch64.** `docker.yml` en `docker-beta.yml` bouwen de image voor `linux/amd64` en `linux/arm64` onder één tag (een manifestlijst); Docker en de
  Supervisor halen zelf de helft die past. `arch` in `config.yaml` heet in Home Assistant `amd64` en `aarch64`. `scripts/test_homeassistant_addon.py` laat de test
  falen zodra de platformen in de workflows en `arch` niet precies gelijk zijn. De job `docker-build` bouwt de image ook voor arm64 (onder QEMU), zodat een
  wijziging die alleen daar breekt op de pull request opvalt; de app-image zelf wordt in CI alleen op amd64 gestart.
- **Test.** De job `docker-build` bouwt de app op de zojuist gebouwde image, start hem met een voorbeeld-`options.json`, wacht op `/readyz` en stopt hem weer
  (afsluitcode 0).

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
eerst of je die wilt kwijtraken. *Instellingen → Systeem → Updatecontrole* toont de geïnstalleerde versie en controleert op verzoek.

**Nieuwe release (updatecontrole).** Los van het bovenstaande (dat merkt dat *de server* is bijgewerkt) vraagt de server aan GitHub of er een nieuwere release is dan die hij draait, en meldt dat alleen aan de ingelogde eigenaar: een balk bovenaan (“Nieuwe release beschikbaar: vX (je hebt vY)”) met *Bekijken* (opent *Instellingen → Systeem → Updatecontrole*) en *Later* (voor die versie; een nog nieuwere versie meldt zich weer), en een stip bij *Instellingen* (of *Meer*). Onder *Updatecontrole* staan de geïnstalleerde en de nieuwste versie, wanneer er voor het laatst gekeken is, *Nu controleren*, een link naar de release notes en hoe je bijwerkt; ook staat daar of de controle uit staat, of er nog geen release is, of waarom het mislukte (“limiet van GitHub bereikt (HTTP 403)”, certificaat, time-out, geen verbinding). De app **meldt alleen**: bijwerken, herstarten of downloaden doet hij nooit; dat doe je zelf op de server (zie *Deploy en update*).
- De controle leest de nieuwste gepubliceerde, niet-pre-release **GitHub Release** van deze repository, via de doorverwijzing van `github.com/Flux76HQ/3dprint_pricing/releases/latest` (niet via `api.github.com`, dat per IP-adres maar 60 aanvragen per uur toestaat). De aanvraag draagt een vaste `User-Agent` en niets over jouw installatie: geen versie, geen id, geen gegevens. Een beta-build (`PRINTPRICING_TAG=beta`) ziet dus alleen stabiele releases en nooit een nieuwere beta.
- Het antwoord wordt per worker in het geheugen bewaard: zes uur na een succes, tien minuten na een mislukking; *Nu controleren* slaat dat over maar heeft een ondergrens van 30 seconden. Een mislukking houdt het laatste goede antwoord vast, zodat een gemelde update niet verdwijnt door een storing. Uitzetten: `PRINTPRICING_UPDATE_CHECK=false` in `.env` (dit is een nieuwe, optionele variabele: wie niets doet heeft de controle aan; `docker-compose.yml` geeft `.env` al door).

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

### Waar de data staat
Alles staat in **één map op de host**, `DATA_PATH` (op een server bijvoorbeeld `/srv/printpricing`, op Unraid `/mnt/user/appdata/printpricing`):

```
/srv/printpricing/postgres   de database (PostgreSQL)
/srv/printpricing/uploads    de geüploade STL/3MF-bestanden
/srv/printpricing/backups    de dumps die `scripts/update.sh` maakt
```

Het zijn gewone mappen, **geen Docker-volumes**: `docker compose down -v`, een `docker system prune --volumes`, opnieuw bouwen en updaten raken ze niet (een test, `test_deploy_layout.py`, laat
de CI falen als de compose-file ooit een volume voor de data gebruikt). De app-container ziet `DATA_PATH` als `/data`; de database-container mount alleen `DATA_PATH/postgres`.
**`DATA_PATH` is altijd een absolute map van de Docker-host, nooit `./data`.** Een relatief pad wordt opgelost door het hulpmiddel dat de stack start, niet door de app: een hulpmiddel dat bij elke deploy een verse checkout maakt, begint met een lege database, en Dockhand op Unraid zette `./data` in een map in het RAM-geheugen van de host (`/appdata/...` in plaats van `/mnt/user/appdata/...`), die bij de volgende herstart leeg is. Compose weigert te starten zonder `DATA_PATH`. Start de app-container met een relatief pad, dan zegt hij dat bij het opstarten (*WARNING: DATA_PATH is …, a relative path*); start hij zonder
`/data`-mount, dan zegt hij ook dat (*WARNING: /data is not a mounted folder*), want de uploads verdwijnen dan met de container.

**Staat de data in een andere map dan `DATA_PATH`?** Controleer waar de database echt staat:
```bash
docker inspect $(docker compose ps -aq db) --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'
```
Moet de bron `DATA_PATH/postgres` zijn en is dat niet zo, zet dan in `.env` een absolute `DATA_PATH` en draai op de host `sh scripts/migrate_data.sh` (of `--check` om alleen te zien wat er zou gebeuren). Dat stopt de stack, kopieert `postgres/`, `uploads/` en `backups/` naar `DATA_PATH`, controleert de kopie en laat de oude map staan (hij zegt waar). Daarna `docker compose up -d`. `scripts/update.sh` doet dit zelf vóór de update; een update via Dockhand voert dat script niet uit, draai het daar één keer met de hand. Staat er in `DATA_PATH/postgres` al een database, dan weigert het script: kies zelf welke je houdt.

**Overstappen van oudere versies.** Tot en met 0.26.10 stonden de uploads in `DATA_PATH/app/uploads`. Bij de eerste start na de update verplaatst de container ze zelf naar `DATA_PATH/uploads` (ook de bestanden met een spatie of punt in de naam; een bestand dat daar al
staat wordt nooit overschreven, het oude blijft dan staan, en de lege map `app/` verdwijnt). De database bleef al in `DATA_PATH/postgres`, dus daar verandert niets. Zorg dat `DATA_PATH` in `.env` naar dezelfde map wijst als voorheen.

### Deploy en update
```bash
sh scripts/update.sh        # maakt eerst een dump in DATA_PATH/backups en doet dan pull + up
# of met de hand:
docker compose pull && docker compose up -d
```
`scripts/update.sh` bewaart de database als `DATA_PATH/backups/pre-update-JJJJ-MM-DD-UUMMSS.sql.gz` voordat er iets wordt vervangen (daarna verhuist `scripts/migrate_data.sh` data die in een andere map dan `DATA_PATH` staat); mislukt of is die dump leeg, dan stopt de update. Die dumps staan in dezelfde map als de data die ze beschermen:
kopieer ze nu en dan van de server af. Terugzetten: zie *Back-up en herstel*.
CI publiceert bij elke push naar `beta` `:beta` (en `:beta-<sha>`), zonder release of nieuw versienummer: zet `PRINTPRICING_TAG=beta` in `.env` om de beta te draaien, met een aparte datamap.
CI publiceert bij elke promotie naar `main` (een pull request vanuit `beta`) `:latest`, en `:X.Y.Z` plus een GitHub Release (met notities) wanneer
`VERSION` een nieuwe versie heeft. Een versie-image wordt nooit overschreven. Migraties draaien bij het opstarten
vóór de server verkeer krijgt; de container stopt als een migratie faalt of een toegepaste migratie is gewijzigd.
Hosten op de gedeelde Flux76-server: zie `shared/infrastructure/adding-an-app.md` in App-Guidance.

**Zie je na een update nog de oude app?** Controleer de draaiende versie in de zijbalk (onder de naam, als `vx.x.x (commit)`), onder *Instellingen* (onderaan) of met
`curl http://<host>:<poort>/api/version`, en vergelijk met de laatste release op GitHub. Staat daar een oudere versie:
- `docker compose up -d` pullt een image die al lokaal bestaat **niet** opnieuw; gebruik `docker compose pull && docker compose up -d`.
  Een eerder lokaal gebouwde `…:latest` heeft voorrang tot je pullt.
- Controleer of `PRINTPRICING_TAG` in `.env` niet op een oude versie staat; zet hem desnoods op `latest`. Een oude `APP_IMAGE` in `.env` wordt niet meer gelezen.
- Draait alles goed maar toont je browser oude schermen, ververs dan één keer hard (de service worker haalt bestanden
  vanaf versie 0.3.1 eerst van het netwerk).

### Back-up en herstel
```bash
# back-up
docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup-$(date +%F).sql
# herstel (op een lege database, app gestopt)
docker compose exec -T db psql -U "$POSTGRES_USER" "$POSTGRES_DB" < backup-2026-01-01.sql
```
`pg_dump` bevat **niet** de geüploade STL/3MF-bestanden: die staan in `DATA_PATH/uploads`. Back die map ook
op (`tar czf uploads.tgz "$DATA_PATH/uploads"`), of stop de stack en kopieer heel `DATA_PATH` (dat is dan alles in één
keer). Een berekening zonder terugkomend bestand blijft werken; alleen “Downloaden” geeft dan een melding.
De back-up bevat je passkey-publieke sleutels en gehashte herstelcodes, geen geheimen (ook de OpenAI-sleutel van de optionele AI-afbeeldingen niet). Bewaar `.env` apart (in je wachtwoordmanager): zonder `SESSION_SECRET` log je gewoon opnieuw
in, maar `RP_ID` moet gelijk blijven.

### Runtime-architectuur
Eén app-container (Gunicorn serveert API **en** de statische PWA) + één PostgreSQL-17-container. Data: PostgreSQL in
`DATA_PATH/postgres` en geüploade printbestanden in `DATA_PATH/uploads` (de database bewaart per bestand de metadata
en wat eruit is gelezen). Bestanden die nooit aan een berekening zijn gekoppeld worden na een dag opgeruimd.
De container start als root om de rechten van de gemounte map te zetten en draait daarna als gebruiker `app`.

| Onderdeel | Taak |
|---|---|
| `backend/app/calc.py` | de kostprijsberekening (`Decimal`, afronden per regel) |
| `backend/app/auth.py`, `webauthn.py` | passkeys (ES256, controle door de bibliotheek `py_webauthn`), herstelcodes, sessies, step-up |
| `backend/app/api.py` | printers, tarieven, filament, verpakking, onderdelen, accessoires, berekeningen, voorkeuren |
| `backend/app/files.py`, `printfile.py` | upload/download van STL/3MF en het uitlezen ervan (slicer-gegevens of volume) |
| `backend/app/db.py`, `migrations/` | migratierunner (vooruit-only, checksum-bewaakt) |
| `frontend/` | statische PWA zonder buildstap, plus service worker voor offline schil |

### Limieten buiten de repository
Alles wat een verzoek onderweg naar de app kan weigeren, met de waarde die de app nodig heeft:

| Limiet | Waarde die de app nodig heeft | Beperkt |
|---|---|---|
| Maximale request-body (proxy/CDN) | ≥ `MAX_UPLOAD_MB` + 1 MB (standaard 51 MB); voor het herstellen van een back-up met printbestanden zo groot als die back-up | uploadlimiet van de app; Cloudflare Free stopt bij 100 MB, nginx staat standaard op 1 MB (`client_max_body_size`) |
| Request-timeout (proxy/CDN) | ≥ 120 s | Gunicorn `--timeout 120` in `deploy/entrypoint.sh` (een groot 3MF uitlezen duurt even) |
| `Origin`-header op schrijvende verzoeken doorgeven | verplicht ongewijzigd | origin-check tegen `RP_ORIGINS` |
| `X-Forwarded-For/-Proto/-Host` doorgeven | aantal proxies = `PROXY_HOPS` | rate-limit op de setupcode per client-IP |
| TLS | verplicht (behalve `localhost`) | WebAuthn, installeren, camera en push werken alleen in een secure context |
| Uitgaand https vanaf de app-container | naar de pushdiensten (zie hierboven) | het versturen van push-meldingen; zonder dit falen ze zonder dat de app het merkt, behalve in de testknop |

Er zit geen CDN of proxy in deze repository; wat ervoor staat bepaalt de werkelijke ceilings.

## Wachtwoord en tweestapsverificatie (optioneel)

Standaard **uit**; passkeys blijven de aanbevolen manier van inloggen en werken altijd, ook als je een wachtwoord instelt. Een wachtwoord is de weg
voor plekken waar een passkey niet kan werken (een IP-adres in je eigen netwerk, of zonder https). De eigenaar kan er bij de onboarding mee beginnen; daarna zet je
het aan onder *Instellingen → Beveiliging → Wachtwoord en tweestapsverificatie*, en een uitgenodigde gast kiest het zelf.

- **Een wachtwoord** (minstens 12 tekens) is genoeg om in te loggen. Het vraagt alleen dat je ingelogd bent (het moet ook werken op een toestel zonder passkey).
- **Tweestapsverificatie** is een aparte keuze, onder dezelfde kaart: je koppelt een authenticator-app (TOTP, 6 cijfers) en krijgt 8 back-upcodes (elk één keer bruikbaar).
  Daarna komt er pas een sessie nadat wachtwoord én code kloppen. Aanzetten vraagt alleen een sessie; uitzetten, nieuwe back-upcodes en alles wat je wachtwoord raakt vragen een verse bevestiging.
- **Bevestigen** doe je met een passkey, of met je wachtwoord (plus een code uit de app of een back-upcode als je tweestapsverificatie hebt); dat telt voor de blokkade net als inloggen.
- **Blokkade.** Na 5 mislukte pogingen blokkeert wachtwoord-login 15 minuten (daarna steeds langer); een passkey blijft werken.
- **Niet buitengesloten.** Het wachtwoord uitzetten kan alleen als je een passkey hebt, en je laatste passkey verwijderen alleen als je een wachtwoord hebt.
  Bij een eigenaar die met een wachtwoord begon zijn de herstelcodes de weg terug als het wachtwoord kwijt is; bewaar ze. Nieuwe herstelcodes maak je met je wachtwoord als je geen passkey hebt.

Wachtwoorden zijn met argon2id gehasht; het TOTP-geheim staat versleuteld met een sleutel afgeleid van `SESSION_SECRET`. Wijzig je
`SESSION_SECRET`, dan werkt de tweestapscode niet meer: zet tweestapsverificatie uit met een passkey of een back-upcode en stel hem opnieuw in.

## Gebruikers en rollen

De app is voor één bedrijf, maar er kunnen meer mensen mee werken. Wie de app instelt (de onboarding) is de **eigenaar**: een beheerder die nooit kan worden verwijderd, teruggezet of tot gewone gebruiker gemaakt, zodat de installatie altijd een beheerder heeft. Iedereen die later komt, krijgt een uitnodiging van een beheerder. Er zijn twee rollen; wat een rol mag staat op de server vast (`backend/app/access.py`), het verbergen van een tabblad op het scherm is alleen beleefdheid.

| | Gebruiker | Beheerder |
|---|---|---|
| Berekeningen, bestellingen en facturen maken, klanten, voorraad, printers, tarieven, filamentbibliotheek, printbestanden | ✅ | ✅ |
| Eigen voorkeuren (taal, thema, meldingen, stille uren), eigen passkeys, wachtwoord en herstelcodes | ✅ | ✅ |
| Bedrijfsgegevens, btw en afronding, drempels voor *filament bijna op*, factuursjabloon en logo wijzigen | ❌ | ✅ |
| Gebruikers uitnodigen, nieuwe inloglink maken, beheerder maken, verwijderen | ❌ | ✅ |
| Back-up en herstel, fabrieksinstellingen, updatecontrole en melding *nieuwe versie*, OpenAI-sleutel | ❌ | ✅ |

Wat een gewone gebruiker ziet maar niet wijzigt (bijvoorbeeld de btw bij een nieuwe bestelling of de bedrijfsgegevens op een factuur) komt uit de gedeelde bedrijfsinstellingen. Een gewone gebruiker kan wel facturen maken: die gebruiken de bedrijfsgegevens van het bedrijf. Gemaakte gegevens (berekeningen, bestellingen, klanten) horen bij het bedrijf, niet bij wie ze maakte: ze blijven staan als die persoon wordt verwijderd.

### Iemand uitnodigen

*Instellingen → Gebruikers → Iemand uitnodigen* (alleen beheerders). Vul eventueel een naam in als voorstel en kies *Maak link*. De app toont de link **één keer**, met een knop *Kopieer*; stuur hem via chat, mail of in het echt.

- De gast opent de link, kiest een naam (het voorstel mag worden aangepast) en kiest zelf een **passkey** of een **wachtwoord**. Zo weet de beheerder nooit iemands wachtwoord, en hoeft hij er ook nooit een door te geven. In beide gevallen krijgt de gast 8 herstelcodes; tweestapsverificatie met een authenticator-app zet de gast daarna zelf aan, onder *Wachtwoord en tweestapsverificatie*. Werkt een passkey niet op het adres dat de gast gebruikt, dan staat het wachtwoord al open.
- De link werkt **één keer** en vervalt na **7 dagen**; een openstaande uitnodiging trek je in onder *Openstaande uitnodigingen*. Een onbekende, verlopen of al gebruikte link geeft altijd dezelfde melding. Een naam die in een openstaande uitnodiging staat is gereserveerd. Er kunnen hooguit 50 gebruikers zijn (openstaande uitnodigingen voor nieuwe mensen tellen mee) en 50 openstaande uitnodigingen.
- De link is `https://<adres>/#invite=<token>`. Het token staat achter de `#`, dus het gaat nooit mee naar een server, proxy of `Referer`; de pagina stuurt het in een kop (`X-Invite-Token`) terug, en de server bewaart alleen de SHA-256 ervan. Na gebruik verdwijnt het uit de adresbalk. Het adres in de link is het adres waarop de beheerder op dat moment is ingelogd, als dat in `RP_ORIGINS` staat (anders het eerste adres daar), nooit het adres dat een proxy achter de schermen gebruikt. Is `RP_ORIGINS` leeg, dan is het het adres waarop de beheerder de app opende. Een passkey werkt alleen op een adres uit `RP_ORIGINS` (leeg: het adres waarop hij gemaakt is).
- Een uitnodiging is geen sessie: wie alleen de link heeft, kan niets in de app. En: er verandert niets zolang de gast niet klaar is. Opent iemand de link en loopt weg, dan is er niets aangemaakt of veranderd.

### Inloggen met meer dan één persoon

Met passkeys verandert er niets: de browser vindt de passkey zelf. Is **wachtwoord-login** aan, dan vraagt het inlogscherm zodra er meer dan één persoon is ook om je **naam** (hoofdletters maken niet uit), want elk heeft een eigen wachtwoord, authenticator, back-upcodes en blokkade na 5 mislukte pogingen. Met één persoon blijft de naam weg. Namen zijn uniek, ook zonder hoofdletters.

### Opnieuw inloggen (de inloglink)

Is iemands telefoon met de passkey weg, of is het wachtwoord vergeten, dan maakt een beheerder onder *Gebruikers* **Nieuwe inloglink** voor die persoon. Dezelfde soort link, dezelfde regels (één keer, 7 dagen, alleen de hash bewaard), met twee verschillen: de naam staat vast, en wat de persoon nu heeft om in te loggen (passkeys, herstelcodes, wachtwoord, authenticator, back-upcodes, meldingsaanmeldingen) blijft werken **tot het moment dat de nieuwe is ingesteld**. Dan worden de oude gewist en eindigen alle oude sessies op alle apparaten. Er is hooguit één inloglink per persoon; een nieuwe vervangt de oude. De eigenaar kan geen inloglink krijgen: zijn weg terug zijn de herstelcodes (bewaar ze goed), zodat één klik een installatie nooit van zijn beheerder berooft.

### Beheerder maken

Een beheerder kan een gewone gebruiker **beheerder maken** (*Maak beheerder* in de lijst) en dat ook weer terugdraaien (*Maak gewone gebruiker*). Een beheerder mag daarna alles, behalve de eigenaar aanraken; je kunt je eigen rol niet wijzigen. Beheerder maken geeft iemand alle rechten, dus de app vraagt dan om een **verse bevestiging** door degene die het doet, voor precies die persoon: een passkey, of (als wachtwoord-login aan staat) wachtwoord plus een code. Dezelfde bevestiging geldt voor een inloglink voor een andere beheerder. Gewone gebruiker maken, een gewone gebruiker verwijderen en een inloglink voor een gewone gebruiker vragen er niet om. Een rol geldt direct: een lopende sessie wint of verliest de rechten bij het eerstvolgende verzoek.

### Een gebruiker verwijderen

*Verwijderen* (prullenbak) wist de persoon en alles wat aan haar of hem hangt in één keer: passkeys, herstelcodes, wachtwoord en authenticator, meldingsaanmeldingen, een openstaande inloglink. De sessie eindigt direct. De eigenaar en jezelf kun je niet verwijderen.

### Gedeeld of persoonlijk

Per persoon blijven: taal, thema en accentkleur, de balk onderaan, in- of uitklappen van het menu, het verbergen van kostprijzen, de schakelaar *Zakelijk*, stille uren, en of je een melding over een nieuwe versie wilt. Gedeeld door iedereen (en alleen door een beheerder te wijzigen): `business` (bedrijfsgegevens, factuurnummerformaat, betaal-QR), `vat_pct`, `price_rounding` en `low_stock`. Ze staan in de tabel `shared_preferences`; bij het bijwerken naar deze versie verhuist wat de eigenaar tot nu toe had ingevuld daarheen. Een back-up bevat beide samen onder `preferences`, zoals altijd, en een oudere back-up herstelt dus gewoon.

### Back-up, fabrieksinstellingen en de database

- Een **back-up** bevat geen gebruikers, uitnodigingen of inloggegevens (zie *Back-up in de app*). Een herstel verandert niemands toegang: het zet de gegevens terug (en de bedrijfsinstellingen voor iedereen, plus de eigen voorkeuren van de beheerder die herstelt). Op een lege installatie begin je dus als eigenaar en nodig je de anderen opnieuw uit.
- **Fabrieksinstellingen** wist ook alle andere gebruikers en uitnodigingen (zie *Fabrieksinstellingen*). Het mag elke beheerder, na het getypte woord en een verse bevestiging.
- Database: `users.role` (`admin` of `user`), `users.is_owner` (hooguit één, altijd beheerder), `users.session_epoch`, de tabellen `invitations` en `shared_preferences` (migratie `0024`). Elke tabel met een `user_id` verwijst met `ON DELETE CASCADE` naar `users`; `test_users.py` controleert dat een nieuwe tabel dat ook doet.
- **Nieuwe instellingen in `.env` of `docker-compose.yml`: geen.** Een bestaande installatie werkt zonder ingreep door; de bestaande gebruiker wordt eigenaar en beheerder en bestaande sessies blijven geldig.

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
| **Algemeen** | kostprijs en marge blurren, de schakelaar **Zakelijk**, app installeren |
| **Weergave** | taal, thema, accentkleur |
| **Beveiliging** | passkeys en herstelcodes, wachtwoord en tweestapsverificatie |
| **Zakelijk** | btw en afronding, bedrijfsgegevens, factuursjabloon; alleen zichtbaar voor beheerders, en als de schakelaar *Zakelijk* onder *Algemeen* aan staat (de voorkeur `business_mode`, per account) |
| **Filamenten** | de filamentbibliotheek: specificaties van filamenten, een Bambu Lab-factuur inlezen, JSON-export en -import en synchroniseren met GitHub; zie *Filamentbibliotheek* |
| **Notificaties** | meldingen (dit apparaat, testmelding, verbindingscontrole, apparatenlijst) en stille uren; *nieuwe versie* en de drempels voor *filament bijna op* alleen voor beheerders |
| **Gebruikers** | alleen beheerders: wie mag inloggen, uitnodigen, nieuwe inloglink, beheerder maken, verwijderen; zie *Gebruikers en rollen* |
| **AI-afbeeldingen** | alleen beheerders, en alleen als `AI_IMAGES_ENABLED=TRUE`: de OpenAI-sleutel en het logboek |
| **Systeem** | alleen beheerders: back-up en herstel (zie *Back-up in de app*), de updatecontrole (zie *Meldingen en updates*) en onder *Opruimen* terug naar fabrieksinstellingen (zie *Fabrieksinstellingen*) |

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

Vijf manieren om de bibliotheek te vullen of te delen zonder te typen:

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
- **Rollen toevoegen aan bibliotheek.** De knop zet de filamenten van alle rollen in je filamentlijst (gearchiveerde rollen niet) in de bibliotheek, zodat je ze met anderen kunt delen
  (exporteren of de gedeelde bibliotheek). Je ziet eerst hoeveel er nieuw komen en hoeveel bestaande vermeldingen iets missen. Per rol geldt dezelfde regel als bij *Ook aan de bibliotheek toevoegen*: staat het
  filament er nog niet in, dan komt het erin met wat de rol over het filament zegt (nooit de prijs of wat er over is); staat het er wel in, dan krijgt die vermelding alleen wat ze nog mist. Past een rol bij meer dan één vermelding
  (bijvulling én met spoel), dan wordt ze overgeslagen en genoemd. **De rollen zelf worden alleen gelezen, nooit gewijzigd.**
- **Bijdragen aan de centrale bibliotheek.** De knop *Bijdragen aan de centrale bibliotheek* (naast *Synchroniseren*) haalt de gedeelde bibliotheek op, zoekt de filamenten van
  jouw bibliotheek die daarin nog ontbreken (dezelfde regel als overal: SKU, barcode, filament-ID of naam met gewicht en diameter) en laat je kiezen wat je meestuurt. Daarna opent
  GitHub met een **issue** die al is ingevuld; **jij** verstuurt hem (een GitHub-account is nodig), de app stuurt zelf niets en heeft geen token. Meegestuurd worden de specificaties en de
  richtprijs; **notities en alles over je rollen blijven eruit**. Past de bijdrage niet in het adres (vanaf ongeveer 20 filamenten), dan toont de app de JSON in een tekstvak met een knop *Kopiëren* en opent *Open GitHub* het formulier met een leeg veld: plak de JSON daar zelf in.
  Een workflow (`library-contribution`) controleert de issue met dezelfde regels als de app en opent een pull request naar `beta` die alleen filamenten **toevoegt** (een bestaand filament wordt
  nooit gewijzigd, een bijdrage zonder nieuwe filamenten wordt gesloten) en die een beheerder beoordeelt. Wat is goedgekeurd, krijgt iedereen via *Synchroniseren* zodra `beta` is gepromoveerd naar `main`.
  De knop staat er alleen zolang `FILAMENT_LIBRARY_URL` de standaardwaarde heeft, omdat het formulier bij deze repository hoort. GitHub leest issueformulieren en workflows die op `issues` starten alleen van de **standaardbranch** van de repository: die moet `beta` zijn (Settings → Branches), anders werken formulier en workflow pas nadat `beta` naar `main` is gepromoveerd.
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

## Spoolman (optioneel)

Gebruik je [Spoolman](https://github.com/Donkie/Spoolman) voor je spoelen, dan kan dat de **bron van de rollen en van wat er nog op zit** zijn, zodat je dat op één plek bijhoudt. Je vult het adres in als beheerder
onder *Instellingen → Filamenten* (veld *Adres van Spoolman*, met *Opslaan* en *Verbinding testen*), of je zet het in `.env` als `SPOOLMAN_URL=http://spoolman:8000`. Het moet het adres zijn waarop **de server van de app** Spoolman bereikt
(dat kan een ander zijn dan in je browser, bijvoorbeeld `http://spoolman:8000` in hetzelfde Docker-netwerk of `http://192.168.1.20:7912` met de poort die je naar buiten zette); `http` mag, zonder inlog of vraagteken, en een pad mag
als Spoolman erachter staat. Een leeg adres betekent: geen Spoolman, en alles blijft zoals het was. Staat het in `.env`, dan **gaat dat voor**: de app toont het dan alleen-lezen. Het adres staat **niet in een back-up** (het hoort bij
één netwerk) en alleen een beheerder kan het zien of wijzigen; de server doet met dit adres uitsluitend de vaste aanroepen onder `/api/v1/` van Spoolman en geeft van de test alleen het oordeel door. Spoolman heeft zelf geen inlog: zet het niet open op internet.

- **Synchroniseren** (*Instellingen → Filamenten* en bovenaan *Filament*, alleen voor beheerders; iedereen ziet wanneer het voor het laatst gebeurde). De app leest alle spoelen uit Spoolman en maakt er elk een rol van,
  gekoppeld aan het spoolnummer van Spoolman: de volgende keer wordt die rol bijgewerkt, niet nog een keer toegevoegd. Merk, materiaal, kleur (naam en kleurcode), gewicht, prijs, diameter, temperaturen,
  opmerking en wat er nog op zit komen uit Spoolman; de *artikelnummer* van het filament wordt de barcode (rollen met dezelfde barcode tellen in de voorraad samen). Een spoel met een eigen prijs telt voor die prijs, anders geldt de prijs van het filament.
  **Prijzen worden overgenomen zoals ze in Spoolman staan en gelden hier als prijs excl. btw**, net als overal in de app.
- **Een rol uit Spoolman is van Spoolman.** Je past hem daar aan; hier kan je hem niet bewerken, archiveren of verwijderen (de volgende synchronisatie zou het terugzetten). Alleen de melding *bijna op* is van de app
  en blijft staan. Een spoel die in Spoolman is gearchiveerd, wordt hier gearchiveerd; een spoel die uit Spoolman is verdwenen wordt hier **gearchiveerd, nooit verwijderd**, omdat opgeslagen berekeningen ernaar kunnen verwijzen.
  Rollen die je met de hand invoerde, blijven wat ze waren en worden niet gekoppeld of aangeraakt.
- **Verbruik gaat terug naar Spoolman.** Boek je het filament van een berekening, dan meldt de app de grammen aan Spoolman (`use`), zodat het niet twee keer wordt afgeboekt. Is Spoolman op dat moment niet bereikbaar,
  dan lukt het boeken gewoon; de grammen staan in de wachtrij en gaan mee bij de volgende synchronisatie, en tot dan telt de app ze af van het gewicht dat Spoolman meldt. Een melding die Spoolman voorgoed weigert (de spoel bestaat daar niet meer) wordt laten vallen.
- **Bibliotheek naar Spoolman.** De knop zet de filamenten van de [filamentbibliotheek](#filamentbibliotheek) in Spoolman, zodat je daar alleen nog een spoel hoeft toe te voegen (en die komt met de volgende synchronisatie hier). Eerst zie je
  hoeveel er worden aangemaakt. Merken die Spoolman nog niet kent worden aangemaakt; een filament dat Spoolman al heeft (zelfde merk en artikelnummer, of zelfde merk, naam en materiaal) blijft **ongemoeid**, en er wordt in Spoolman
  **nooit iets verwijderd of overschreven**. De kleur (met het type ervoor) wordt de naam, barcode (anders SKU) het artikelnummer en de richtprijs de prijs. Spoolman eist een dichtheid: de app neemt een gangbare waarde per materiaal
  (PLA 1,24, PETG 1,27, ABS 1,04, ASA 1,07, TPU 1,21, PC 1,20, PA 1,14), die alleen gebruikt wordt om gram in meters om te rekenen. Per keer worden hoogstens 300 filamenten aangemaakt; de melding zegt of je het nog een keer moet doen.
  Let op: dit zijn **filamenten** (in Spoolman onder *Filaments*), geen **spoelen**; de pagina *Spools* blijft leeg tot je daar een spoel toevoegt of *Rollen naar Spoolman* gebruikt.
- **Rollen naar Spoolman.** De knop maakt in Spoolman een **spoel** van elke rol die je hier met de hand invoerde (niet gearchiveerd, met naam of barcode): het filament wordt gezocht of aangemaakt zoals hierboven, de spoel krijgt het gewicht dat er nog op zit
  en de prijs, en de rol wordt meteen aan die spoel gekoppeld, zodat de volgende synchronisatie hem bijwerkt in plaats van er een tweede van te maken. Elke rol wordt apart vastgelegd: gaat het halverwege mis, dan blijven de al gekoppelde
  rollen gekoppeld en maakt een tweede run ze niet opnieuw aan. Daarna komen merk, type en kleur van de rol uit Spoolman (het type komt daar vóór de kleur in de naam te staan). Hoogstens 300 spoelen per keer.
- **De bibliotheek blijft.** Spoolman vervangt de bibliotheek niet: zonder `SPOOLMAN_URL` werkt alles als voorheen, en de bibliotheek (GitHub-sync, factuurimport, bijdragen) kan ernaast blijven bestaan.
- **Back-up.** Een back-up bevat het spoolnummer van elke rol uit Spoolman, zodat een teruggezette rol gekoppeld blijft. De wachtrij met nog te melden verbruik zit er niet in (werk in uitvoering).

## Back-up in de app

*Instellingen → Systeem → Back-up en herstel* downloadt al je gegevens als één JSON-bestand (`printpricing-backup-JJJJ-MM-DD.json`; met *Printbestanden (STL/3MF) meenemen* is het een ZIP-bestand, zie hieronder):
je instellingen (thema, taal, btw, afronding, stille uren, bedrijfsgegevens…), printers, energietarieven, verpakkingen, onderdelen, accessoires, de filamentbibliotheek, filamentrollen,
berekeningen (met hun nummers), klanten, bestellingen met hun factuurnummers en bewaarde factuur-PDF’s, het factuursjabloon en het logo, op wens ook de geüploade printbestanden (groter). **Niet** in het bestand: gebruikers en uitnodigingen, passkeys, herstelcodes, het wachtwoord
met zijn authenticatorgeheim en meldingsaanmeldingen. Het zijn sleutels of horen bij één apparaat; een bestand dat je kunt
mailen of bewaren mag de app niet kunnen openen. Na herstellen op een lege installatie log je dus gewoon in met je passkey.

*Herstellen uit back-up…* kiest zo'n bestand, controleert het eerst helemaal (met dezelfde regels als handmatig invoeren; de
berekeningen worden opnieuw uitgerekend, een aangepast totaal in het bestand telt dus niet, en printbestanden worden opnieuw
gelezen en tegen hun controlesom gehouden) en laat zien wat er terugkomt. Pas na jouw bevestiging **vervangt** het alles wat er
nu staat, in één keer: lukt iets niet, dan verandert er niets. Een bestand uit een nieuwere versie van de app wordt geweigerd; een back-up van een oudere versie (zonder bestellingen) werkt
nog steeds en laat de bestellingen dan leeg. Het volgende bestel- en factuurnummer gaat door na de hoogste uit de back-up.

**Met printbestanden is het een ZIP-bestand** (`printpricing-backup-JJJJ-MM-DD.zip`): elk STL- of 3MF-bestand staat er los in, onder `files/` met zijn eigen naam (heten twee modellen hetzelfde, dan krijgt de tweede ` (2)`), en `backup.json`
bevat de rest, met per model een verwijzing (`archive_path`) en zijn controlesom. Je kunt het ZIP-bestand dus gewoon openen om een model terug te halen. Een back-up zonder printbestanden blijft één JSON-bestand, en een JSON-back-up
van een eerdere versie (met de modellen er inline in) kan nog steeds worden teruggezet.

**Je ziet wat er gebeurt.** Bij het maken van een back-up toont de kaart een voortgangsbalk: eerst dat de server hem samenstelt, daarna hoeveel er al binnen is. Bij herstellen zie je het uploaden (met megabytes), het controleren van het bestand
en daarna het herstellen zelf, met bij printbestanden *printbestand 4 van 10*. Na de controle vraagt de app om bevestiging; **daarna draait het herstel op de server als achtergrondtaak** (tabel `backup_jobs`, geen onderdeel van een back-up):
je kunt de pagina verlaten of de browser sluiten en het gaat door. Open *Instellingen → Systeem* weer, dan zie je de stand of de uitkomst; is het klaar, dan laadt de app opnieuw met de teruggezette instellingen. Mislukt het, dan staat er waarom
en is er niets veranderd (het vervangen is één transactie). Er loopt hooguit één herstel tegelijk. Een herstel dat 15 minuten niet vooruitkwam (de server was herstart) wordt als onderbroken gemeld; ook dan is er niets veranderd.
Het geüploade bestand staat tot het herstel klaar is als `.restore-<token>` onder `DATA_PATH/uploads` en wordt daarna, of na een uur, verwijderd.

De grootte: een herstel mag tot 2 GB zijn, en elk model daarin hoogstens `MAX_UPLOAD_MB` (standaard 50 MB), net als een gewone upload. Een proxy of CDN vóór de app moet zo'n body doorlaten
(zie *Limieten buiten de repository*: Cloudflare Free stopt bij 100 MB, nginx staat standaard op 1 MB); past je back-up daar niet doorheen, gebruik dan de database-dump en de uploads-map hierboven.
Een volledige kopie van de database (`pg_dump`) en de map met uploads blijft de manier voor een back-up van de hele server, zie
*Back-up en herstel* (onder Beheer) hierboven.

## Fabrieksinstellingen

*Instellingen → Systeem → Opruimen → Terug naar fabrieksinstellingen…* zet de app terug zoals direct na de installatie. Het verwijdert **alles**:
berekeningen, bestellingen met factuurnummers, klanten, printers, tarieven, rollen, de filamentbibliotheek, instellingen, het factuursjabloon
en logo, de geüploade bestanden, de OpenAI-sleutel, meldingsaanmeldingen en ook alle gebruikers en openstaande uitnodigingen, met hun passkeys, herstelcodes en wachtwoorden. Alleen de database zelf en
je `.env` blijven staan. Het kan niet ongedaan worden gemaakt: download eerst een back-up (*Back-up en herstel*) als je iets wilt bewaren.

De knop opent **eerst de waarschuwing** (wat verdwijnt, ook je eigen passkeys, en wat blijft), dan het veld waarin je het woord **`RESET`** typt; zonder dat woord doet de server niets, ook niet met een geldige bevestiging. Wat **blijft**: je `.env` (met `SETUP_CODE`, `SESSION_SECRET`, de VAPID-sleutels), de image, `DATA_PATH/backups` (de dumps van `scripts/update.sh`) en je accounts bij andere diensten (zoals OpenAI; alleen de sleutel in de app verdwijnt). Daarna volgt een laatste vraag (“alle gegevens worden nu definitief gewist”) en pas dan de bevestiging hieronder. Er is **geen herstart** nodig: alle toestand staat in de database en de uploadmap, en de server begint bij het volgende verzoek gewoon opnieuw met een lege database. De reset laat één regel achter in het logboek van de container (hoeveel tabellen zijn geleegd en hoeveel bestanden zijn verwijderd, met hun namen; nooit inhoud). Weet je het niet zeker: kopieer eerst de map `DATA_PATH` of maak een back-up; de reset biedt er zelf geen aan.

De app vraagt om bevestiging met de verificatiemethode die je gebruikt: een verse passkey-bevestiging, of, als wachtwoord-login aan staat en de passkey op dit
apparaat niet werkt, je wachtwoord plus een code (authenticator of back-upcode); dat telt voor de blokkade net als inloggen. Daarna sta je weer op het
welkomstscherm: je doorloopt de eerste start opnieuw, met de `SETUP_CODE` uit `.env`, en maakt een nieuwe passkey en nieuwe herstelcodes. Bestel-, factuur- en
berekeningsnummers beginnen weer bij 1; wil je ze behouden, herstel dan een back-up na de eerste start.
