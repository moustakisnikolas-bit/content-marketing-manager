"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ProductPicker } from "@/components/product-picker";
import { SelectableList } from "@/components/selectable-list";
import { WooCommerceConnectForm } from "@/components/woocommerce-connect-form";
import { api, type Platform } from "@/lib/api";
import { ApiError } from "@/lib/api-client";
import { POST_OAUTH_REDIRECT_KEY } from "@/lib/oauth-redirect";
import { cn } from "@/lib/utils";

type Step = 1 | 2 | 3 | 4 | 5;

interface WizardState {
  connectedPlatforms: Platform[];
  connectedStore: boolean;
  campaignId: string | null;
  goalSlug: string;
  whatToPromote: string;
  selectedProductIds: string[];
}

// ---------- Step 1: Connect ----------

function ConnectStep({ onContinue }: { onContinue: () => void }) {
  const queryClient = useQueryClient();
  const [connecting, setConnecting] = useState(false);

  const { data: connections } = useQuery({ queryKey: ["publishing", "connections"], queryFn: api.listConnections });
  const { data: stores } = useQuery({ queryKey: ["commerce", "stores"], queryFn: api.listStores });

  const metaConnected = connections?.some(
    (c) => c.connection.platform === "facebook" || c.connection.platform === "instagram",
  );
  const storeConnected = (stores?.length ?? 0) > 0;

  const handleConnectMeta = async () => {
    setConnecting(true);
    try {
      const { authorization_url } = await api.getAuthorizationUrl("facebook");
      const url = new URL(authorization_url);
      if (url.hostname === "stub-oauth.local") {
        // Dev mode: no real Meta app registered — simulate the round trip
        // instead of redirecting, same fallback as calendar/page.tsx.
        const state = url.searchParams.get("state")!;
        await api.completeOAuthCallback("dev-simulated-code", state);
        toast.success("Connected Facebook");
        await queryClient.invalidateQueries({ queryKey: ["publishing", "connections"] });
      } else {
        // Full-page redirect to Meta — /oauth/callback needs to know to
        // send the browser back here afterward, not to /calendar.
        sessionStorage.setItem(POST_OAUTH_REDIRECT_KEY, "/quick-start");
        window.location.href = authorization_url;
        return;
      }
    } catch {
      toast.error("Couldn't connect. Please try again.");
    } finally {
      setConnecting(false);
    }
  };

  const handleStoreConnected = async () => {
    await queryClient.invalidateQueries({ queryKey: ["commerce", "stores"] });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Connect your accounts</CardTitle>
        <CardDescription>Optional — you can always do this later.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-md border border-border p-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium">Facebook &amp; Instagram</p>
            {metaConnected ? (
              <span className="text-sm font-medium text-primary">✓ Connected</span>
            ) : (
              <Button size="sm" disabled={connecting} onClick={handleConnectMeta}>
                {connecting ? "Connecting..." : "Connect"}
              </Button>
            )}
          </div>
        </div>

        {storeConnected ? (
          <div className="rounded-md border border-border p-3">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">Online store</p>
              <span className="text-sm font-medium text-primary">✓ Connected</span>
            </div>
          </div>
        ) : (
          <WooCommerceConnectForm onConnected={handleStoreConnected} />
        )}

        <div className="flex items-center justify-between pt-2">
          <Button variant="ghost" size="sm" onClick={onContinue}>
            Skip for now
          </Button>
          <Button onClick={onContinue}>Continue</Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------- Step 2: Campaign ----------

function CampaignStep({
  wizard,
  setWizard,
  onContinue,
}: {
  wizard: WizardState;
  setWizard: (update: Partial<WizardState>) => void;
  onContinue: () => void;
}) {
  const { data: campaigns } = useQuery({ queryKey: ["marketing", "campaigns"], queryFn: api.listCampaigns });
  const activeCampaigns = (campaigns ?? []).filter((c) => c.status !== "completed" && c.status !== "cancelled");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Add to a campaign</CardTitle>
        <CardDescription>Pick an existing campaign to add to, or start a new one.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <button
          type="button"
          onClick={() => setWizard({ campaignId: null })}
          className={cn(
            "block w-full rounded-md border p-3 text-left text-sm transition-colors",
            wizard.campaignId === null ? "border-primary bg-primary/10" : "border-border hover:bg-muted",
          )}
        >
          <p className="font-medium">Start a new campaign</p>
        </button>

        {activeCampaigns.length > 0 && (
          <div>
            <p className="mb-2 text-sm font-medium">Or add to an existing campaign</p>
            <SelectableList
              items={activeCampaigns.map((c) => ({ id: c.id, primary: c.name, secondary: c.status }))}
              selectedId={wizard.campaignId}
              onSelect={(id) => setWizard({ campaignId: id })}
              emptyMessage="No active campaigns."
            />
          </div>
        )}

        <Button onClick={onContinue}>Continue</Button>
      </CardContent>
    </Card>
  );
}

// ---------- Step 3: What are you promoting ----------

function PromoteStep({
  wizard,
  setWizard,
  onContinue,
}: {
  wizard: WizardState;
  setWizard: (update: Partial<WizardState>) => void;
  onContinue: () => void;
}) {
  const { data: goals } = useQuery({ queryKey: ["marketing", "goals"], queryFn: api.listMarketingGoals });

  return (
    <Card>
      <CardHeader>
        <CardTitle>What are you promoting?</CardTitle>
        <CardDescription>
          In your own words — this becomes the shared prompt for every product you pick next, both for the
          writing and the generated image.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <textarea
          rows={3}
          className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none"
          placeholder="20% off this week, bright summer photography"
          value={wizard.whatToPromote}
          onChange={(e) => setWizard({ whatToPromote: e.target.value })}
        />

        <div>
          <p className="mb-2 text-sm font-medium">What&apos;s the goal?</p>
          <div className="grid gap-2 sm:grid-cols-2">
            {goals?.map((goal) => (
              <button
                key={goal.slug}
                type="button"
                onClick={() => setWizard({ goalSlug: goal.slug })}
                className={cn(
                  "rounded-md border p-3 text-left text-sm transition-colors",
                  wizard.goalSlug === goal.slug ? "border-primary bg-primary/10" : "border-border",
                )}
              >
                <p className="font-medium">{goal.label}</p>
                <p className="text-xs text-muted-foreground">{goal.description}</p>
              </button>
            ))}
          </div>
        </div>

        <Button onClick={onContinue} disabled={!wizard.whatToPromote.trim()}>
          Continue
        </Button>
      </CardContent>
    </Card>
  );
}

// ---------- Step 4: Products ----------

function ProductsStep({
  wizard,
  setWizard,
  onContinue,
}: {
  wizard: WizardState;
  setWizard: (update: Partial<WizardState>) => void;
  onContinue: () => void;
}) {
  const { data: products } = useQuery({ queryKey: ["commerce", "products"], queryFn: api.listProducts });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Which products?</CardTitle>
        <CardDescription>We&apos;ll generate one post (and a matching image) for each product you pick.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!products || products.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No products yet — connect a store and sync from the eCommerce page.
          </p>
        ) : (
          <ProductPicker
            products={products}
            selectedIds={wizard.selectedProductIds}
            onChange={(ids) => setWizard({ selectedProductIds: ids })}
          />
        )}
        <Button onClick={onContinue} disabled={wizard.selectedProductIds.length === 0}>
          Continue
        </Button>
      </CardContent>
    </Card>
  );
}

// ---------- Step 5: Review & Launch ----------

function ReviewLaunchStep({ wizard }: { wizard: WizardState }) {
  const router = useRouter();
  const [launching, setLaunching] = useState(false);
  const { data: products } = useQuery({ queryKey: ["commerce", "products"], queryFn: api.listProducts });

  const selectedProducts = (products ?? []).filter((p) => wizard.selectedProductIds.includes(p.id));

  const handleLaunch = async () => {
    setLaunching(true);
    try {
      const result = await api.bulkGenerateProductCampaign({
        product_ids: wizard.selectedProductIds,
        description: wizard.whatToPromote,
        goal_slug: wizard.goalSlug,
        target_platforms: wizard.connectedPlatforms,
        campaign_id: wizard.campaignId,
        generate_images: true,
      });
      if (result.failed_product_ids.length > 0) {
        toast.error(`${result.failed_product_ids.length} product(s) couldn't be included.`);
      }
      toast.success(`Started ${result.started_count} item(s) — they'll appear on the campaign page as they finish.`);
      router.push(`/campaigns?campaign=${result.campaign_id}`);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't launch this campaign.";
      toast.error(message);
      setLaunching(false);
    }
  };

  return (
    <Card className="border-primary/30">
      <CardHeader>
        <CardTitle>Review &amp; launch</CardTitle>
        <CardDescription>
          {wizard.campaignId ? "Adding these to your existing campaign." : "Starting a new campaign."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <p className="text-sm font-medium">What you&apos;re promoting</p>
          <p className="mt-1 text-sm text-muted-foreground">{wizard.whatToPromote}</p>
        </div>
        <div>
          <p className="text-sm font-medium">{selectedProducts.length} product(s)</p>
          <ul className="mt-1 max-h-48 space-y-1 overflow-y-auto text-sm text-muted-foreground">
            {selectedProducts.map((p) => (
              <li key={p.id}>{p.title}</li>
            ))}
          </ul>
        </div>
        <Button onClick={handleLaunch} disabled={launching}>
          {launching ? "Launching..." : "Launch"}
        </Button>
      </CardContent>
    </Card>
  );
}

// ---------- Main wizard ----------

export default function QuickStartPage() {
  const [step, setStep] = useState<Step>(1);
  const [wizard, setWizardState] = useState<WizardState>({
    connectedPlatforms: [],
    connectedStore: false,
    campaignId: null,
    goalSlug: "brand_awareness",
    whatToPromote: "",
    selectedProductIds: [],
  });
  const { data: connections } = useQuery({ queryKey: ["publishing", "connections"], queryFn: api.listConnections });
  const { data: stores } = useQuery({ queryKey: ["commerce", "stores"], queryFn: api.listStores });

  const setWizard = (update: Partial<WizardState>) => setWizardState((prev) => ({ ...prev, ...update }));

  const goToStep2 = () => {
    const connectedPlatforms = (connections?.map((c) => c.connection.platform) ?? []).filter(
      (p): p is Platform => p === "facebook" || p === "instagram",
    );
    const connectedStore = (stores?.length ?? 0) > 0;
    setWizard({
      connectedPlatforms,
      connectedStore,
      goalSlug: connectedStore ? "more_sales" : "brand_awareness",
    });
    setStep(2);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Quick Start</h1>
        <p className="text-muted-foreground">Step {step} of 5</p>
      </div>

      {step === 1 && <ConnectStep onContinue={goToStep2} />}
      {step === 2 && <CampaignStep wizard={wizard} setWizard={setWizard} onContinue={() => setStep(3)} />}
      {step === 3 && <PromoteStep wizard={wizard} setWizard={setWizard} onContinue={() => setStep(4)} />}
      {step === 4 && <ProductsStep wizard={wizard} setWizard={setWizard} onContinue={() => setStep(5)} />}
      {step === 5 && <ReviewLaunchStep wizard={wizard} />}
    </div>
  );
}
