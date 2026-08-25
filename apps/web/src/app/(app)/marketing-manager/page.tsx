"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { ProposalSummary } from "@/components/proposal-summary";
import { api, type CampaignProposalOut } from "@/lib/api";
import { ApiError } from "@/lib/api-client";

const PLATFORM_OPTIONS = ["facebook", "instagram", "tiktok", "youtube"];
const MODE_OPTIONS: { value: "manual" | "guided" | "autopilot"; label: string; description: string }[] = [
  { value: "guided", label: "Guided", description: "We create content, you review and approve each piece." },
  { value: "manual", label: "Manual", description: "We plan it, you decide when to create each piece." },
  { value: "autopilot", label: "Auto-Pilot", description: "We create and publish within limits you set — no per-post approval." },
];

function ProposalReview({ proposal }: { proposal: CampaignProposalOut }) {
  const router = useRouter();
  const [campaignName, setCampaignName] = useState("");
  const [approving, setApproving] = useState(false);

  const handleApprove = async () => {
    if (!campaignName.trim()) {
      toast.error("Give your campaign a name first.");
      return;
    }
    setApproving(true);
    try {
      const result = await api.approveProposal(proposal.id, { campaign_name: campaignName });
      toast.success("Campaign created");
      router.push(`/campaigns?campaign=${result.campaign_id}`);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't approve this proposal.";
      toast.error(message);
    } finally {
      setApproving(false);
    }
  };

  return (
    <Card className="border-primary/30">
      <ProposalSummary proposal={proposal} />
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="campaign_name">Campaign name</Label>
          <input
            id="campaign_name"
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
            placeholder="Summer Sale Push"
            value={campaignName}
            onChange={(e) => setCampaignName(e.target.value)}
          />
        </div>
        <Button onClick={handleApprove} disabled={approving}>
          {approving ? "Creating..." : "Approve & create campaign"}
        </Button>
      </CardContent>
    </Card>
  );
}

export default function MarketingManagerPage() {
  const { data: goals } = useQuery({ queryKey: ["marketing", "goals"], queryFn: api.listMarketingGoals });

  const [goalSlug, setGoalSlug] = useState("");
  const [whatToPromote, setWhatToPromote] = useState("");
  const [mode, setMode] = useState<"manual" | "guided" | "autopilot">("guided");
  const [platforms, setPlatforms] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ brief_id: string; proposal: CampaignProposalOut } | null>(null);

  const togglePlatform = (platform: string) => {
    setPlatforms((prev) => (prev.includes(platform) ? prev.filter((p) => p !== platform) : [...prev, platform]));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!goalSlug || !whatToPromote.trim()) return;
    setSubmitting(true);
    try {
      const response = await api.createMarketingBrief({
        goal_slug: goalSlug,
        what_to_promote: whatToPromote,
        mode,
        target_platforms: platforms,
      });
      setResult(response);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't generate a proposal.";
      toast.error(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">AI Marketing Manager</h1>
        <p className="text-muted-foreground">Tell us your goal — we&apos;ll propose a plan.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">What would you like to achieve?</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="space-y-2">
              <Label htmlFor="goal">Goal</Label>
              <select
                id="goal"
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
                value={goalSlug}
                onChange={(e) => setGoalSlug(e.target.value)}
              >
                <option value="">Select a goal...</option>
                {goals?.map((g) => (
                  <option key={g.id} value={g.slug}>
                    {g.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="what_to_promote">What are you promoting?</Label>
              <textarea
                id="what_to_promote"
                rows={3}
                className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none"
                placeholder="Our new summer collection, 20% off this week"
                value={whatToPromote}
                onChange={(e) => setWhatToPromote(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>How hands-on do you want to be?</Label>
              <div className="grid gap-2 sm:grid-cols-3">
                {MODE_OPTIONS.map((option) => (
                  <button
                    type="button"
                    key={option.value}
                    onClick={() => setMode(option.value)}
                    className={`rounded-md border p-3 text-left text-sm transition-colors ${
                      mode === option.value ? "border-primary bg-primary/10" : "border-border"
                    }`}
                  >
                    <p className="font-medium">{option.label}</p>
                    <p className="text-xs text-muted-foreground">{option.description}</p>
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <Label>Platforms</Label>
              <div className="flex flex-wrap gap-2">
                {PLATFORM_OPTIONS.map((platform) => (
                  <button
                    type="button"
                    key={platform}
                    onClick={() => togglePlatform(platform)}
                    className={`rounded-full border px-3 py-1 text-sm capitalize transition-colors ${
                      platforms.includes(platform) ? "border-primary bg-primary/10" : "border-border"
                    }`}
                  >
                    {platform}
                  </button>
                ))}
              </div>
            </div>
            <Button type="submit" disabled={submitting || !goalSlug || !whatToPromote.trim()}>
              {submitting ? "Building your plan..." : "Get a plan"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {result && <ProposalReview proposal={result.proposal} />}
    </div>
  );
}
