"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Bookmark, Eye, Heart, MessageCircle, Send, Share2, ThumbsUp, Trash2 } from "lucide-react";
import { Suspense, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api-client";
import { RevisionPreview } from "@/components/revision-preview";
import { SelectableList } from "@/components/selectable-list";
import { api, type CampaignPlanItemOut, type PublishApprovedResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

const PLAN_ITEM_STATUS_LABELS: Record<string, string> = {
  pending: "Not started",
  generating: "Creating...",
  awaiting_review: "Ready for review",
  approved: "Approved",
  scheduled: "Scheduled",
  published: "Published",
  failed: "Failed",
  skipped: "Skipped by Auto-Pilot",
  cancelled: "Cancelled",
};

function AutoPilotSection({ campaignId }: { campaignId: string }) {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);

  const { data: policy } = useQuery({
    queryKey: ["marketing", "autopilot-policy", campaignId],
    queryFn: () => api.getAutoPilotPolicy(campaignId),
    retry: false,
  });

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

  // TEMPORARY: Auto-Pilot is disabled workspace-wide — it was generating
  // and publishing image plan items as text posts (AutoPilotService.run_item()
  // ignores plan_item.content_type). Starting is blocked server-side too;
  // this just makes the reason visible instead of a raw 500. The kill
  // switch stays available on an existing policy as a safety action.
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Auto-Pilot</CardTitle>
        <CardDescription>
          Temporarily disabled — it was generating and publishing image items as text posts. Use manual review
          below instead for now.
        </CardDescription>
      </CardHeader>
      {policy && !policy.kill_switch_active && (
        <CardContent>
          <Button variant="outline" onClick={handleHalt} disabled={busy}>
            Activate kill switch on this campaign&apos;s policy
          </Button>
        </CardContent>
      )}
    </Card>
  );
}

function PlanItemReviewPanel({
  campaignId,
  items,
  hasPrevious,
  hasNext,
  onNavigate,
  onDecided,
  onClose,
  onDelete,
}: {
  campaignId: string;
  // Usually one item. When a text+image pair for the same product/platform
  // both reached awaiting_review together, this holds both — reviewed and
  // decided as a single combined post (see the "combined review" plan).
  items: CampaignPlanItemOut[];
  hasPrevious: boolean;
  hasNext: boolean;
  onNavigate: (direction: "previous" | "next") => void;
  onDecided: () => void;
  onClose: () => void;
  onDelete: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [instructions, setInstructions] = useState("");
  const isImageLike = (i: CampaignPlanItemOut) => i.content_type === "image" || i.content_type === "story";
  const imageItem = items.find(isImageLike) ?? null;
  const [promptDraft, setPromptDraft] = useState(imageItem?.brief_text ?? "");
  const [regenerating, setRegenerating] = useState(false);
  const [primary, secondary] = items;

  const primaryQuery = useQuery({
    queryKey: ["content", "items", primary.content_item_id],
    queryFn: () => api.getContentItem(primary.content_item_id!),
    enabled: !!primary.content_item_id,
  });
  const secondaryQuery = useQuery({
    queryKey: ["content", "items", secondary?.content_item_id],
    queryFn: () => api.getContentItem(secondary?.content_item_id ?? ""),
    enabled: !!secondary?.content_item_id,
  });
  const primaryRevision = primaryQuery.data?.revisions.at(-1);
  const secondaryRevision = secondary ? secondaryQuery.data?.revisions.at(-1) : undefined;
  const ready = !!primaryRevision && (!secondary || !!secondaryRevision);

  const handleReview = async (decision: "approved" | "rejected") => {
    const targets = [
      { item: primary, revision: primaryRevision },
      ...(secondary ? [{ item: secondary, revision: secondaryRevision }] : []),
    ].filter((t): t is { item: CampaignPlanItemOut; revision: NonNullable<typeof t.revision> } =>
      !!t.item.generation_job_id && !!t.revision,
    );
    if (targets.length === 0) return;
    setBusy(true);
    try {
      await Promise.all(
        targets.map((t) =>
          api.reviewGenerationJob(t.item.generation_job_id!, {
            decision,
            revision_id: t.revision.id,
            comment: decision === "rejected" ? instructions.trim() || undefined : undefined,
          }),
        ),
      );
      toast.success(
        decision === "approved"
          ? `Approved${targets.length > 1 ? " both" : ""}`
          : `Rejected${targets.length > 1 ? " — both parts are being regenerated" : " — a new attempt is being generated"} with your feedback`,
      );
      await queryClient.invalidateQueries({ queryKey: ["marketing", "campaign", campaignId] });
      onDecided();
    } catch {
      toast.error("Couldn't submit review.");
    } finally {
      setBusy(false);
    }
  };

  const handleRegenerate = async () => {
    if (!imageItem?.generation_job_id || !promptDraft.trim()) return;
    setRegenerating(true);
    try {
      await api.regenerateGenerationJob(imageItem.generation_job_id, promptDraft.trim());
      toast.success("Recreating the image with the updated prompt — check back shortly.");
      await queryClient.invalidateQueries({ queryKey: ["marketing", "campaign", campaignId] });
      onDecided();
    } catch {
      toast.error("Couldn't recreate the image.");
    } finally {
      setRegenerating(false);
    }
  };

  const revisionFor = (item: CampaignPlanItemOut) => (item.id === primary.id ? primaryRevision : secondaryRevision);
  const queryFor = (item: CampaignPlanItemOut) => (item.id === primary.id ? primaryQuery : secondaryQuery);

  const handleDelete = async () => {
    if (
      !window.confirm(
        secondary
          ? "Delete both of these permanently? This can't be undone — any generated image or text stays saved, it just won't show here anymore."
          : "Delete this item permanently? This can't be undone — any generated image or text stays saved, it just won't show here anymore.",
      )
    ) {
      return;
    }
    setDeleting(true);
    try {
      await onDelete();
    } finally {
      setDeleting(false);
    }
  };

  const anyBusy = busy || regenerating || deleting;

  return (
    <Card className="border-primary/30">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="text-base">{primary.title}</CardTitle>
            <CardDescription>
              {items.map((i) => i.content_type).join(" + ")} {primary.target_platform && `· ${primary.target_platform}`}
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <Button variant="destructive" size="sm" disabled={anyBusy} onClick={handleDelete}>
              {deleting ? "Deleting..." : secondary ? "Delete both" : "Delete"}
            </Button>
            <Button variant="ghost" size="sm" onClick={onClose}>
              Close
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {items.map((i) => {
          const revision = revisionFor(i);
          const query = queryFor(i);
          return (
            <div key={i.id} className="space-y-1">
              {query.data && revision ? (
                <RevisionPreview
                  revision={revision}
                  // A Story plan item's underlying generated content is still an
                  // image (see prepare_story_image_generation in commerce/service.py) —
                  // only CampaignPlanItem.content_type says "story".
                  contentType={i.content_type === "story" ? "image" : i.content_type}
                  onEdited={() => queryClient.invalidateQueries({ queryKey: ["content", "items"] })}
                />
              ) : (
                <p className="text-sm text-muted-foreground">Loading preview...</p>
              )}
            </div>
          );
        })}

        {imageItem && (
          <div className="space-y-1 rounded-md border border-border p-3">
            <Label htmlFor={`prompt-${imageItem.id}`}>Image prompt</Label>
            <textarea
              id={`prompt-${imageItem.id}`}
              rows={3}
              className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none"
              value={promptDraft}
              onChange={(e) => setPromptDraft(e.target.value)}
            />
            <div className="flex items-center justify-between pt-1">
              <p className="text-xs text-muted-foreground">
                Edit the prompt and recreate the image — doesn&apos;t count as a reject.
              </p>
              <Button
                size="sm"
                variant="outline"
                disabled={anyBusy || !promptDraft.trim()}
                onClick={handleRegenerate}
              >
                {regenerating ? "Recreating..." : "Recreate image"}
              </Button>
            </div>
          </div>
        )}

        <div className="space-y-1">
          <Label htmlFor={`instructions-${primary.id}`}>What should change? (optional, used if you reject)</Label>
          <textarea
            id={`instructions-${primary.id}`}
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
            <Button size="sm" disabled={anyBusy || !ready} onClick={() => handleReview("approved")}>
              {secondary ? "Approve both" : "Approve"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={anyBusy || !ready}
              onClick={() => handleReview("rejected")}
            >
              {secondary ? "Reject both" : "Reject"}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// Styled to read like an actual Facebook/Instagram post, not a plain data
// row — the whole point is letting you judge how the real thing will
// look (image + caption together) before it goes out, not just its title.
function SocialPostMockup({
  platform, pageName, imageUrl, caption, scheduledFor,
}: {
  platform: string | null;
  pageName: string;
  imageUrl: string | undefined;
  caption: string;
  scheduledFor: string;
}) {
  const isInstagram = platform === "instagram";
  const timeLabel = new Date(scheduledFor).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });

  return (
    <div className="w-full max-w-sm overflow-hidden rounded-lg border border-border bg-card shadow-sm">
      <div className="flex items-center gap-2 p-3">
        <div
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold text-white",
            isInstagram ? "bg-gradient-to-br from-amber-400 via-pink-500 to-purple-600" : "bg-[#1877F2]",
          )}
        >
          {pageName.charAt(0).toUpperCase()}
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{pageName}</p>
          <p className="text-xs text-muted-foreground">
            {timeLabel} · {isInstagram ? "Instagram" : "Facebook"}
          </p>
        </div>
      </div>

      {/* Facebook shows the caption above the image; Instagram below. */}
      {!isInstagram && caption && <p className="whitespace-pre-wrap px-3 pb-3 text-sm">{caption}</p>}

      {imageUrl ? (
        // eslint-disable-next-line @next/next/no-img-element -- presigned storage URL, not a local/optimizable asset
        <img src={imageUrl} alt="Post preview" className="aspect-square w-full object-cover" />
      ) : (
        <div className="flex aspect-square w-full items-center justify-center bg-muted text-xs text-muted-foreground">
          Text-only post — no image
        </div>
      )}

      <div className="flex items-center gap-4 px-3 py-2 text-muted-foreground">
        {isInstagram ? (
          <>
            <Heart className="h-5 w-5" />
            <MessageCircle className="h-5 w-5" />
            <Send className="h-5 w-5" />
            <Bookmark className="ml-auto h-5 w-5" />
          </>
        ) : (
          <>
            <ThumbsUp className="h-5 w-5" />
            <MessageCircle className="h-5 w-5" />
            <Share2 className="h-5 w-5" />
          </>
        )}
      </div>

      {isInstagram && caption && (
        <p className="whitespace-pre-wrap px-3 pb-3 text-sm">
          <span className="font-semibold">{pageName}</span> {caption}
        </p>
      )}
    </div>
  );
}

function SocialStoryMockup({ pageName, imageUrl }: { pageName: string; imageUrl: string | undefined }) {
  return (
    <div className="w-full max-w-[220px]">
      <p className="mb-1 text-center text-xs font-medium text-muted-foreground">
        Story preview — regenerated from this photo after publishing
      </p>
      <div className="relative aspect-[9/16] w-full overflow-hidden rounded-lg border border-border bg-black">
        <div className="absolute inset-x-2 top-2 h-0.5 rounded-full bg-white/40" />
        <div className="absolute left-2 right-2 top-4 z-10 flex items-center gap-1.5">
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-gradient-to-br from-amber-400 via-pink-500 to-purple-600 text-[10px] font-semibold text-white">
            {pageName.charAt(0).toUpperCase()}
          </div>
          <p className="truncate text-xs font-medium text-white drop-shadow">{pageName}</p>
        </div>
        {imageUrl ? (
          // eslint-disable-next-line @next/next/no-img-element -- presigned storage URL, not a local/optimizable asset
          <img src={imageUrl} alt="Story preview" className="h-full w-full object-cover opacity-80" />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-xs text-white/60">No image yet</div>
        )}
      </div>
    </div>
  );
}

// One entry in the pre-publish review: fetches the actual generated image
// + caption for this plan item (and its paired text/image sibling) so the
// preview shows the real post, not just a title and a timestamp.
function PublishPreviewItem({
  pageName, planItem, textItem, scheduledFor, willCreateStory,
}: {
  pageName: string;
  planItem: CampaignPlanItemOut;
  textItem: CampaignPlanItemOut | null;
  scheduledFor: string;
  willCreateStory: boolean;
}) {
  const isImagePost = planItem.content_type === "image";
  // A text-only product (no paired image) publishes planItem itself as the
  // post — its own content is the caption. Otherwise the caption comes
  // from the paired text item; planItem is the image being published.
  const captionItem = isImagePost ? textItem : planItem;

  const imageQuery = useQuery({
    queryKey: ["content", "items", planItem.content_item_id],
    queryFn: () => api.getContentItem(planItem.content_item_id!),
    enabled: isImagePost && !!planItem.content_item_id,
  });
  const captionQuery = useQuery({
    queryKey: ["content", "items", captionItem?.content_item_id],
    queryFn: () => api.getContentItem(captionItem?.content_item_id ?? ""),
    enabled: !!captionItem?.content_item_id,
  });
  const imageRevision = imageQuery.data?.revisions.at(-1);
  const assetQuery = useQuery({
    queryKey: ["assets", imageRevision?.asset_id, "download-url"],
    queryFn: () => api.getAssetDownloadUrl(imageRevision!.asset_id!),
    enabled: !!imageRevision?.asset_id,
  });
  const caption = captionQuery.data?.revisions.at(-1)?.text_body ?? planItem.title;

  return (
    <div className="rounded-md border border-border p-4">
      <p className="mb-1 text-sm font-medium">{planItem.title}</p>
      <p className="mb-3 text-xs text-muted-foreground">
        Scheduled for {new Date(scheduledFor).toLocaleString()}
        {willCreateStory && " · a Story will also be created for review"}
      </p>
      <div className="flex flex-wrap items-start gap-6">
        <SocialPostMockup
          platform={planItem.target_platform}
          pageName={pageName}
          imageUrl={isImagePost ? assetQuery.data?.url : undefined}
          caption={caption}
          scheduledFor={scheduledFor}
        />
        {willCreateStory && <SocialStoryMockup pageName={pageName} imageUrl={assetQuery.data?.url} />}
      </div>
    </div>
  );
}

function CampaignDetail({ campaignId, onCancelled }: { campaignId: string; onCancelled: () => void }) {
  const queryClient = useQueryClient();
  const [startingItemId, setStartingItemId] = useState<string | null>(null);
  const [removingItemId, setRemovingItemId] = useState<string | null>(null);
  const [reviewingId, setReviewingId] = useState<string | null>(null);
  const [refreshingPhotos, setRefreshingPhotos] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [publishPreview, setPublishPreview] = useState<PublishApprovedResponse | null>(null);
  const [confirmingPublish, setConfirmingPublish] = useState(false);
  const [itemsPerWeek, setItemsPerWeek] = useState(7);

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

  const handlePreviewPublish = async () => {
    setPublishing(true);
    try {
      const preview = await api.publishApprovedCampaign(campaignId, { dryRun: true, itemsPerWeek });
      if (preview.published.length === 0 && preview.skipped.length === 0) {
        toast.info("Nothing ready to publish yet — approve some content first.");
      } else {
        setPublishPreview(preview);
      }
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't preview what would be published.");
    } finally {
      setPublishing(false);
    }
  };

  const handleConfirmPublish = async () => {
    setConfirmingPublish(true);
    try {
      const result = await api.publishApprovedCampaign(campaignId, { itemsPerWeek });
      const storyCount = result.published.filter((p) => p.will_create_story).length;
      toast.success(
        `Published ${result.published.length} post(s)` +
          (storyCount > 0 ? ` (${storyCount} with a Story queued for review)` : "") +
          (result.skipped.length > 0 ? ` — skipped ${result.skipped.length}: ${result.skipped.map((s) => s.reason).join("; ")}` : ""),
      );
      setPublishPreview(null);
      await queryClient.invalidateQueries({ queryKey: ["marketing", "campaign", campaignId] });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't publish approved content.");
    } finally {
      setConfirmingPublish(false);
    }
  };

  const handleRemoveItem = async (itemId: string) => {
    if (!window.confirm("Delete this item permanently? This can't be undone — any generated image or text stays saved, it just won't show here anymore.")) {
      return;
    }
    setRemovingItemId(itemId);
    try {
      await api.removePlanItem(campaignId, itemId);
      toast.success("Deleted");
      if (reviewingId === itemId) setReviewingId(null);
      await queryClient.invalidateQueries({ queryKey: ["marketing", "campaign", campaignId] });
    } catch {
      toast.error("Couldn't remove this item.");
    } finally {
      setRemovingItemId(null);
    }
  };

  // Delete straight from the review panel — confirmation already happened
  // there, so this just does the work (one or two items, for a combined
  // text+image review group) and closes the panel.
  const handleDeleteReviewGroup = async (items: CampaignPlanItemOut[]) => {
    try {
      await Promise.all(items.map((i) => api.removePlanItem(campaignId, i.id)));
      toast.success(items.length > 1 ? "Deleted both" : "Deleted");
      setReviewingId(null);
      await queryClient.invalidateQueries({ queryKey: ["marketing", "campaign", campaignId] });
    } catch {
      toast.error("Couldn't delete this item.");
    }
  };

  if (!detail) return null;

  const reviewableItems = detail.plan_items.filter((i) => i.status === "awaiting_review");

  // A text+image pair generated together for the same product/platform
  // reviews as one combined post once both sides are ready; anything else
  // (a lone item still waiting on its pair, a Story, a non-product item)
  // still reviews standalone. See the "combined review" plan.
  const reviewGroups: CampaignPlanItemOut[][] = [];
  const consumed = new Set<string>();
  for (const item of reviewableItems) {
    if (consumed.has(item.id)) continue;
    if ((item.content_type === "text" || item.content_type === "image") && item.product_id) {
      const pairType = item.content_type === "text" ? "image" : "text";
      const pair = reviewableItems.find(
        (other) =>
          !consumed.has(other.id) &&
          other.id !== item.id &&
          other.content_type === pairType &&
          other.product_id === item.product_id &&
          other.target_platform === item.target_platform,
      );
      if (pair) {
        consumed.add(item.id);
        consumed.add(pair.id);
        reviewGroups.push(item.content_type === "text" ? [item, pair] : [pair, item]);
        continue;
      }
    }
    consumed.add(item.id);
    reviewGroups.push([item]);
  }

  const reviewingIndex = reviewGroups.findIndex((g) => g.some((i) => i.id === reviewingId));
  const reviewingGroup = reviewingIndex >= 0 ? reviewGroups[reviewingIndex] : null;

  const handleNavigate = (direction: "previous" | "next") => {
    const nextIndex = reviewingIndex + (direction === "next" ? 1 : -1);
    if (nextIndex >= 0 && nextIndex < reviewGroups.length) {
      setReviewingId(reviewGroups[nextIndex][0].id);
    }
  };

  const handleDecided = () => {
    // Picks the next group from the list as it stood *before* this decision
    // — the group just decided will drop out of reviewGroups once the
    // campaign query refetches, so index-chasing after that would skip one.
    const nextIndex = reviewingIndex + 1 < reviewGroups.length ? reviewingIndex + 1 : reviewingIndex - 1;
    const next = nextIndex >= 0 && nextIndex < reviewGroups.length ? reviewGroups[nextIndex] : null;
    const nextId = next?.[0]?.id ?? null;
    setReviewingId(nextId && nextId !== reviewingId ? nextId : null);
  };

  const titleForPlanItem = (planItemId: string) =>
    detail.plan_items.find((i) => i.id === planItemId)?.title ?? "Untitled item";

  // Approved (or already-published) items are done — sink them to the
  // bottom so items that still need attention stay up top. Array.sort is
  // stable, so relative order within each group is otherwise unchanged.
  const isDecided = (item: CampaignPlanItemOut) =>
    item.status === "approved" || item.status === "published" || item.publication_plan_id !== null;
  const sortedPlanItems = [...detail.plan_items].sort(
    (a, b) => Number(isDecided(a)) - Number(isDecided(b)),
  );

  return (
    <div className="space-y-6">
      {publishPreview && (
        <Card className="border-primary/30">
          <CardHeader>
            <CardTitle className="text-base">Review before publishing</CardTitle>
            <CardDescription>
              Nothing has gone out yet — these are the real times each post would be scheduled for, paced at{" "}
              {itemsPerWeek} per week using your best-performing days and times. Anything beyond that spreads into
              future weeks at the same pace.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {publishPreview.published.length > 0 && (
              <div className="space-y-3">
                {publishPreview.published.map((p) => {
                  const planItem = detail.plan_items.find((i) => i.id === p.plan_item_id);
                  if (!planItem) return null;
                  const textItem =
                    planItem.content_type === "image"
                      ? (detail.plan_items.find(
                          (i) =>
                            i.content_type === "text" &&
                            i.product_id === planItem.product_id &&
                            i.target_platform === planItem.target_platform,
                        ) ?? null)
                      : null;
                  return (
                    <PublishPreviewItem
                      key={p.plan_item_id}
                      pageName={detail.campaign.name}
                      planItem={planItem}
                      textItem={textItem}
                      scheduledFor={p.scheduled_for}
                      willCreateStory={p.will_create_story}
                    />
                  );
                })}
              </div>
            )}
            {publishPreview.skipped.length > 0 && (
              <ul className="space-y-2">
                {publishPreview.skipped.map((s) => (
                  <li key={s.plan_item_id} className="rounded-md border border-border p-3 text-sm text-muted-foreground">
                    <p className="font-medium">{titleForPlanItem(s.plan_item_id)}</p>
                    <p className="text-xs">Skipped — {s.reason}</p>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex justify-end gap-2 pt-2">
              <Button size="sm" variant="ghost" disabled={confirmingPublish} onClick={() => setPublishPreview(null)}>
                Cancel
              </Button>
              <Button
                size="sm"
                disabled={confirmingPublish || publishPreview.published.length === 0}
                onClick={handleConfirmPublish}
              >
                {confirmingPublish ? "Publishing..." : `Confirm & publish ${publishPreview.published.length} post(s)`}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {reviewingGroup && (
        <PlanItemReviewPanel
          key={reviewingGroup.map((i) => i.id).join("-")}
          campaignId={campaignId}
          items={reviewingGroup}
          hasPrevious={reviewingIndex > 0}
          hasNext={reviewingIndex < reviewGroups.length - 1}
          onNavigate={handleNavigate}
          onDecided={handleDecided}
          onClose={() => setReviewingId(null)}
          onDelete={() => handleDeleteReviewGroup(reviewingGroup)}
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
                <>
                  <Button size="sm" variant="outline" disabled={refreshingPhotos} onClick={handleRefreshPhotos}>
                    {refreshingPhotos ? "Refreshing..." : "Refresh product photos"}
                  </Button>
                  <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    Posts/week
                    <input
                      type="number"
                      min={1}
                      max={28}
                      value={itemsPerWeek}
                      onChange={(e) => setItemsPerWeek(Math.max(1, Math.min(28, Number(e.target.value) || 1)))}
                      className="h-8 w-14 rounded-md border border-input bg-background px-2 text-sm text-foreground"
                    />
                  </label>
                  <Button size="sm" disabled={publishing} onClick={handlePreviewPublish}>
                    {publishing ? "Checking..." : "Publish approved"}
                  </Button>
                </>
              )}
              <Button size="sm" variant="ghost" disabled={cancelling} onClick={handleCancelCampaign}>
                {cancelling ? "Removing..." : "Remove campaign"}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2">
            {sortedPlanItems.map((item) => {
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
                    {reviewable && (
                      <Button
                        size="icon-sm"
                        variant="outline"
                        aria-label="Review"
                        title="Review"
                        onClick={(e) => {
                          e.stopPropagation();
                          setReviewingId(item.id);
                        }}
                      >
                        <Eye />
                      </Button>
                    )}
                    {item.status !== "cancelled" && item.status !== "published" && (
                      <Button
                        size="icon-sm"
                        variant="destructive"
                        aria-label="Remove"
                        title="Remove"
                        disabled={removingItemId === item.id}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleRemoveItem(item.id);
                        }}
                      >
                        <Trash2 />
                      </Button>
                    )}
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
