# Remote asset library (self-hosted)

One team library, many thin Godot checkouts. Artists publish finished
assets once; developers browse the catalog from inside the editor and
download only what they need — no terabyte clones, no vendor cloud.

## Run it

```bash
cp .env.example .env        # then set a real ASSETMGR_LIBRARY_TOKEN
docker compose up -d --build library
curl localhost:8081/health # -> {"ok": true}
```

Data lives in the `library-data` volume (`store/` blobs + `library.db`).
The API is token-authenticated (`Authorization: Bearer <token>`):

- `GET /api/v1/assets?q=&tag=&kind=` — search the catalog
- `POST /api/v1/assets?name=&kind=&importer=&params={}&tags=` (raw body)
  — publish; replies `{"id", "blob_sha256"}` (dedupe is by content hash)
- `GET /api/v1/assets/<id>/blob` — download bytes

The same operations exist offline-first on the CLI:
`assetmgr library-init|library-push|library-pull` (see `docs/API.md`).
Uploads are capped at 2 GiB (`MAX_UPLOAD_BYTES`); no chunked upload yet.

## Connect Godot

1. Copy `godot-plugin/addons/asset_library/` into your project's `addons/`.
2. Project → Project Settings → Plugins → enable **Asset Library**.
3. Open the dock (left), enter server URL + token, Search, select, Download.
   Files land in `res://<name>` and the editor filesystem rescans, so
   `.import` sidecars generate on the spot.

Publish the other way with the `godot::publish-to-library` action
(importer + params travel in the upload), or plain
`assetmgr library-push`.

## Security notes (read before exposing this)

- Token auth: one token per teammate, created locally against the DB file
  (plaintext shown once, only digests stored).
- Revocation is instant (`library-token-revoke`); revoked tokens 401.
  There are no roles — every live token reads and writes everything.
- No TLS, no rate limiting. Fine on a LAN / VPN or behind a reverse proxy
  that adds TLS — do not put 8081 directly on the internet.
- Tokens live in `.env` (git-ignored; see `.env.example`) only as the
  *bootstrap* secret: on first start it seeds the `default` token, and is
  ignored once any token exists. Prefer per-user tokens after that.
- Rotate by revoking the name and creating a fresh one.
- The server trusts its operator: anyone with the token can read and
  write every asset.
