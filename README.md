# AETHERBELT

The unified local toolbelt for the **Aether constellation** — one command that
bundles your our-own tools, runs their health checks, and plugs into
[AETHERBUS](https://github.com/Mellowambience/aetherbus) so it stays connected
to everything else (coinmoth, vault-lint, citewise, fairy-os, bus-reflect).

Built our-own: single small package, **zero paid deps**, local-first, MIT. No
account, no cloud, no network at startup. Each tool keeps its own repo;
aetherbelt discovers them by path and routes.

## Install
```
pip install -e .
```
(needs `aetherbus` on the same machine and the our-own tool repos under your home dir)

## Commands
```
aetherbelt status        # show every our-own tool, path, git head, liveness
aetherbelt selfcheck     # smoke-test each tool; emit results to AETHERBUS
aetherbelt bus           # observe the shared AETHERBUS event spine
aetherbelt dispatch <id> [args...]   # run a tool by its short id
```

## Posting (approval-gated — you flip the switch)
```
aetherbelt share <note.md> [--thread]   # draft a post/thread from a note -> outbox
aetherbelt outbox [-n 10]               # preview queued drafts
aetherbelt send --id N                 # POST (owner flip; needs X creds)
```
The agent **drafts and queues only**. Posting requires credentials in the
environment AND your explicit `send`. Without them, `send` hard-refuses — no
silent network calls (Steward: consent + accountability).

### X (Twitter) credentials — two ways
1. **Static bearer (simple):** set `X_BEARER_TOKEN` (or `X_API_KEY`) to a
   user-context access token. That's it.
2. **OAuth 2.0 user-context (recommended):** set the app pair +
   refresh token once; `send` mints a short-lived bearer per post (nothing
   written to disk):
   ```
   X_CLIENT_ID=...        # OAuth 2.0 Client ID (your app)
   X_CLIENT_SECRET=...    # OAuth 2.0 Client Secret
   X_REFRESH_TOKEN=...    # long-lived refresh token from your initial auth
   ```
   The bearer is resolved in-process only; it is never stored.

> **Tier note:** X API **Free** tier is read-only and cannot post. Posting
> needs at least the **Basic** ($100/mo) tier. If `send` returns a 403, that's
> the tier, not the code.

**Never** commit credentials. Put them in your shell env or a local `.env`
(that aetherbelt's `.gitignore` already excludes). The agent never asks for
them and never stores them.


## Tools wired
| id | repo | check |
|----|------|-------|
| coinmoth | coinmoth-cli | `scan` smoke |
| citewise | our-own-citewise | `--self-check` |
| vault-lint | hybrid-vault-lint | manual (needs a vault path) |
| limen | limen | manual (not yet checked out locally) |

MIT · local-first · no lock-in.
