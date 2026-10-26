## Summary

<!-- What changes and why, in two or three sentences. Link the issue: "Closes #123". The base branch is `beta`. -->

## Deployment files

<!--
Required when the PR touches a Compose file (docker-compose*.yml), the Dockerfile,
deploy/ or .env.example. State it as an operator instruction, not a diff summary:
exact variable name, its default, whether it must be added by hand, the exact
Compose mapping line if one changed, and whether an existing installation keeps
working untouched or must be edited before the next update.
If nothing applies, write exactly: "No deployment-file changes in this PR."
-->

## Limits

<!--
Required when the PR raises or lowers a size, rate or timeout limit (MAX_UPLOAD_MB,
Gunicorn timeout, rate limits, ...). State the new value as a number the operator can
act on ("the largest request is now 60 MB; whatever runs in front must allow at least
that"), never as one proxy's directive. Otherwise write "No limit changes in this PR."
-->

## Checklist

- [ ] `VERSION` is untouched (the promotion to `main` raises it; label the promotion pull request `version:minor` / `version:major` if it must not be a patch).
- [ ] The branch is based on `beta`, this pull request targets `beta`, and it is current with it (`python scripts/update_branch.py`).
- [ ] No secrets or `.env` files are staged.
- [ ] `docs/handleiding.md` is updated when run, deploy or backup behaviour changed.
- [ ] `README.md` and `README.nl.md` stay in sync (same sections, same order, same screenshots from `docs/assets/`).
- [ ] Tests added or updated; `cd backend && PYTHONPATH=. python -m pytest -q` passes.
- [ ] Standards: anything defined by a standard (passkeys, OAuth, JWT, TOTP...) uses an existing open-source module, named here, or the exception is explained (baseline §19).
- [ ] The other agent clients' surfaces are still correct — `AGENTS.md` §7 (entry files, client-surface table).
