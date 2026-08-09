# CI

GitHub Actions workflow definitions.

The actual workflow files live at `.github/workflows/` — that's the only
location GitHub Actions reads from, so this directory can't hold the real
YAML itself. What's wired up today:

- `backend-ci.yml` — `uv sync`, `ruff check`, `mypy`, then `pytest` (real
  Postgres via testcontainers — the runner's preinstalled Docker handles
  this without any extra service config).
- `frontend-ci.yml` — `tsc --noEmit`, then `npm run lint` (eslint).

Both trigger on push/PR, scoped by path (`backend/**` /
`apps/web/**`) so an unrelated change doesn't run the other stack's job.

No component/e2e test runner exists yet for the frontend (Vitest/Playwright
were named in the original stack plan but never actually set up) — add a
`test` job to `frontend-ci.yml` once one does.

## Dependency audit

`uvx pip-audit` on the backend is clean (0 known vulnerabilities). `npm audit`
on the frontend reports 12 "high" findings, all dev-tooling or Next.js-16
false positives, not currently actionable:

- Several trace to `eslint`'s `minimatch` chain (ReDoS-class, dev-only —
  never runs in production, only in CI/local lint).
- The rest trace to Next.js itself via `postcss`/`sharp`, where npm's audit
  database's `fixAvailable` suggests downgrading Next 16 → 9.3.3 — a
  7-major-version regression with no real bearing on this app, a symptom of
  the advisory DB not yet having proper ranges for Next's intentionally
  bleeding-edge canary line (see `apps/web/AGENTS.md`).

Re-run `npm audit` after any Next.js upgrade to confirm these clear rather
than assuming they're permanent.
