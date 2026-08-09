"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const PLAN_ITEM_STATUS_LABELS: Record<string, string> = {
  pending: "Not started",
  generating: "Creating...",
  awaiting_review: "Ready for review",
  scheduled: "Scheduled",
  published: "Published",
  failed: "Failed",
  skipped: "Skipped by Auto-Pilot",
  cancelled: "Cancelled",
};

function AutoPilotSection({ campaignId }: { campaignId: string }) {
  const queryClient = useQueryClient();
  const [platforms, setPlatforms] = useState("facebook");
  const [maxSpend, setMaxSpend] = useState("10");
  const [blockedTopics, setBlockedTopics] = useState("");
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);

  const { data: policy, isError } = useQuery({
    queryKey: ["marketing", "autopilot-policy", campaignId],
    queryFn: () => api.getAutoPilotPolicy(campaignId),
    retry: false,
  });

  const handleCreatePolicy = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    try {
      await api.createAutoPilotPolicy(campaignId, {
        allowed_platforms: platforms.split(",").map((p) => p.trim()).filter(Boolean),
        max_total_spend: maxSpend,
        blocked_topics: blockedTopics.split(",").map((t) => t.trim()).filter(Boolean),
        posting_window_start_hour: 0,
        posting_window_end_hour: 23,
      });
      toast.success("Auto-Pilot policy set");
      await queryClient.invalidateQueries({ queryKey: ["marketing", "autopilot-policy", campaignId] });
    } catch {
      toast.error("Couldn't save the policy.");
    } finally {
      setCreating(false);
    }
  };

  const handleStart = async () => {
    setBusy(true);
    try {
      await api.startAutoPilot(campaignId);
      toast.success("Auto-Pilot started");
      await queryClient.invalidateQueries({ queryKey: ["marketing", "campaign", campaignId] });
    } catch {
      toast.error("Couldn't start Auto-Pilot.");
    } finally {
      setBusy(false);
    }
  };

  const handleHalt = async () => {
    setBusy(true);
    try {
      await api.haltAutoPilot(campaignId);
      toast.success("Kill switch activated — no further posts will go out.");
      await queryClient.invalidateQueries({ queryKey: ["marketing", "autopilot-policy", campaignId] });
    } catch {
      toast.error("Couldn't activate the kill switch.");
    } finally {
      setBusy(false);
    }
  };

  if (isError || !policy) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Auto-Pilot</CardTitle>
          <CardDescription>Set limits before letting Auto-Pilot run this campaign on its own.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleCreatePolicy}>
            <div className="space-y-2">
              <Label htmlFor="allowed_platforms">Allowed platforms (comma-separated)</Label>
              <input
                id="allowed_platforms"
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
                value={platforms}
                onChange={(e) => setPlatforms(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="max_spend">Maximum total spend (credits)</Label>
              <input
                id="max_spend"
                type="number"
                step="0.01"
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
                value={maxSpend}
                onChange={(e) => setMaxSpend(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="blocked_topics">Blocked topics (comma-separated, optional)</Label>
              <input
                id="blocked_topics"
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
                value={blockedTopics}
                onChange={(e) => setBlockedTopics(e.target.value)}
              />
            </div>
            <Button type="submit" disabled={creating}>
              {creating ? "Saving..." : "Save policy"}
            </Button>
          </form>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Auto-Pilot</CardTitle>
        <CardDescription>
          Allowed: {policy.allowed_platforms.join(", ") || "none"} &middot; Limit: {policy.max_total_spend} credits
          {policy.kill_switch_active && " · Kill switch is ACTIVE"}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex gap-2">
        <Button onClick={handleStart} disabled={busy || policy.kill_switch_active}>
          Start Auto-Pilot
        </Button>
        <Button variant="outline" onClick={handleHalt} disabled={busy || policy.kill_switch_active}>
          Kill switch
        </Button>
      </CardContent>
    </Card>
  );
}

function CampaignDetail({ campaignId }: { campaignId: string }) {
  const queryClient = useQueryClient();
  const [startingItemId, setStartingItemId] = useState<string | null>(null);

  const { data: detail } = useQuery({
    queryKey: ["marketing", "campaign", campaignId],
    queryFn: () => api.getCampaign(campaignId),
    refetchInterval: 4000,
  });

  const handleStartItem = async (itemId: string) => {
    setStartingItemId(itemId);
    try {
      await api.startPlanItem(campaignId, itemId);
      toast.success("Started");
      await queryClient.invalidateQueries({ queryKey: ["marketing", "campaign", campaignId] });
    } catch {
      toast.error("Couldn't start this item.");
    } finally {
      setStartingItemId(null);
    }
  };

  if (!detail) return null;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{detail.campaign.name}</CardTitle>
          <CardDescription>
            Status: {detail.campaign.status} &middot; Spent: {Number(detail.campaign.total_spent).toFixed(2)} credits
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2">
            {detail.plan_items.map((item) => (
              <li key={item.id} className="flex items-center justify-between rounded-md border border-border p-3 text-sm">
                <div>
                  <p className="font-medium">{item.title}</p>
                  <p className="text-xs text-muted-foreground">
                    {PLAN_ITEM_STATUS_LABELS[item.status] ?? item.status}
                    {item.target_platform && ` · ${item.target_platform}`}
                  </p>
                </div>
                {item.status === "pending" && (
                  <Button size="sm" disabled={startingItemId === item.id} onClick={() => handleStartItem(item.id)}>
                    Start
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <AutoPilotSection campaignId={campaignId} />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Why we did what we did</CardTitle>
          <CardDescription>Every decision this campaign made, explained.</CardDescription>
        </CardHeader>
        <CardContent>
          {detail.decisions.length === 0 ? (
            <p className="text-sm text-muted-foreground">No decisions recorded yet.</p>
          ) : (
            <ul className="space-y-2">
              {detail.decisions.map((d, i) => (
                <li key={i} className="rounded-md border border-border p-3 text-sm">
                  <p className="text-xs font-medium uppercase text-muted-foreground">{d.decision_type.replace(/_/g, " ")}</p>
                  <p>{d.explanation}</p>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function CampaignsPageInner() {
  const searchParams = useSearchParams();
  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get("campaign"));

  const { data: campaigns } = useQuery({ queryKey: ["marketing", "campaigns"], queryFn: api.listCampaigns });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Campaigns</h1>
        <p className="text-muted-foreground">Everything you&apos;ve planned with the AI Marketing Manager.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">All campaigns</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {!campaigns || campaigns.length === 0 ? (
              <p className="text-sm text-muted-foreground">No campaigns yet.</p>
            ) : (
              campaigns.map((c) => (
                <button
                  key={c.id}
                  onClick={() => setSelectedId(c.id)}
                  className={cn(
                    "block w-full rounded-md px-3 py-2 text-left text-sm transition-colors",
                    selectedId === c.id ? "bg-accent text-accent-foreground" : "hover:bg-muted",
                  )}
                >
                  <p className="font-medium">{c.name}</p>
                  <p className="text-xs text-muted-foreground">{c.status}</p>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        {selectedId ? (
          <CampaignDetail campaignId={selectedId} />
        ) : (
          <Card>
            <CardContent className="pt-6">
              <p className="text-sm text-muted-foreground">Select a campaign to see details.</p>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

export default function CampaignsPage() {
  return (
    <Suspense fallback={null}>
      <CampaignsPageInner />
    </Suspense>
  );
}
