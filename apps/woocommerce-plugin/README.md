# WooCommerce Plugin

Thin PHP plugin: connects a WooCommerce store to AI Content Studio in one click, then hands off to the web app to finish connecting Facebook/Instagram. No AI/business logic and no third-party provider keys ever live here — see `13_WOOCOMMERCE_PLUGIN_ARCHITECTURE.md`.

**What's built** (`content-studio-connect.php`, a single-file plugin — no Composer/Action Scheduler/PHPUnit/wp-env, deliberately leaner than the original spec's full vision, since this first slice only needs one settings screen and one outbound HTTP call):

- A settings screen under WooCommerce's own menu (WooCommerce → Content Studio) with a "paste your pairing code" form.
- On submit, generates a real WooCommerce REST API key pair internally (the same way WooCommerce's own "Add Key" screen does, so the store owner never visits that screen) and sends it to the backend's `POST /commerce/connect/plugin` alongside the pairing code.
- On success, shows a "Finish setup: Connect Facebook & Instagram" link to the web app's Quick Start page — the actual Meta OAuth flow still happens there, in a real browser tab, not inside WordPress (Meta blocks iframe embedding, and there's no benefit to reimplementing that flow in PHP).

**Before deploying this plugin anywhere**, set `CS_CONNECT_API_BASE_URL` and `CS_CONNECT_WEB_APP_URL` (top of `content-studio-connect.php`) to the real backend/frontend domains — they default to placeholder values.

**Not yet verified against a real WordPress install** — no PHP or wp-cli tooling exists in the environment this was built in, so this has been reviewed carefully but not executed. The riskiest single piece is `cs_connect_generate_api_keys()`, which inserts directly into WooCommerce's own `{prefix}woocommerce_api_keys` table (WooCommerce has no public "create a key for me" function, only its own admin-UI code path does this) — if the first real "Connect" attempt fails, check there first.

**Getting a pairing code**: log into the web app, go to eCommerce → "Connect automatically with our WordPress plugin" → Generate pairing code (valid 30 minutes).

**Deliberately not built yet**: uninstall doesn't reach into Content Studio to revoke the connection there too (no revoke endpoint exists on the backend yet); no product sync/campaign preview UI inside WordPress (that's the web app's job, per the thin-plugin principle).
