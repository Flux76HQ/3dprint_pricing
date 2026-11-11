<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/icon.png">
  <img src="docs/assets/icon.png" alt="Logo van 3D Print Pricing" width="128">
</picture>

# 3D Print Pricing

**De zelf-gehoste kostprijscalculator voor wie 3D-prints verkoopt.**

Reken uit wat een print echt kost, houd je filamentvoorraad bij en maak van bestellingen facturen: op je telefoon of aan je bureau, op een eigen server.

🇳🇱 **Nederlands** · 🇬🇧 [English](README.md)

[![Platform](https://img.shields.io/badge/platform-iOS%20%7C%20Android%20%7C%20Web-blue)](#snel-starten)
[![Self-hosted](https://img.shields.io/badge/self--hosted-Docker-2496ED?logo=docker&logoColor=white)](#installatie-zelf-hosten)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-app-41BDF5?logo=homeassistant&logoColor=white)](#installatie-als-home-assistant-app)
[![Talen](https://img.shields.io/badge/languages-NL%20%7C%20EN-lightgrey)](#wat-kan-het)
[![Status](https://img.shields.io/badge/status-in%20ontwikkeling-orange)](#)

[![Laatste commit](https://img.shields.io/github/last-commit/Flux76HQ/3dprint_pricing/beta)](https://github.com/Flux76HQ/3dprint_pricing/commits/beta)
[![Commitactiviteit](https://img.shields.io/github/commit-activity/m/Flux76HQ/3dprint_pricing)](https://github.com/Flux76HQ/3dprint_pricing/graphs/commit-activity)
[![Forks](https://img.shields.io/github/forks/Flux76HQ/3dprint_pricing?style=social)](https://github.com/Flux76HQ/3dprint_pricing/forks)
[![Sterren](https://img.shields.io/github/stars/Flux76HQ/3dprint_pricing?style=social)](https://github.com/Flux76HQ/3dprint_pricing/stargazers)
[![Issues](https://img.shields.io/github/issues/Flux76HQ/3dprint_pricing)](https://github.com/Flux76HQ/3dprint_pricing/issues)
[![Bijdragers](https://img.shields.io/github/contributors/Flux76HQ/3dprint_pricing)](https://github.com/Flux76HQ/3dprint_pricing/graphs/contributors)

[![Release](https://img.shields.io/github/v/release/Flux76HQ/3dprint_pricing)](https://github.com/Flux76HQ/3dprint_pricing/releases/latest)
[![Buy me a coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-flux76-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/flux76)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-flux76-FF5E5B?logo=kofi&logoColor=white)](https://ko-fi.com/flux76)

[Handleiding](docs/handleiding.md) · [Releasenotes](https://github.com/Flux76HQ/3dprint_pricing/releases) · [Een fout melden](https://github.com/Flux76HQ/3dprint_pricing/issues/new/choose)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/desktop-calculation-dark.png">
  <img src="docs/assets/desktop-calculation.png" alt="3D Print Pricing op de desktop: een berekening met het overzicht van de kostprijs" width="900">
</picture>

</div>

---

## Inhoud

- [Waarom 3D Print Pricing?](#waarom-3d-print-pricing)
- [Wat kan het?](#wat-kan-het)
- [Zo ziet het eruit](#zo-ziet-het-eruit)
- [Snel starten](#snel-starten)
- [Configuratie](#configuratie)
- [Beheer](#beheer)
- [Data en back-ups](#data-en-back-ups)
- [Architectuur](#architectuur)
- [Stabiel en beta](#stabiel-en-beta)
- [Meewerken](#meewerken)
- [Privacy en beveiliging](#privacy-en-beveiliging)
- [Steun 3D Print Pricing](#steun-3d-print-pricing)
- [Licentie](#licentie)

## Waarom 3D Print Pricing?

Wie 3D-prints verkoopt moet weten wat elke print kost: filament per gram, machinetijd, stroom, verpakking en een eerlijk deel van de aanschaf van de printer. Met een spreadsheet kom je een eind, tot de prijzen veranderen, de voorraad ongemerkt opraakt of een klant om een factuur vraagt. 3D Print Pricing houdt prijzen, voorraad en bestellingen bij elkaar op een plek die je zelf host, en werkt op je telefoon net zo goed als aan je bureau.

## Wat kan het?

- **Kostprijs in een paar seconden**: filament, onderdelen, accessoires (kabels, laders), printerafschrijving en energie tellen op tot een kostprijs, met optioneel een marge voor een adviesverkoopprijs. Elke regel wordt eerst op hele centen afgerond, zodat de regels op het scherm optellen tot het totaal, en een opgeslagen berekening bewaart de prijzen van het moment van opslaan, dus een latere prijswijziging van een rol herschrijft je geschiedenis niet.
- **Rechtstreeks uit de slicer**: koppel een `.3mf`- of `.stl`-bestand. Een gesliced 3MF (Bambu Studio / Orca) geeft de echte gram per filament en de printtijd, die automatisch in de berekening komen; een STL geeft een schatting van het gewicht.
- **Filamentbibliotheek**: de gegevens van de filamenten die je koopt (merk, type, kleur, filament-ID van de leverancier, gewicht, diameter, temperaturen, richtprijs), zodat een nieuwe rol zichzelf invult. Vul haar zonder te typen (importeer een Bambu Lab-factuur of een JSON-bestand, voeg de rollen uit je filamentlijst toe, synchroniseer de gedeelde bibliotheek met GitHub of draag de jouwe eraan bij) en exporteer haar als JSON; importeren en synchroniseren voegen alleen toe en werken bij, verwijderen nooit, leggen nooit twee keer hetzelfde filament vast en laten je voorraad met rust.
- **Filamentvoorraad met barcodescanner**: je rollen met prijs, resterend gewicht, kleur en temperaturen, gegroepeerd per soort. Maak een rol aan met de hand, door de barcode te scannen, uit de bibliotheek of, bij Bambu Lab, uit de producten en kleuren van de webshop, dupliceer een rol om er een of meer van hetzelfde bij te zetten, of voeg een hele levering in één keer toe door de rollen na elkaar te scannen; zoek op naam, barcode of materiaal terwijl je typt; krijg een melding als een soort bijna op is en boek het verbruik van een berekening met één klik van de voorraad af.
- **Zakelijk bruikbaar**: btw over de verkoopprijs, een marge en een afronding van de prijs per bestelling (op 5/10/50 cent, hele euro's of eindigend op ,95/,99, met je marge als minimum), en een knop om de kosten te blurren als een klant meekijkt.
- **Elk overzicht werkt hetzelfde**: 3D-modellen, bestellingen, klanten, filament, verpakking, onderdelen en printers toon je als tegels of als lijst; je zoekt terwijl je typt, filtert, sorteert op een kolom en groepeert rollen per soort. Bij een 3D-model bewaar je meerdere links: de pagina van het model en de plekken waar het te koop staat (Marktplaats, Bol.com, je webshop).
- **Klanten, bestellingen en facturen**: klanten met klantnummer, bestellingen met meerdere prints, een status van *nieuw* tot *afgehandeld* en een factuur als PDF met je logo, een uniek factuurnummer en een SEPA-betaal-QR. Wil je je eigen briefpapier, dan kan dat als Word- of PDF-sjabloon.
- **Inloggen met passkeys**: geen wachtwoord dat kan lekken. Of een wachtwoord waar een passkey niet kan werken (een IP-adres in je eigen netwerk), optioneel met tweestapsverificatie, en herstelcodes voor noodgevallen.
- **Met meer dan één persoon**: een beheerder nodigt mensen uit met een link voor eenmalig gebruik en iedereen kiest zelf een passkey of wachtwoord, zodat niemand dat van een ander kent. Gewone gebruikers doen het dagelijkse werk; een beheerder beheert ook de gebruikers, de bedrijfsgegevens, back-ups en updates en kan een gewone gebruiker tot beheerder maken.
- **Een echte app op elk apparaat**: te installeren op het beginscherm van iPhone en Android en op de desktop, werkt met de camera en met meldingen, en spreekt Nederlands en Engels.
- **Jij houdt de regie**: alles draait in je eigen container, je gegevens staan in één map op je eigen server, en je maakt er vanuit de app een back-up van en zet die ook weer terug; de app maakt er bovendien elke 12 uur zelf een.

De volledige beschrijving van elke functie staat in de [handleiding](docs/handleiding.md).

## Zo ziet het eruit

### Desktop

| 3D Modellen | Filamentvoorraad | Bestellingen |
|:---:|:---:|:---:|
| <img src="docs/assets/desktop-calculations.png" width="290" alt="Overzicht van berekeningen"> | <img src="docs/assets/desktop-filament.png" width="290" alt="Filamentvoorraad per soort"> | <img src="docs/assets/desktop-orders.png" width="290" alt="Bestellingen met hun status"> |

### iPhone: de iOS-look

De zwevende navigatiebalk met glaseffect. Op het beginscherm geïnstalleerd draait de app schermvullend onder de statusbalk.

| 3D Modellen | Kostprijs | Bestellingen | Filament |
|:---:|:---:|:---:|:---:|
| <img src="docs/assets/ios-calculations.png" width="200" alt="iOS: berekeningen"> | <img src="docs/assets/ios-calculation.png" width="200" alt="iOS: kostprijs van een berekening"> | <img src="docs/assets/ios-orders.png" width="200" alt="iOS: bestellingen"> | <img src="docs/assets/ios-filament.png" width="200" alt="iOS: filamentvoorraad"> |

### Android: de Android-look

De navigatiebalk over de volle breedte met een pil achter het actieve icoon.

| 3D Modellen | Kostprijs | Bestellingen | Filament |
|:---:|:---:|:---:|:---:|
| <img src="docs/assets/android-calculations.png" width="200" alt="Android: berekeningen"> | <img src="docs/assets/android-calculation.png" width="200" alt="Android: kostprijs van een berekening"> | <img src="docs/assets/android-orders.png" width="200" alt="Android: bestellingen"> | <img src="docs/assets/android-filament.png" width="200" alt="Android: filamentvoorraad"> |

### Instellingen en je eigen kleur

*Instellingen* is gegroepeerd in *Persoonlijk*, *Gegevens* en *Beheer*, elk onderdeel met een icoon (wat je ziet hangt af van je rol). Op een telefoon vormen de onderdelen een rij die je kunt vegen. Onder *Weergave* kies je de taal, licht of donker en je **accentkleur**: elf voorinstellingen, waaronder bordeaux en grafiet, of een kleur naar keuze. Het hele scherm kleurt mee, niet alleen de knoppen. Onder *Filamenten* klappen de blokken Spoolman en *Importeren en delen* in.

| Weergave: licht, met het standaardpaars | Weergave: donker, met teal |
|:---:|:---:|
| <img src="docs/assets/desktop-settings.png" width="440" alt="Desktop: Instellingen, Weergave, licht met de paarse accentkleur"> | <img src="docs/assets/desktop-settings-dark.png" width="440" alt="Desktop: Instellingen, Weergave, donker met de teal accentkleur"> |

| iPhone: instellingen | Android: instellingen |
|:---:|:---:|
| <img src="docs/assets/ios-settings.png" width="200" alt="iOS: Instellingen met het veegbare menu"> | <img src="docs/assets/android-settings.png" width="200" alt="Android: Instellingen met het veegbare menu"> |

### Filament: bibliotheek, import en nieuwe rollen

*Instellingen → Filamenten* bevat de filamentbibliotheek: voeg een filament toe, importeer een Bambu Lab-factuur, voeg de rollen uit je filamentlijst toe, importeer of exporteer de bibliotheek als JSON, synchroniseer haar met GitHub, of draag je filamenten bij aan de centrale bibliotheek met een voorgevulde GitHub-issue. Onder *Filament → Nieuwe rol* maak je een rol aan, met de hand, door de barcode te scannen of door een filament uit de bibliotheek te kiezen. *Filament → Scannen* voegt een levering toe: scan elke rol (camera of barcodescanner) en de rollen met een bekende barcode worden in één keer toegevoegd, allemaal vol.

| Bibliotheek: import, export en synchronisatie | Nieuwe rol |
|:---:|:---:|
| <img src="docs/assets/desktop-library.png" width="440" alt="Desktop: de filamentbibliotheek met factuurimport, synchroniseren, JSON-export en -import"> | <img src="docs/assets/desktop-new-roll.png" width="440" alt="Desktop: een nieuwe rol aanmaken, met de keuzelijst van de bibliotheek bovenaan"> |

| iPhone: bibliotheek | iPhone: nieuwe rol | Android: bibliotheek | Android: nieuwe rol |
|:---:|:---:|:---:|:---:|
| <img src="docs/assets/ios-library.png" width="200" alt="iOS: de filamentbibliotheek"> | <img src="docs/assets/ios-new-roll.png" width="200" alt="iOS: een nieuwe rol aanmaken"> | <img src="docs/assets/android-library.png" width="200" alt="Android: de filamentbibliotheek"> | <img src="docs/assets/android-new-roll.png" width="200" alt="Android: een nieuwe rol aanmaken"> |

Onder *Instellingen → Weergave → Navigatiebalk* kies je iOS-achtig of Android-achtig, of laat je de instelling op *Automatisch*: de app herkent het toestel en kiest Android-achtig op Android en iOS-achtig op andere apparaten. Je keuze wordt bij je account bewaard en geldt op al je apparaten. Licht, donker en systeemthema en een eigen accentkleur zitten erbij.

<sub>De schermafbeeldingen tonen demogegevens.</sub>

## Snel starten

- 🌐 **Web:** open het adres van je eigen installatie. Passkeys vragen https en een domeinnaam.
- 📱 **iPhone / iPad** en 🤖 **Android:** zie [Installeren als app](#installeren-als-app).
- 🐳 **Zelf hosten:** zie [Installatie](#installatie-zelf-hosten), of [als Home Assistant-app](#installatie-als-home-assistant-app).

### Installeren als app

- **Android (Chrome, Edge, Samsung Internet) en desktop:** open het https-adres en kies *Installeer de app* in de melding, of onder *Instellingen → Algemeen → App installeren*. Lang drukken op het icoon geeft snelkoppelingen (nieuwe berekening, filament).
- **iPhone / iPad:** open het https-adres in **Safari → Deel → Zet op beginscherm**. De app start dan schermvullend met een eigen icoon en opstartscherm, zonder pinch-zoom of zijwaarts vegen, als een native app.

### Installatie (zelf hosten)

```bash
git clone https://github.com/Flux76HQ/3dprint_pricing.git
cd 3dprint_pricing
python scripts/init_env.py --port 6090 --domain print.voorbeeld.nl   # maakt .env met verse geheimen
docker compose up -d
```

`init_env.py` is de makkelijkste weg; `.env.example` kopiëren naar `.env` en aanpassen werkt net zo goed. Een server heeft alleen `docker-compose.yml` en `.env` nodig: de image wordt van `ghcr.io/flux76hq/3dprint_pricing` gepulld. Zonder `--domain` blijven `RP_ID` en `RP_ORIGINS` leeg en volgt de app het adres waarop je hem opent (ook een IP-adres), genoeg om het uit te proberen.

Open daarna het adres en doorloop de onboarding:

1. Vul de **setupcode** en je naam in. De setupcode is de waarde achter `SETUP_CODE=` in het `.env`-bestand op je server (`init_env.py` toonde hem ook; `grep SETUP_CODE .env` toont hem opnieuw). Typ of plak hem in het veld *Setupcode* van het eerste scherm; je hebt hem alleen voor deze eerste keer nodig, daarna log je in met je passkey of wachtwoord. Het onboarding-scherm legt dit ook uit.
2. Kies hoe je inlogt: maak een **passkey** aan (vingerafdruk, gezicht of apparaatcode), of kies **een wachtwoord** (minstens 12 tekens). Werkt een passkey niet op het adres dat je gebruikt (een IP-adres, zonder https), dan zegt het scherm dat en staat het wachtwoord al open.
3. **Bewaar de 8 herstelcodes.** Ze worden één keer getoond en werken elk één keer.

Een wachtwoord werkt op elk adres, ook in je eigen netwerk. Zet voor passkeys, installeren, de camera en meldingen een reverse proxy met TLS voor de app en stel `RP_ID` en `RP_ORIGINS` in op dat domein: ze werken alleen via https (behalve op `localhost`).

### Installatie als Home Assistant-app

Voeg op Home Assistant OS of Supervised `https://github.com/Flux76HQ/3dprint_pricing` toe onder **Instellingen > Apps > App installeren > Repositories** en installeer *3D Print Pricing*: de app bewaart zijn data (één SQLite-database en de uploads) in de map van de app, die Home Assistant meeneemt in zijn back-ups. Passkeys vragen nog steeds een domein met https voor de poort van de app, dus vul daarvoor `rp_id` in op het tabblad Configuratie; met een wachtwoord werkt de app ook op `http://<adres van Home Assistant>:6080`. De stappen staan op het tabblad Documentatie van de app ([`homeassistant/DOCS.md`](homeassistant/DOCS.md)). Draait op amd64 en aarch64 (Raspberry Pi 4/5, ARM-minipc's).

## Configuratie

In `.env`; [`.env.example`](.env.example) beschrijft elke waarde. Commit `.env` nooit: daar staan de geheimen in.

| Variabele | Verplicht | Standaard | Omschrijving |
|---|:---:|---|---|
| `DATA_PATH` | ✅ | - | Map op de host voor alle data: de database (`db/`, één SQLite-bestand) en de geüploade bestanden (`uploads/`). Gewone mappen, geen Docker-volumes. Moet een **absolute** map van de Docker-host zijn, op een lokale schijf (bijv. `/srv/printpricing`, op Unraid de pool zelf, `/mnt/<pool>/appdata/printpricing`, niet `/mnt/user/...` tenzij appdata een exclusieve share is: SQLite hoort niet op een netwerkshare of FUSE-mount), nooit `./data`; data die ergens anders terecht is gekomen verplaatst `scripts/migrate_data.sh` |
| `PRINTPRICING_TAG` | ❌ | `latest` | Welke build draait: `latest` (stabiel), `beta` (de ontwikkelversie) of een versienummer zoals `0.26.15`. `docker-compose.yml` pullt `ghcr.io/flux76hq/3dprint_pricing:<tag>` en geeft dezelfde waarde aan de app, die op `beta` een **beta**-label naast zijn naam toont. Vervangt `APP_IMAGE` |
| `WEB_PORT` | ✅ | - | Poort van de app; compose publiceert en de app luistert op deze waarde |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | ✅ | - | Alleen voor de PostgreSQL van de releases vóór SQLite, die de app één keer leest om je data over te zetten als hij zonder SQLite-bestand start (zie de [handleiding](docs/handleiding.md), *Overstap naar SQLite*). Laat ze zoals ze zijn; de volgende release laat ze vallen. Alleen letters en cijfers in het wachtwoord |
| `RP_ID` | ❌ | leeg | Domein waarop de app draait, zonder schema of poort. Passkeys zijn eraan gebonden, dus zet het vast zodra je ze gebruikt. Leeg: het adres waarop de app wordt geopend |
| `RP_ORIGINS` | ❌ | leeg | Volledige origin(s), komma-gescheiden, bijvoorbeeld `https://print.voorbeeld.nl`. Gezet: schrijvende verzoeken van een andere origin worden geweigerd, en uitnodigingslinks gebruiken het adres waarop de beheerder is ingelogd als dat hier staat, anders het eerste. Leeg: het adres waarop de app wordt geopend |
| `SETUP_CODE` | ✅ | - | Eenmalige code voor de onboarding, zodat niet de eerste bezoeker de app overneemt |
| `SESSION_SECRET` | ✅ | - | Ondertekent sessiecookies, minimaal 32 tekens |
| `RP_NAME` | ❌ | `3D Print Pricing` | Naam die in de passkey-prompt staat |
| `SESSION_HOURS` | ❌ | `24` | Levensduur van een sessie |
| `MAX_UPLOAD_MB` | ❌ | `50` | Grootste STL/3MF-upload in MB |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | ❌ | leeg | Sleutelpaar voor push-meldingen (`python scripts/generate_vapid.py`); leeg betekent meldingen uit |
| `VAPID_SUBJECT` | ❌ | `mailto:admin@<RP_ID>` (`mailto:admin@localhost` zonder `RP_ID`) | Contactadres voor de pushdiensten |
| `AI_IMAGES_ENABLED` | ❌ | `FALSE` | Zet op `TRUE` om de optionele functie *AI-afbeeldingen* te tonen (productafbeeldingen uit een foto, gemaakt met OpenAI GPT Image). De API-sleutel voer je in de app in onder Instellingen, niet in `.env` |
| `FILAMENT_LIBRARY_URL` | ❌ | `library/filaments.json` van deze repository | Waar *Instellingen → Filamenten → Synchroniseren* de gedeelde filamentbibliotheek vandaan haalt: een JSON-bestand in het formaat van de bibliotheek-export, op `raw.githubusercontent.com`. Leeg zet de knop Synchroniseren uit |
| `SPOOLMAN_URL` | ❌ | leeg (vul het in de app in) | Het adres van je [Spoolman](https://github.com/Donkie/Spoolman) zoals de container van de app het bereikt, bijvoorbeeld `http://spoolman:8000` (zonder inlog). Daarmee leest *Instellingen → Filamenten → Synchroniseren* de rollen en wat er nog op zit uit Spoolman (een rol die je hier al had, wordt gekoppeld en verschijnt niet dubbel), houdt Spoolman het verbruik bij (afboeken vanuit een 3D Model staat dan uit) en kunnen de bibliotheek en je eigen rollen erheen worden gezet. Laat het leeg om het adres in de app in te vullen (beheerders, *Instellingen → Filamenten*); staat het hier, dan gaat dat voor en toont de app het alleen-lezen |
| `PROXY_HOPS` | ❌ | `0` | Aantal reverse proxies voor de app |
| `WEB_CONCURRENCY` | ❌ | `2` | Aantal Gunicorn-workers |
| `PRINTPRICING_UPDATE_CHECK` | ❌ | `true` | De updatecontrole: de app vraagt aan GitHub of er een nieuwere stabiele release is en meldt dat aan de eigenaar met een melding en onder *Instellingen → Beheer → Over → Updatecontrole*. Er wordt niets over jouw installatie meegestuurd en er wordt nooit iets bijgewerkt. `false` (ook `0`, `no`, `off`) zet het uit, voor een installatie die niet naar buiten mag bellen. Een beta-build ziet alleen stabiele releases |

## Beheer

| Taak | Commando |
|---|---|
| Starten | `docker compose up -d` |
| Stoppen | `docker compose down` (de data blijft in `DATA_PATH`) |
| Bijwerken | `sh scripts/update.sh`, dat eerst de database naar `DATA_PATH/backups` kopieert; of met de hand `docker compose pull && docker compose up -d` |
| Terug naar de vorige versie | zet `PRINTPRICING_TAG` op het vorige versienummer, dan `docker compose up -d`; de kopie die `scripts/update.sh` maakte staat in `DATA_PATH/backups` |
| Logboek | `docker compose logs -f app` |

- **Health check:** `GET /healthz` antwoordt `200` met `{"status": "ok", "version": …, "commit": …}` zolang het proces leeft; `GET /readyz` controleert ook de database en antwoordt `503` als die niet reageert.
- **Grootste upload:** 50 MB per STL/3MF-bestand (`MAX_UPLOAD_MB`). Wat voor de app staat (een reverse proxy, een CDN) moet minstens `MAX_UPLOAD_MB` + 1 MB toelaten, en zoveel als je back-up groot is als je er een met printbestanden terugzet (tot 2 GB). Elke limiet buiten de repository staat in de [handleiding](docs/handleiding.md), *Limieten buiten de repository*.
- **Updatecheck:** de app meldt de eigenaar dat er een nieuwere stabiele versie is. Hij vraagt het aan GitHub (de nieuwste stabiele release van deze repository, er wordt niets over jouw installatie meegestuurd), toont een melding en *Instellingen → Beheer → Over → Updatecontrole*, en werkt zichzelf nooit bij. `PRINTPRICING_UPDATE_CHECK=false` zet het uit.

Meldingen en al het andere over het draaiende houden van de app staan in de [handleiding](docs/handleiding.md).

## Data en back-ups

Alles staat onder `DATA_PATH`:

| Map | Wat erin staat |
|---|---|
| `db/` | de database, `printpricing.sqlite3` (met een `-wal`- en `-shm`-bestand ernaast zolang de app draait) |
| `uploads/` | de geüploade STL- en 3MF-bestanden |
| `backups/` | de kopieën van de database die `scripts/update.sh` vóór een update maakt, en in `backups/auto/` de automatische back-ups van de app |
| `postgres/` | de database van de releases vóór SQLite, alleen als je daarvan komt; één keer gelezen om de data over te zetten, daarna mag je hem zelf opruimen |

Maak een back-up vanuit de app (*Instellingen → Beheer → Back-up*): één JSON-bestand, of een ZIP-bestand als je de printbestanden meeneemt. Die back-up bevat nooit inloggegevens (passkeys, herstelcodes, wachtwoorden, pushaanmeldingen), gebruikers of uitnodigingen. Voor de hele server kopieer je de database met `docker compose exec -T app python backup_db.py /data/backups/backup-$(date +%F).sqlite3` en bewaar je ook `uploads/`, of stop je de stack en kopieer je `DATA_PATH`; een gewone `cp` van de database terwijl de app draait is geen consistente kopie. Bewaar `.env` apart, in je wachtwoordmanager.

De app maakt ook zelf back-ups: standaard elke 12 uur hetzelfde ZIP-bestand (met de printbestanden, de bestellingen en hun facturen) in `DATA_PATH/backups/auto`, en hij bewaart de nieuwste 14, een week; een nieuwe vervangt de oudste. Een beheerder zet het uit, kiest hoe vaak (elke 0,5, 1, 2, 7 of 14 dagen) en hoeveel er bewaard blijven (0 tot 60) onder *Instellingen → Beheer → Back-up*. *Instellingen → Beheer → Back-up* toont ze samen met elke back-up die je met *Maak back-up* maakt, die daar bewaard wordt (niet gedownload) en nooit door de rotatie wordt opgeruimd, om te downloaden, terug te zetten of te verwijderen (verwijderen vraagt om je passkey, of je wachtwoord en code). Ze staan op dezelfde schijf als de data die ze beschermen, dus kopieer er af en toe een van de server af, en reken op ongeveer 14 keer de grootte van `uploads/` plus de database. Details: [handleiding](docs/handleiding.md), *Automatische back-ups*.

Terugzetten: *Herstellen uit back-up…* controleert eerst het hele bestand, laat zien wat er terugkomt en vervangt na jouw bevestiging alles in één keer; lukt iets niet, dan verandert er niets. Een databasekopie zet je terug met de app gestopt, op de plek van `db/printpricing.sqlite3`, nadat je het `-wal`- en `-shm`-bestand hebt weggehaald; de commando's staan in de [handleiding](docs/handleiding.md), *Back-up en herstel*.

*Instellingen → Systeem → Opruimen → Terug naar fabrieksinstellingen…* zet de app terug naar een nieuwe installatie: dat verwijdert alles in de database en de uploads (ook de passkeys), na een getypt woord en een verse bevestiging met passkey (of wachtwoord en code), en laat `.env`, de image en `DATA_PATH/backups` (ook de automatische back-ups) staan. Maak eerst een back-up als je het niet zeker weet.

## Architectuur

```mermaid
flowchart LR
    A[Telefoon of desktop<br/>geïnstalleerde PWA] -->|https| P[Reverse proxy<br/>TLS]
    P --> B[App-container<br/>Flask API + PWA-bestanden]
    B --> C[(SQLite-bestand)]
    B --> D[/Geüploade STL- en 3MF-bestanden/]
    B -.->|optioneel web push| E[Pushdiensten]
    B -.->|eenmalige import| F[(PostgreSQL van<br/>eerdere releases)]
```

| Onderdeel | Doel | Gegevens |
|---|---|---|
| `app` | Gunicorn serveert de Flask-API en de PWA-bestanden; draait de databasemigraties voordat hij verkeer krijgt | `DATA_PATH/db`, `DATA_PATH/uploads` |
| `db` | de PostgreSQL 17 van de releases vóór SQLite, alleen één keer gelezen om de data over te zetten; gaat weg in de volgende release | `DATA_PATH/postgres` |

- **App / frontend:** een Progressive Web App in gewoon JavaScript, zonder buildstap, met een service worker voor de offline schil
- **Backend:** Python, Flask en Gunicorn; passkeys via de open-source bibliotheek `py_webauthn` (pakket `webauthn`)
- **Database:** SQLite (één bestand, WAL-modus), met alleen-vooruit migraties die op checksum bewaakt worden
- **Infrastructuur:** Docker Compose, een image die CI naar GHCR publiceert

## Stabiel en beta

| | Stabiel | Beta |
|---|---|---|
| Branch | `main` | `beta` |
| Image | `ghcr.io/flux76hq/3dprint_pricing:latest` (en `X.Y.Z`) | `ghcr.io/flux76hq/3dprint_pricing:beta` |
| GitHub-release | `vX.Y.Z` | geen |

Elke wijziging komt eerst in `beta`, en elke push naar `beta` bouwt een nieuwe beta-image. Pas als de beta zich bewijst, wordt hij gepromoveerd naar `main`, wat `VERSION` ophoogt en `latest` en de release bouwt. Om de beta te proberen zet je `PRINTPRICING_TAG=beta` in `.env` (de app toont dan een **beta**-label naast zijn naam) en draai je `docker compose pull && docker compose up -d`; gebruik daarvoor een aparte datamap.

## Meewerken

Bijdragen zijn welkom. Pull requests gaan naar de branch `beta`, nooit rechtstreeks naar `main`; `main` is de stabiele lijn en krijgt alleen een promotie-pull-request vanuit `beta`. De werkafspraken voor mensen en AI-hulpen staan in [`AGENTS.md`](AGENTS.md): versiebeheer, lokale controles, tests en de werkwijze voor pull requests. Voor fouten en ideeën open je een [issue](https://github.com/Flux76HQ/3dprint_pricing/issues/new/choose).

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements-dev.txt
python scripts/setup_hooks.py
cd backend && PYTHONPATH=. python -m pytest -q
```

De schermafbeeldingen hierboven komen uit een demo-installatie: na een wijziging die een scherm anders laat uitzien draai je `pip install playwright && python scripts/generate_screenshots.py` en commit je de bijgewerkte afbeeldingen in `docs/assets/`.

## Privacy en beveiliging

- Alles staat op je eigen server: geen account bij ons, geen analytics en geen tracking.
- Inloggen gaat met passkeys of, waar een passkey niet kan werken, met een wachtwoord (gehasht met argon2id), optioneel met tweestapsverificatie.
- Een back-up uit de app bevat nooit inloggegevens (passkeys, herstelcodes, wachtwoorden, pushaanmeldingen) of uitnodigingen. Een uitnodigingslink wordt één keer getoond en alleen de hash ervan wordt bewaard.
- Meld een kwetsbaarheid vertrouwelijk, via een [privé security advisory](https://github.com/Flux76HQ/3dprint_pricing/security/advisories/new) of rechtstreeks bij de beheerders ([@Flux76HQ](https://github.com/Flux76HQ)), nooit in een openbaar issue.

## Steun 3D Print Pricing

3D Print Pricing is gratis. Heb je er iets aan? Met een koffie houd je de ontwikkeling gaande.

<a href="https://buymeacoffee.com/flux76"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy me a coffee" height="40"></a>
<a href="https://ko-fi.com/flux76"><img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Steun me op Ko-fi" height="40"></a>

## Licentie

Er is nog geen licentie gekozen: alle rechten voorbehouden.

---

<div align="center">
<sub>Met ❤️ gemaakt in Nederland door <a href="https://flux76.com">Flux76</a></sub>
</div>
