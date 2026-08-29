import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Terms of Service — AI Content Studio",
  description: "The terms that govern use of AI Content Studio.",
};

export default function TermsOfServicePage() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-12">
      <h1 className="text-3xl font-bold tracking-tight">Terms of Service</h1>
      <p className="mt-2 text-sm text-muted-foreground">Last updated: August 29, 2026</p>

      <div className="mt-8 space-y-8 text-sm leading-relaxed">
        <section>
          <h2 className="text-lg font-semibold">1. Acceptance of terms</h2>
          <p className="mt-2">
            By creating an account or otherwise using AI Content Studio ("the Service"), you agree to these
            Terms of Service. If you don't agree, don't use the Service.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold">2. What the Service does</h2>
          <p className="mt-2">
            AI Content Studio helps store owners plan, generate, and publish marketing content. It lets you
            connect an e-commerce platform (e.g. WooCommerce) and social media accounts (e.g. Facebook,
            Instagram) so the Service can read your product catalog and publish approved content on your
            behalf, using third-party AI providers to generate that content.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold">3. Your account</h2>
          <p className="mt-2">
            You're responsible for the accuracy of the information you provide, for keeping your login
            credentials secure, and for all activity that happens under your account. You must be authorized
            to connect any store or social account you link to the Service.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold">4. Connected third-party accounts</h2>
          <p className="mt-2">
            When you connect a store or social account, you authorize the Service to access and act on that
            account within the scope of the permissions you grant (e.g. reading products, publishing posts).
            You can revoke this access at any time by disconnecting the account in the Service or removing its
            access from the third-party platform directly. Your use of those third-party platforms remains
            subject to their own terms.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold">5. Content and publishing</h2>
          <p className="mt-2">
            The Service generates content suggestions using AI. You're responsible for reviewing content
            before it's published and for ensuring it complies with applicable law and the policies of the
            platforms you publish to. You retain ownership of content you create or approve through the
            Service.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold">6. Acceptable use</h2>
          <p className="mt-2">
            Don't use the Service to publish unlawful, infringing, or deceptive content, to circumvent any
            third-party platform's terms or rate limits, or to access accounts or data you're not authorized
            to access.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold">7. Plans and usage limits</h2>
          <p className="mt-2">
            The Service may offer different plans with different usage limits (e.g. number of generations or
            connected accounts). We'll let you know if you're approaching or have reached a limit on your
            plan.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold">8. Termination</h2>
          <p className="mt-2">
            You may stop using the Service and delete your account at any time. We may suspend or terminate
            access to the Service for violations of these terms.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold">9. Disclaimer and limitation of liability</h2>
          <p className="mt-2">
            The Service is provided "as is," without warranties of any kind. AI-generated content may contain
            errors — review it before publishing. To the extent permitted by law, we're not liable for
            indirect, incidental, or consequential damages arising from use of the Service.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold">10. Changes to these terms</h2>
          <p className="mt-2">
            We may update these terms from time to time. Continued use of the Service after an update
            constitutes acceptance of the revised terms.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold">11. Contact</h2>
          <p className="mt-2">
            Questions about these terms? Contact us at{" "}
            <a className="underline" href="mailto:privacy@example.com">privacy@example.com</a>.
          </p>
        </section>
      </div>
    </div>
  );
}
