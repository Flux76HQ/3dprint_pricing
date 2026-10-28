# 3D Print Pricing

*English below · Nederlands eerst.*

## Nederlands

[3D Print Pricing](https://github.com/Flux76HQ/3dprint_pricing) rekent de kostprijs van elke 3D-print uit (filament, onderdelen, printerafschrijving, energie) en houdt de voorraad en tarieven bij waar die prijzen op gebaseerd zijn, met klanten, bestellingen en facturen. Deze app draait dezelfde app als de Docker-versie, met een eigen PostgreSQL in dezelfde container: je hoeft verder niets te installeren.

### Installeren

1. Ga in Home Assistant naar **Instellingen > Apps > App installeren** (voorheen *Add-ons*), open het menu rechtsboven (⋮) en kies **Repositories**.
2. Voeg `https://github.com/Flux76HQ/3dprint_pricing` toe.
3. Kies **3D Print Pricing** en klik op **Installeren**. Home Assistant bouwt de app op je apparaat; de eerste keer duurt dat een paar minuten.
4. Klik op **Starten** en open het tabblad **Logboek**: bij de allereerste start staat daar de **setupcode** voor het eerste scherm.
5. Open `http://<adres van Home Assistant>:6080` (of **Webinterface openen**) en doorloop de onboarding: setupcode, je naam, een wachtwoord of een passkey, en bewaar de 8 herstelcodes.

Alle opties zijn optioneel. Heb je de setupcode in het logboek gemist (hij wordt maar één keer getoond), vul dan zelf een code in bij de optie *Setupcode* en start de app opnieuw: die code geldt dan.

### Inloggen: wachtwoord of passkey

De app werkt op elk adres. Hoe je inlogt hangt van dat adres af:

- **Een wachtwoord** (minstens 12 tekens) werkt overal, ook op `http://<adres van Home Assistant>:6080` in je eigen netwerk. Kies het op het eerste scherm. Tweestapsverificatie met een authenticator-app zet je daarna zelf aan onder **Instellingen > Beveiliging**.
- **Een passkey** is veiliger en makkelijker, maar een browser maakt er alleen een op een pagina met **https** en een **domeinnaam**: niet op een IP-adres en niet op `http://homeassistant.local:6080` (`http://localhost` is de enige uitzondering). Daarvoor moet de app bereikbaar zijn op een https-adres dat van jou is (zie *Beveiliging* hieronder); dat adres vul je in bij *Domein voor passkeys*. Het eerste scherm zegt het als een passkey op het adres dat je gebruikt niet kan werken, en zet het wachtwoord dan al open.
- **Meer mensen:** een beheerder nodigt anderen uit met een link (**Instellingen > Gebruikers**). Elk kiest zelf een wachtwoord of passkey; niemand kent die van een ander.
- **Herstelcodes** zijn je weg terug als je je apparaat of wachtwoord kwijt bent. Bewaar ze buiten de app.

### Opties

| Optie | Betekenis |
|---|---|
| **rp_id** (Domein voor passkeys) | Alleen het domein, bijvoorbeeld `print.voorbeeld.nl`, zonder `https://` of poort. Leeg: het adres waarop je de app opent. Een passkey is aan dit domein gebonden: wijzig je het later, dan werken bestaande passkeys niet meer (herstelcodes wel). Zet het vast zodra je passkeys gebruikt. |
| **rp_origins** (Adres(sen) waarop de app wordt geopend) | Het volledige adres, kommagescheiden, bijvoorbeeld `https://print.voorbeeld.nl`. Leeg: `https://` plus het domein, of het adres waarop je de app opent als er geen domein is. Is het ingevuld, dan weigert de app schrijvende verzoeken vanaf een ander adres. |
| **setup_code** | Wordt één keer op het eerste scherm getypt. Leeg: de app maakt er een en zet die bij de eerste start in het logboek. |
| **proxy_hops** | Hoeveel reverse proxy's tussen de browser en de app staan: `1` voor één proxy (het gewone geval), `0` als je de app rechtstreeks op zijn poort opent. |
| **max_upload_mb** | Grootste STL/3MF-bestand dat de app aanneemt (standaard 50). Een proxy ervoor moet minstens zoveel toestaan. |
| **ai_images_enabled** | Zet de optionele AI-productafbeeldingen aan. De OpenAI-sleutel voer je in de app in, onder **Instellingen**. |
| **spoolman_url** | Adres van een Spoolman, bijvoorbeeld `http://homeassistant.local:7912`. Leeg: typ het in de app (**Instellingen > Filamenten**). |
| **update_check** | De app vraagt aan GitHub of er een nieuwere versie is en meldt dat aan de eigenaar. Hij werkt nooit zelf bij: dat doe je hier, in Home Assistant. |

Wijzigingen gelden na een herstart van de app.

### Spoolman bereiken

- **Spoolman als app:** gebruik het adres dat Home Assistant eraan geeft, zoals `http://<hostnaam-van-de-app>:7912` (te zien op de infopagina van die app). Zet dat in de optie *Spoolman-adres* of in de app.
- **Spoolman elders:** het adres waarop de Home Assistant-machine Spoolman bereikt, bijvoorbeeld `http://192.168.1.20:7912`.

### Beveiliging

De webinterface staat op poort 6080 van je netwerk en heeft **geen ingress**: de app heeft zijn eigen inlog (wachtwoord, tweestapsverificatie, passkeys) en is gemaakt om op de root van een eigen adres te draaien, waaraan passkeys gebonden zijn. Zet de poort niet rechtstreeks op internet. Wil je van buitenaf bij de app, of passkeys gebruiken, zet er dan een reverse proxy met een certificaat voor (bijvoorbeeld de Nginx Proxy Manager- of Caddy-app, een Cloudflare Tunnel of Tailscale serve), zet **proxy_hops** op `1` en vul **rp_id** in. Home Assistant Cloud (Nabu Casa) stuurt alleen Home Assistant zelf door, geen andere poorten.

### Gegevens en back-ups

Alles staat in de data-map van de app: de database in `/data/postgres`, de uploads in `/data/uploads` en de gegenereerde geheimen (sessiesleutel, databasewachtwoord, pushsleutels) in `/data/secrets.json`. Home Assistant neemt die mee in elke back-up van de app en zet ze ook weer terug. Tijdens een back-up wordt de app kort gestopt, omdat een draaiende database geen consistente kopie is.

In de app maak je daarnaast een eigen back-upbestand onder **Instellingen > Systeem > Back-up en herstel**. Dat is de weg om te verhuizen tussen deze app en de Docker Compose-installatie, in beide richtingen. Zo'n bestand bevat nooit passkeys, wachtwoorden of gebruikers: richt de nieuwe installatie eerst in (onboarding) en herstel daarna het bestand.

De database is PostgreSQL 17. Een data-map van een ander hoofdnummer kan niet geopend worden; de app weigert dan te starten in plaats van eraan te komen.

### Updaten

Home Assistant meldt een nieuwe versie bij de app; klik op **Bijwerken**. Dat bouwt de app opnieuw op je apparaat en herstart hem; de database wordt zo nodig vanzelf aangepast. De app draait op **amd64** en **aarch64** (de gepubliceerde image is voor beide gebouwd, dus ook op een Raspberry Pi 4/5 of een ARM-minipc). De release-teksten staan op [GitHub](https://github.com/Flux76HQ/3dprint_pricing/releases).

### Problemen oplossen

- **De app start niet:** kijk onderaan het tabblad **Logboek**; de laatste regel zegt waarom (bijvoorbeeld een ongeldige waarde bij *Domein voor passkeys*, of een data-map van een andere PostgreSQL-versie).
- **Passkey werkt niet:** open de app via het https-adres met je domeinnaam en controleer **rp_id** en **rp_origins**. Op een IP-adres kan het niet; log dan in met je wachtwoord.
- **Alles geweigerd na het instellen van een domein:** staat **rp_origins** ingevuld, dan moet het exact het adres in de adresbalk zijn (met `https://`, zonder `/` erachter), en moet **proxy_hops** kloppen met je proxy.
- **Wachtwoord vergeten of toestel kwijt:** log in met een herstelcode; een beheerder kan voor iemand anders een nieuwe inloglink maken (**Instellingen > Gebruikers**).
- **Een foutmelding over de versie of de database na een update:** meld het op [GitHub](https://github.com/Flux76HQ/3dprint_pricing/issues) met het versienummer uit de zijbalk van de app.

## English

[3D Print Pricing](https://github.com/Flux76HQ/3dprint_pricing) works out the cost price of every 3D print (filament, parts, printer depreciation, energy) and keeps the inventory and tariffs those prices are based on, with customers, orders and invoices. This app runs the same app as the Docker version, with its own PostgreSQL in the same container: nothing else has to be installed.

### Installing

1. In Home Assistant go to **Settings > Apps > Install app** (formerly *Add-ons*), open the menu at the top right (⋮) and choose **Repositories**.
2. Add `https://github.com/Flux76HQ/3dprint_pricing`.
3. Choose **3D Print Pricing** and click **Install**. Home Assistant builds the app on your device; the first time that takes a few minutes.
4. Click **Start** and open the **Log** tab: on the very first start it shows the **setup code** for the first screen.
5. Open `http://<address of Home Assistant>:6080` (or **Open web UI**) and go through the onboarding: setup code, your name, a password or a passkey, and save the 8 recovery codes.

All options are optional. If you missed the setup code in the log (it is shown once), type your own code in the *Setup code* option and restart the app: that code then applies.

### Signing in: password or passkey

The app works on any address. How you sign in depends on that address:

- **A password** (at least 12 characters) works everywhere, also on `http://<address of Home Assistant>:6080` on your own network. Choose it on the first screen. You can turn on two-step verification with an authenticator app afterwards, under **Settings > Security**.
- **A passkey** is more secure and easier, but a browser only creates one on a page served over **https**, on a **domain name**: not on an IP address and not on `http://homeassistant.local:6080` (`http://localhost` is the one exception). For that the app has to be reachable on an https address you control (see *Security* below); that address is what you enter in *Domain for passkeys*. The first screen tells you when a passkey cannot work on the address you are using, and opens the password for you.
- **More people:** an administrator invites others with a link (**Settings > Users**). Each chooses their own password or passkey; nobody knows anyone else's.
- **Recovery codes** are your way back in when you lose your device or password. Keep them outside the app.

### Options

| Option | Meaning |
|---|---|
| **rp_id** (Domain for passkeys) | The domain only, for example `print.example.com`, without `https://` or a port. Empty: the address you open the app on. A passkey is bound to this domain: changing it later makes existing passkeys unusable (recovery codes still work). Set it once you use passkeys. |
| **rp_origins** (Address(es) the app is opened on) | The full address, comma separated, for example `https://print.example.com`. Empty: `https://` plus the domain, or the address you open the app on when there is no domain. When set, the app refuses writes from any other address. |
| **setup_code** | Typed once on the first screen. Empty: the app makes one and prints it in the log on the first start. |
| **proxy_hops** | How many reverse proxies sit between the browser and the app: `1` for one proxy (the usual case), `0` when you open the app directly on its port. |
| **max_upload_mb** | Largest STL/3MF file the app accepts (default 50). A proxy in front has to allow at least as much. |
| **ai_images_enabled** | Switches on the optional AI product images. The OpenAI key is entered in the app, under **Settings**. |
| **spoolman_url** | Address of a Spoolman, for example `http://homeassistant.local:7912`. Empty: type it in the app (**Settings > Filaments**). |
| **update_check** | The app asks GitHub whether a newer release exists and tells the owner. It never updates anything itself: that is done here, in Home Assistant. |

Changes take effect after a restart of the app.

### Reaching Spoolman

- **Spoolman as an app:** use the address Home Assistant gives it, such as `http://<host name of the app>:7912` (shown on the info page of that app). Put it in the *Spoolman address* option or in the app.
- **Spoolman elsewhere:** the address at which the Home Assistant machine reaches Spoolman, for example `http://192.168.1.20:7912`.

### Security

The web interface is on port 6080 of your network and has **no ingress**: the app has its own login (password, two-step verification, passkeys) and is made to be served from the root of an address of its own, which is what passkeys are bound to. Do not expose the port directly to the internet. To reach the app from outside, or to use passkeys, put a reverse proxy with a certificate in front of it (for example the Nginx Proxy Manager or Caddy app, a Cloudflare Tunnel or Tailscale serve), set **proxy_hops** to `1` and fill in **rp_id**. Home Assistant Cloud (Nabu Casa) only forwards Home Assistant itself, not other ports.

### Data and backups

Everything is in the app's data folder: the database in `/data/postgres`, the uploads in `/data/uploads` and the generated secrets (session key, database password, push keys) in `/data/secrets.json`. Home Assistant includes it in every backup of the app and restores it too. The app is stopped briefly during a backup, because a running database is not a consistent copy.

In the app you can also make a backup file of your own under **Settings > System > Backup and restore**. That is the way to move between this app and the Docker Compose installation, in either direction. Such a file never contains passkeys, passwords or users: set up the new installation first (the onboarding), then restore the file.

The database is PostgreSQL 17. A data folder of another major version cannot be opened; the app refuses to start rather than touch it.

### Updating

Home Assistant announces a new version on the app; click **Update**. That rebuilds the app on your device and restarts it; the database is extended automatically when needed. The app runs on **amd64** and **aarch64** (the published image is built for both, so it also runs on a Raspberry Pi 4/5 or an ARM mini PC). The release notes are on [GitHub](https://github.com/Flux76HQ/3dprint_pricing/releases).

### Troubleshooting

- **The app does not start:** look at the bottom of the **Log** tab; the last line says why (for example an invalid value in *Domain for passkeys*, or a data folder of another PostgreSQL version).
- **A passkey does not work:** open the app through the https address with your domain name and check **rp_id** and **rp_origins**. It cannot work on an IP address; sign in with your password instead.
- **Everything is refused after setting a domain:** when **rp_origins** is filled in it has to be exactly the address in the address bar (with `https://`, without a trailing `/`), and **proxy_hops** has to match your proxy.
- **Forgot the password or lost a device:** sign in with a recovery code; an administrator can make a new sign-in link for someone else (**Settings > Users**).
- **A message about the version or the database after an update:** report it on [GitHub](https://github.com/Flux76HQ/3dprint_pricing/issues) with the version number from the sidebar of the app.
