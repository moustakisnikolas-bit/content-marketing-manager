/** sessionStorage key: where /oauth/callback should land after a successful
 * connect. Defaults to /calendar when unset (see oauth/callback/page.tsx) —
 * callers that start the OAuth redirect from somewhere else (e.g.
 * /quick-start) should set this immediately before redirecting to Meta,
 * since a full-page OAuth redirect would otherwise strand the user back on
 * /calendar instead of returning them to where they started. */
export const POST_OAUTH_REDIRECT_KEY = "post-oauth-redirect";
