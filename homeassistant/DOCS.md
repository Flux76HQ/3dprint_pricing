# 3D Print Pricing

This app runs [3D Print Pricing](https://github.com/Flux76HQ/3dprint_pricing) inside Home Assistant. Everything it stores (one SQLite database
and the uploads) lives in the app's own data folder, which Home Assistant includes in its backups.

## Install

1. In Home Assistant open **Settings > Apps > Install app**, then the menu (⋮) > **Repositories**, and add
   `https://github.com/Flux76HQ/3dprint_pricing`.
2. Choose **3D Print Pricing** and **Install**. Home Assistant builds the app on your device, which takes a few minutes the first time.
3. Optionally fill in **rp_id** on the **Configuration** tab (see below), save, and **Start** the app.
4. Open the **Log** tab: the setup code for the first screen is printed there (or type your own under *Setup code*).
5. Open the app (`https://<your domain>` with a domain, otherwise `http://<address of Home Assistant>:6080`) and go through the onboarding: setup code, your name, a passkey or a password, and save the 8 recovery codes.

## Passkey or password

The app works on any address. How you sign in depends on it:

- **A password** works everywhere, also on `http://<address of Home Assistant>:6080` on your own network. Choose it on the first screen; you can add
  two-step verification with an authenticator app later, under Settings.
- **A passkey** is more secure and easier, but a browser only creates one on a page served over **https**, on a **domain name** (not an IP address and not
  `http://homeassistant.local:6080`; `http://localhost` is the one exception). For that the app has to be reachable on an https address you control, and that
  address is what you enter below. The first screen tells you when a passkey cannot work on the address you are using.

| Option | What to enter |
|---|---|
| **rp_id** | Optional. The domain only, for example `print.example.com`. Leave it empty to follow the address the app is opened on. Passkeys are bound to it: changing it later makes existing passkeys unusable (recovery codes still work). Set it once you use passkeys. |
| **rp_origins** | Optional. The full address(es), comma separated, for example `https://print.example.com`. Empty means `https://` plus the domain, or the address the app is opened on when there is no domain. When set, writes from any other address are refused. |
| **proxy_hops** | `1` when one reverse proxy sits in front of the app (the usual case), `0` when the app is opened on its port directly. |

For passkeys put a reverse proxy with a certificate in front of port **6080** of this app (for example the Nginx Proxy Manager or Caddy app, a
Cloudflare Tunnel, or Tailscale serve). Home Assistant Cloud (Nabu Casa) only forwards Home Assistant itself, not other ports. The app is
not offered through the Home Assistant sidebar (Ingress): it is made to be served from the root of its own domain, which is what passkeys are bound to.

## Options

| Option | Meaning |
|---|---|
| **setup_code** | Typed once on the first screen. Empty makes one and prints it in the Log. |
| **max_upload_mb** | Largest STL/3MF upload. A proxy in front has to allow at least as much. |
| **ai_images_enabled** | Switches on the optional AI product images. The OpenAI key is entered in the app, under Settings. |
| **spoolman_url** | Address of a Spoolman, for example `http://homeassistant.local:7912`. Empty: type it in the app (Settings > Filaments). |
| **update_check** | The app asks GitHub whether a newer release exists and tells the owner. It never updates anything; updating is done here, in Home Assistant. |

Changes take effect after a restart of the app.

## Data, backups and moving

- The database is the file `/data/db/printpricing.sqlite3`, the uploads are in `/data/uploads` and the generated secrets (session key, push keys)
  in `/data/secrets.json`. Home Assistant stops the app while it makes a backup (a database that is being written is not a consistent copy), so a backup
  takes the app offline for a moment.
- The app also has its own backup and restore (Settings > System), which is the way to move an installation between this app and the Docker
  Compose installation, in either direction. A backup file never contains passkeys or users: the person restoring signs up again.
- An installation from before the SQLite releases still has its database in `/data/postgres`. On the first start after the update the app moves
  it into the SQLite file by itself (PostgreSQL runs for that one start); `/data/postgres` is left alone, and you can remove it once the app works.
  The app refuses to start rather than begin empty when it finds that folder and cannot import it.

## Updating

A new release shows up as an update of this app. Updating rebuilds the app on your device and restarts it; migrations run on start. The
architectures are **amd64** and **aarch64** (the published image is built for both, so it also runs on a Raspberry Pi 4/5 or an ARM mini PC).
