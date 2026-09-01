"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api-client";
import { RevisionPreview } from "@/components/revision-preview";
import { SelectableList } from "@/components/selectable-list";
import { api, type CampaignPlanItemOut } from "@/lib/api";
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

function PlanItemReviewPanel({
  campaignId,
  item,
  hasPrevious,
  hasNext,
  onNavigate,
  onDecided,
  onClose,
}: {
  campaignId: string;
  item: CampaignPlanItemOut;
  hasPrevious: boolean;
  hasNext: boolean;
  onNavigate: (direction: "previous" | "next") => void;
  onDecided: () => void;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [instructions, setInstructions] = useState("");

  const { data: detail } = useQuery({
    queryKey: ["content", "items", item.content_item_id],
    queryFn: () => api.getContentItem(item.content_item_id!),
    enabled: !!item.content_item_id,
  });
  const latestRevision = detail?.revisions.at(-1);

  const handleReview = async (decision: "approved" | "rejected") => {
    if (!latestRevision || !item.generation_job_id) return;
    setBusy(true);
    try {
      await api.reviewGenerationJob(item.generation_job_id, {
        decision,
        revision_id: latestRevision.id,
        comment: decision === "rejected" ? instructions.trim() || undefined : undefined,
      });
      toast.success(
        decision === "approved" ? "Approved" : "Rejected — a new attempt is being generated with your feedback",
      );
      await queryClient.invalidateQueries({ queryKey: ["marketing", "campaign", campaignId] });
      onDecided();
    } catch {
      toast.error("Couldn't submit review.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="border-primary/30">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="text-base">{item.title}</CardTitle>
            <CardDescription>
              {item.content_type} {item.target_platform && `· ${item.target_platform}`}
            </CardDescription>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {detail && latestRevision ? (
          <RevisionPreview
            revision={latestRevision}
            contentType={item.content_type}
            onEdited={() => queryClient.invalidateQueries({ queryKey: ["content", "items"] })}
          />
        ) : (
          <p className="text-sm text-muted-foreground">Loading preview...</p>
        )}

        <div className="space-y-1">
          <Label htmlFor={`instructions-${item.id}`}>What should change? (optional, used if you reject)</Label>
          <textarea
            id={`instructions-${item.id}`}
            rows={2}
            className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none"
            placeholder="e.g. make the tone more playful, mention the discount code"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
          />
        </div>

        <div className="flex items-center justify-between pt-2">
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" disabled={!hasPrevious} onClick={() => onNavigate("previous")}>
              ← Previous
            </Button>
            <Button variant="ghost" size="sm" disabled={!hasNext} onClick={() => onNavigate("next")}>
              Next →
            </Button>
          </div>
          <div className="flex gap-2">
            <Button size="sm" disabled={busy || !latestRevision} onClick={() => handleReview("approved")}>
              Approve
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={busy || !latestRevision}
              onClick={() => handleReview("rejected")}
            >
              Reject
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function CampaignDetail({ campaignId, onCancelled }: { campaignId: string; onCancelled: () => void }) {
  const queryClient = useQueryClient();
  const [startingItemId, setStartingItemId] = useState<string | null>(null);
  const [removingItemId, setRemovingItemId] = useState<string | null>(null);
  const [reviewingId, setReviewingId] = useState<string | null>(null);
  const [refreshingPhotos, setRefreshingPhotos] = useState(false);
  const [cancelling, setCancelling] = useState(false);

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
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't start this item.");
    } finally {
      setStartingItemId(null);
    }
  };

  const handleRefreshPhotos = async () => {
    setRefreshingPhotos(true);
    try {
      const stores = await api.listStores();
      await Promise.all(stores.map((s) => api.syncStoreProducts(s.connection.id)));
      toast.success("Product photos refreshed from the store");
      await queryClient.invalidateQueries({ queryKey: ["marketing", "campaign", campaignId] });
      await queryClient.invalidateQueries({ queryKey: ["commerce", "products"] });
    } catch {
      toast.error("Couldn't refresh product photos.");
    } finally {
      setRefreshingPhotos(false);
    }
  };

  const handleCancelCampaign = async () => {
    if (!window.confirm("Remove this campaign? Its content and history stay recorded, but it's taken off your list.")) {
      return;
    }
    setCancelling(true);
    try {
      await api.cancelCampaign(campaignId);
      toast.success("Campaign removed");
      await queryClient.invalidateQueries({ queryKey: ["marketing", "campaigns"] });
      onCancelled();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't remove this campaign.");
    } finally {
      setCancelling(false);
    }
  };

  const handleRemoveItem = async (itemId: string) => {
    if (!window.confirm("Remove this product from the campaign?")) return;
    setRemovingItemId(itemId);
    try {
      await api.removePlanItem(campaignId, itemId);
      toast.success("Removed from campaign");
      if (reviewingId === itemId) setReviewingId(null);
      await queryClient.invalidateQueries({ queryKey: ["marketing", "campaign", campaignId] });
    } catch {
      toast.error("Couldn't remove this item.");
    } finally {
      setRemovingItemId(null);
    }
  };

  if (!detail) return null;

  const reviewableItems = detail.plan_items.filter((i) => i.status === "awaiting_review");
  const reviewingIndex = reviewableItems.findIndex((i) => i.id === reviewingId);
  const reviewingItem = reviewingIndex >= 0 ? reviewableItems[reviewingIndex] : null;

  const handleNavigate = (direction: "previous" | "next") => {
    const nextIndex = reviewingIndex + (direction === "next" ? 1 : -1);
    if (nextIndex >= 0 && nextIndex < reviewableItems.length) {
      setReviewingId(reviewableItems[nextIndex].id);
    }
  };

  const handleDecided = () => {
    // Picks the next item from the list as it stood *before* this decision
    // — the item just decided will drop out of reviewableItems once the
    // campaign query refetches, so index-chasing after that would skip one.
    const nextIndex = reviewingIndex + 1 < reviewableItems.length ? reviewingIndex + 1 : reviewingIndex - 1;
    const next = nextIndex >= 0 && nextIndex < reviewableItems.length ? reviewableItems[nextIndex] : null;
    setReviewingId(next && next.id !== reviewingId ? next.id : null);
  };

  return (
    <div className="space-y-6">
      {reviewingItem && (
        <PlanItemReviewPanel
          key={reviewingItem.id}
          campaignId={campaignId}
          item={reviewingItem}
          hasPrevious={reviewingIndex > 0}
          hasNext={reviewingIndex < reviewableItems.length - 1}
          onNavigate={handleNavigate}
          onDecided={handleDecided}
          onClose={() => setReviewingId(null)}
        />
      )}

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-2">
            <div>
              <CardTitle className="text-base">{detail.campaign.name}</CardTitle>
              <CardDescription>
                Status: {detail.campaign.status} &middot; Spent: {Number(detail.campaign.total_spent).toFixed(2)}{" "}
                credits
              </CardDescription>
            </div>
            <div className="flex gap-2">
              {detail.plan_items.some((i) => i.product_id) && (
                <Button size="sm" variant="outline" disabled={refreshingPhotos} onClick={handleRefreshPhotos}>
                  {refreshingPhotos ? "Refreshing..." : "Refresh product photos"}
                </Button>
              )}
              <Button size="sm" variant="ghost" disabled={cancelling} onClick={handleCancelCampaign}>
                {cancelling ? "Removing..." : "Remove campaign"}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2">
            {detail.plan_items.map((item) => {
              const reviewable = item.status === "awaiting_review";
              return (
                <li
                  key={item.id}
                  onClick={() => reviewable && setReviewingId(item.id)}
                  className={cn(
                    "flex items-center justify-between rounded-md border p-3 text-sm transition-colors",
                    reviewable ? "cursor-pointer hover:bg-muted" : "border-border",
                    reviewingId === item.id ? "border-primary bg-primary/10" : "border-border",
                  )}
                >
                  <div>
                    <p className="font-medium">{item.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {PLAN_ITEM_STATUS_LABELS[item.status] ?? item.status}
                      {item.target_platform && ` · ${item.target_platform}`}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {item.status === "pending" && (
                      <Button
                        size="sm"
                        disabled={startingItemId === item.id}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleStartItem(item.id);
                        }}
                      >
                        Start
                      </Button>
                    )}
                    {item.status !== "cancelled" && item.status !== "published" && (
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={removingItemId === item.id}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleRemoveItem(item.id);
                        }}
                      >
                        Remove
                      </Button>
                    )}
                    {reviewable && <span className="text-xs font-medium text-primary">Review →</span>}
                  </div>
                </li>
              );
            })}
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

  const visibleCampaigns = (campaigns ?? []).filter((c) => c.status !== "cancelled");

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Campaigns</h1>
          <p className="text-muted-foreground">Everything you&apos;ve planned with the AI Marketing Manager.</p>
        </div>
        <Button render={<Link href="/quick-start" />} nativeButton={false}>
          New campaign
        </Button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">All campaigns</CardTitle>
          </CardHeader>
          <CardContent>
            <SelectableList
              items={visibleCampaigns.map((c) => ({ id: c.id, primary: c.name, secondary: c.status }))}
              selectedId={selectedId}
              onSelect={setSelectedId}
              emptyMessage="No campaigns yet."
            />
          </CardContent>
        </Card>

        {selectedId ? (
          <CampaignDetail campaignId={selectedId} onCancelled={() => setSelectedId(null)} />
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
