## Samenvatting

<!-- Wat verandert er en waarom, in twee of drie zinnen. Link het issue: "Closes #123". De basisbranch is `beta`. -->

## Deployment-bestanden

<!--
Verplicht als de PR een Compose-bestand (docker-compose*.yml), de Dockerfile, deploy/ of
.env.example raakt. Formuleer het als instructie voor de beheerder, niet als samenvatting
van de diff: exacte variabelenaam, de standaardwaarde, of die met de hand toegevoegd moet
worden, de exacte Compose-mappingregel als die veranderd is, en of een bestaande
installatie ongewijzigd blijft werken of vóór de volgende update aangepast moet worden.
Is er niets van toepassing, schrijf dan precies: "No deployment-file changes in this PR."
-->

## Limieten

<!--
Verplicht als de PR een limiet voor grootte, aantal verzoeken of time-out verhoogt of
verlaagt (MAX_UPLOAD_MB, Gunicorn-timeout, rate limits, ...). Noem de nieuwe waarde als
getal waar de beheerder iets mee kan ("het grootste verzoek is nu 60 MB; wat ervoor staat
moet minstens dat toestaan"), nooit als directive van één proxy. Anders: "No limit changes in this PR."
-->

## Checklist

- [ ] `VERSION` is onaangeroerd (de promotie naar `main` verhoogt hem; label de promotie-pull request `version:minor` / `version:major` als het geen patch mag zijn).
- [ ] De branch is gebaseerd op `beta`, deze pull request gaat naar `beta` en is actueel met `beta` (`python scripts/update_branch.py`).
- [ ] Er staan geen geheimen of `.env`-bestanden in de commit.
- [ ] `docs/handleiding.md` is bijgewerkt als draaien, deployen of back-ups veranderden.
- [ ] `README.md` en `README.nl.md` lopen gelijk (zelfde secties, zelfde volgorde, zelfde schermafbeeldingen uit `docs/assets/`).
- [ ] Tests toegevoegd of aangepast; `cd backend && PYTHONPATH=. python -m pytest -q` slaagt.
- [ ] Standaarden: alles wat door een standaard is vastgelegd (passkeys, OAuth, JWT, TOTP...) gebruikt een bestaande open-sourcemodule, hier genoemd, of de uitzondering is uitgelegd (baseline §19).
- [ ] De oppervlakken van de andere agent-clients kloppen nog — `AGENTS.md` §7 (entry-bestanden, tabel met client-oppervlakken).
