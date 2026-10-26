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
Uploads are capped at 2 GiB (`MAX_UPLOAD_BYTES`); for anything large use
the session protocol — the CLI switches automatically above 64 MiB
(`--chunk-above BYTES`), or force it with `library-push --chunked
[--chunk-size BYTES]`. Sessions stream in 8 MiB blocks (the server never
holds a whole file in RAM), each attempt gets a fresh session id, and
abandoned sessions are swept on server start.

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
  There are no roles — every live token reads and writes every file.
- TLS is built in, off by default. Pass `--tls-cert/--tls-key`
  (or `ASSETMGR_LIBRARY_TLS_CERT/KEY`) with a PEM pair — self-signed is
  fine on a LAN, use a real certificate (or a reverse proxy that
  terminates for you) for anything internet-facing. Never serve plain
  HTTP past your own network: clients fail closed against a TLS port
  and vice versa.
- Tokens live in `.env` (git-ignored; see `.env.example`) only as the
  *bootstrap* secret: on first start it seeds the `default` token, and is
  ignored once any token exists. Prefer per-user tokens after that.
- Compose with TLS: mount your PEM pair and override the command, e.g.
  volumes `["./certs:/certs:ro"]`, command
  `["-m", "library", "--host", "0.0.0.0", "--port", "8081",
  "--tls-cert", "/certs/fullchain.pem", "--tls-key", "/certs/key.pem"]`.
- Rotate by revoking the name and creating a fresh one.
- The server trusts its operator: anyone with the token can read and
  write every asset.
