# Docker Compose

Per-environment compose files: Temporal, OPA, OpenBao, Langfuse (+ ClickHouse/Redis/S3 — see ADR-0001), Prometheus/Grafana, SeaweedFS, mcp-context-forge.

## Two compose files, two purposes

- **`docker-compose.yml`** — infra only (Postgres, Redis, Temporal, OPA,
  OpenBao, SeaweedFS, otel/Prometheus/Grafana). Local dev runs the app
  itself as bare processes against this (`uvicorn ... --reload` /
  `npm run dev`) so edits take effect without a rebuild.
- **`docker-compose.prod.yml`** — the full stack, containerized:
  `include`s the file above and adds `backend` (`../../backend/Dockerfile`),
  `worker` (same image, `content_studio.workflows.worker` entrypoint), and
  `frontend` (`../../apps/web/Dockerfile`, Next's `standalone` output).
  This is the actual deploy artifact — what Coolify will run — not just a
  dev convenience.

```
docker compose -f docker-compose.prod.yml up --build -d
docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head   # first run / after any migration
```

On a genuinely fresh DB, `backend` crashes once on first boot (no tables yet)
and `worker` would too if it raced Temporal's own cold-start — both now have
`restart: on-failure` / a real `temporal` healthcheck so they self-recover
once migrations exist and Temporal is actually accepting connections. Proven
by wiping all volumes and running the full signup→brief→generate lifecycle
from scratch.

Backend/worker env vars (DB/Redis/Temporal/OPA/OpenBao hosts, JWT secret,
provider API keys) are set in `docker-compose.prod.yml`'s `x-backend-env`
anchor, with dev-safe fallbacks so this runs out of the box like the rest
of the stack — override by copying `.env.example` to `.env` in this same
directory (Compose auto-loads it) before pointing this at anything but a
local machine. This is separate from `backend/.env.example`, which is for
the bare-process dev workflow above.
`NEXT_PUBLIC_API_BASE_URL` is a *build* arg (Next.js has no runtime env for
`NEXT_PUBLIC_*` values), so it must be set correctly before `build`, not
patched in afterward.

## Migrating to Coolify on the VPS

This was built and verified locally first (per-session decision: get a
Contabo VPS later, prove the containerized stack works before moving it).
When the VPS is ready:

1. Install Coolify on the VPS (their one-line install script).
2. Point Coolify at this repo, "Docker Compose" resource type, path
   `infra/docker-compose/docker-compose.prod.yml`.
3. Set real values for every `MUST CHANGE` var in `backend/.env.example`
   (`CS_JWT_SECRET`, `CS_OPENBAO_TOKEN`, object storage keys) as Coolify
   environment variables — never commit real secrets into compose files.
4. Set `NEXT_PUBLIC_API_BASE_URL` to the real public API domain/URL before
   the first frontend build on the VPS — it's baked in at build time.
5. Run the `alembic upgrade head` command above as a Coolify pre-deploy
   command, not inside the container's `CMD` (see the comment in
   `backend/Dockerfile` — avoids a migration race if this ever scales
   beyond one backend replica).
6. Point DNS at the VPS and let Coolify's built-in Traefik handle TLS
   (Let's Encrypt) — no separate reverse-proxy setup needed.
7. **OpenBao is running in dev mode** (`BAO_DEV_ROOT_TOKEN_ID`,
   auto-unsealed, non-durable storage) — fine for local testing, not for
   real customer secrets (OAuth tokens, provider credentials sealed via
   `ports/secrets.py`). Before real users connect any account, switch it to
   real server mode with a durable storage backend and proper unseal keys,
   not just a rotated dev-mode token.
