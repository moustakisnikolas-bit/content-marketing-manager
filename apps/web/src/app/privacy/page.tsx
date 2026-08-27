import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Privacy Policy — AI Content Studio",
  description: "How AI Content Studio collects, uses, and protects your data, including data deletion instructions.",
};

export default function PrivacyPolicyPage() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-12">
      <h1 className="text-3xl font-bold tracking-tight">Privacy Policy</h1>
      <p className="mt-2 text-sm text-muted-foreground">Last updated: August 27, 2026</p>

      <div className="mt-8 space-y-8 text-sm leading-relaxed">
        <section>
          <h2 className="text-lg font-semibold">1. Who we are</h2>
          <p className="mt-2">
            AI Content Studio ("we", "us", "our") is a marketing content platform that helps store owners plan,
            generate, and publish marketing content, and connect their store and social media accounts for that
            purpose.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold">2. Information we collect</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>Account information you provide directly: your email address, display name, and password (stored
              as a salted hash, never in plain text).</li>
            <li>Store data from any e-commerce platform (e.g. WooCommerce) you connect: product catalog, order and
              webhook events relevant to marketing content, and API credentials needed to access them.</li>
            <li>Social platform data from any account (e.g. Facebook, Instagram) you connect via OAuth: your Pages
              or Business accounts you authorize us to access, and the access tokens needed to publish content on
              your behalf.</li>
            <li>Content you create or request through the platform, and metadata about how it performs once
              published (e.g. impressions, engagement).</li>
          </ul>
        </section>

        <section>
          <h2 className="text-lg font-semibold">3. How we use this information</h2>
          <p className="mt-2">We use the information above only to operate the platform's core features:</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>Generating marketing content on your behalf using third-party AI providers (currently OpenRouter),
              which receive only the specific prompts/content needed for a given generation request — not your
              account credentials or store data wholesale.</li>
            <li>Publishing content you approve to the social accounts you've connected, via each platform's own
              official API (e.g. Meta's Graph API).</li>
            <li>Syncing your store's product catalog so it can be referenced when generating product-related
              content.</li>
            <li>Operating your account: authentication, billing, and support.</li>
          </ul>
          <p className="mt-2">We do not sell your data to third parties, and we do not use your store or social
            data to train AI models.</p>
        </section>

        <section>
          <h2 className="text-lg font-semibold">4. How we protect your information</h2>
          <p className="mt-2">
            Third-party credentials (store API keys, social platform access tokens) are never stored in plain
            text — they're sealed in a dedicated secrets store and only ever decrypted in-memory at the moment
            they're needed to make an authorized request on your behalf. Passwords are stored as salted hashes,
            never in plain text or in a reversible form.
          </p>
        </section>

        <section id="data-deletion">
          <h2 className="text-lg font-semibold">5. Data deletion</h2>
          <p className="mt-2">You can request deletion of your data at any time in either of these ways:</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li><strong>Disconnect a specific store or social account</strong> from within the app (eCommerce or
              Publishing settings) — this immediately deletes that connection's stored credentials and synced
              data.</li>
            <li><strong>Request full account deletion</strong> by contacting us (see Section 7) — we will delete
              your account, all connected-store and social-account data, and all generated content associated
              with it.</li>
          </ul>
          <p className="mt-2">
            If you connected a Facebook or Instagram account and remove our app's access from your own Facebook
            Settings &rarr; Business Integrations, we're notified automatically and delete the corresponding
            stored access token.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold">6. Third-party services</h2>
          <p className="mt-2">
            We integrate with third-party services to provide our features, each governed by its own privacy
            policy: e-commerce platforms you connect (e.g. WooCommerce, on your own store's domain), Meta
            Platforms, Inc. (Facebook/Instagram, for publishing), and OpenRouter (AI content generation).
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold">7. Contact</h2>
          <p className="mt-2">
            For privacy questions or to request data deletion, contact us at{" "}
            <a className="underline" href="mailto:privacy@example.com">privacy@example.com</a>.
          </p>
        </section>
      </div>
    </div>
  );
}
