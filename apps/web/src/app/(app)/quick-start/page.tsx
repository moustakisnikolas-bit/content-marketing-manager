"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ProposalSummary } from "@/components/proposal-summary";
import { WooCommerceConnectForm } from "@/components/woocommerce-connect-form";
import { api, type CampaignProposalOut, type Platform } from "@/lib/api";
import { ApiError } from "@/lib/api-client";
import { POST_OAUTH_REDIRECT_KEY } from "@/lib/oauth-redirect";
import { cn } from "@/lib/utils";

type Step = 1 | 2 | 3 | 4;

interface WizardState {
  connectedPlatforms: Platform[];
  connectedStore: boolean;
  goalSlug: string;
  whatToPromote: string;
  mode: "guided" | "autopilot";
}

const AUTOPILOT_MAX_SPEND_CEILING = 20;
const AUTOPILOT_BALANCE_FRACTION = 0.5;

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

// ---------- Step 2: What are you promoting ----------

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
        <CardDescription>In your own words — we&apos;ll turn this into a real plan.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <textarea
          rows={3}
          className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none"
          placeholder="Our new summer candle collection, 20% off this week"
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

// ---------- Step 3: How involved ----------

function InvolvementStep({
  wizard,
  setWizard,
  onContinue,
}: {
  wizard: WizardState;
  setWizard: (update: Partial<WizardState>) => void;
  onContinue: () => void;
}) {
  const canAutopilot = wizard.connectedPlatforms.length > 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>How involved do you want to be?</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <button
            type="button"
            onClick={() => setWizard({ mode: "guided" })}
            className={cn(
              "rounded-md border p-4 text-left text-sm transition-colors",
              wizard.mode === "guided" ? "border-primary bg-primary/10" : "border-border",
            )}
          >
            <p className="font-medium">I want to approve every post</p>
            <p className="mt-1 text-xs text-muted-foreground">We&apos;ll create content and wait for your OK.</p>
          </button>
          <button
            type="button"
            disabled={!canAutopilot}
            onClick={() => canAutopilot && setWizard({ mode: "autopilot" })}
            className={cn(
              "rounded-md border p-4 text-left text-sm transition-colors",
              !canAutopilot && "cursor-not-allowed opacity-50",
              wizard.mode === "autopilot" ? "border-primary bg-primary/10" : "border-border",
            )}
          >
            <p className="font-medium">Just handle it for me</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {canAutopilot
                ? "We'll create and publish automatically, within safe limits."
                : "Connect an account in step 1 to use this."}
            </p>
          </button>
        </div>

        <Button onClick={onContinue}>Continue</Button>
      </CardContent>
    </Card>
  );
}

// ---------- Step 4: Review & Launch ----------

function ReviewLaunchStep({ wizard }: { wizard: WizardState }) {
  const router = useRouter();
  const [proposal, setProposal] = useState<{ brief_id: string; proposal: CampaignProposalOut } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);

  const { data: balance } = useQuery({ queryKey: ["billing", "subscription"], queryFn: api.getSubscriptionBalance });

  const buildProposal = async () => {
    setLoadError(null);
    try {
      const response = await api.createMarketingBrief({
        goal_slug: wizard.goalSlug,
        what_to_promote: wizard.whatToPromote,
        mode: wizard.mode,
        target_platforms: wizard.connectedPlatforms,
      });
      setProposal(response);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Couldn't generate a proposal.");
    }
  };

  // Intentionally mount-only: wizard is finalized by steps 1-3 before this
  // component mounts, and the started-ref guard (not the dep array) is what
  // actually prevents re-runs.
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void buildProposal();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loadError) {
    return (
      <Card>
        <CardContent className="space-y-3 py-6">
          <p className="text-sm text-destructive">{loadError}</p>
          <Button onClick={buildProposal}>Try again</Button>
        </CardContent>
      </Card>
    );
  }

  if (!proposal) {
    return (
      <Card>
        <CardContent className="py-6">
          <p className="text-sm text-muted-foreground">Building your plan...</p>
        </CardContent>
      </Card>
    );
  }

  const estimatedCost = Number(proposal.proposal.estimated_cost);
  const creditBalance = balance ? Number(balance.credit_balance) : null;
  const overBudget = creditBalance !== null && estimatedCost > creditBalance;
  const campaignName = wizard.whatToPromote.trim().slice(0, 40) + (wizard.whatToPromote.trim().length > 40 ? "…" : "");

  const handleLaunch = async () => {
    setLaunching(true);
    let campaignId: string;
    try {
      const result = await api.approveProposal(proposal.proposal.id, { campaign_name: campaignName });
      campaignId = result.campaign_id;
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't create this campaign.";
      toast.error(message);
      setLaunching(false);
      return;
    }

    if (wizard.mode === "autopilot") {
      try {
        const maxSpend = Math.min(
          (creditBalance ?? 0) * AUTOPILOT_BALANCE_FRACTION,
          AUTOPILOT_MAX_SPEND_CEILING,
        ).toFixed(2);
        await api.createAutoPilotPolicy(campaignId, {
          allowed_platforms: wizard.connectedPlatforms,
          max_total_spend: maxSpend,
          blocked_topics: [],
          posting_window_start_hour: 9,
          posting_window_end_hour: 21,
        });
        await api.startAutoPilot(campaignId);
        toast.success("Your campaign is running on Auto-Pilot!");
      } catch {
        toast.success("Campaign created — couldn't set up Auto-Pilot automatically, you can turn it on from this page.");
        router.push(`/campaigns?campaign=${campaignId}`);
        return;
      }
    } else {
      toast.success("Your campaign is live!");
    }
    router.push(`/campaigns?campaign=${campaignId}`);
  };

  return (
    <Card className="border-primary/30">
      <ProposalSummary proposal={proposal.proposal} />
      <CardContent className="space-y-4">
        {overBudget && (
          <p className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            This costs more credits than you have available — add credits or make your request smaller.
          </p>
        )}
        <Button onClick={handleLaunch} disabled={launching || overBudget}>
          {launching ? "Launching..." : "Launch my campaign!"}
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
    goalSlug: "brand_awareness",
    whatToPromote: "",
    mode: "guided",
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
        <p className="text-muted-foreground">Step {step} of 4</p>
      </div>

      {step === 1 && <ConnectStep onContinue={goToStep2} />}
      {step === 2 && <PromoteStep wizard={wizard} setWizard={setWizard} onContinue={() => setStep(3)} />}
      {step === 3 && <InvolvementStep wizard={wizard} setWizard={setWizard} onContinue={() => setStep(4)} />}
      {step === 4 && <ReviewLaunchStep wizard={wizard} />}
    </div>
  );
}
