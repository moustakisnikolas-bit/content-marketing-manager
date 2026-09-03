"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { api, type Platform } from "@/lib/api";
import { ApiError } from "@/lib/api-client";

const PLATFORMS: Platform[] = ["facebook", "instagram", "tiktok", "youtube"];

const STATUS_LABELS: Record<string, string> = {
  draft: "Preparing...",
  pending_approval: "Waiting for your approval",
  approved: "Approved, queued to publish",
  publishing: "Publishing...",
  published: "Published",
  failed: "Failed",
  rejected: "Rejected",
  cancelled: "Cancelled",
};

function ConnectedAccounts() {
  const queryClient = useQueryClient();
  const [connecting, setConnecting] = useState<Platform | null>(null);

  const { data: connections } = useQuery({
    queryKey: ["publishing", "connections"],
    queryFn: api.listConnections,
  });

  const handleConnect = async (platform: Platform) => {
    setConnecting(platform);
    try {
      const { authorization_url } = await api.getAuthorizationUrl(platform);
      const url = new URL(authorization_url);
      if (url.hostname === "stub-oauth.local") {
        // Dev mode: no real Facebook/Instagram/TikTok/YouTube app is
        // registered in this environment, so there's nowhere to redirect
        // the browser to. Simulate what a real OAuth redirect+callback
        // would produce instead — see backend adapters/social_platform/stub.py.
        const state = url.searchParams.get("state")!;
        await api.completeOAuthCallback("dev-simulated-code", state);
      } else {
        window.location.href = authorization_url;
        return;
      }
      toast.success(`Connected ${platform}`);
      await queryClient.invalidateQueries({ queryKey: ["publishing", "connections"] });
    } catch {
      toast.error("Couldn't connect. Please try again.");
    } finally {
      setConnecting(null);
    }
  };

  const connectedPlatforms = new Set(connections?.map((c) => c.connection.platform));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Connected accounts</CardTitle>
        <CardDescription>Connect the platforms you want to publish to.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {PLATFORMS.map((platform) => {
          const connection = connections?.find((c) => c.connection.platform === platform);
          return (
            <div key={platform} className="flex items-center justify-between rounded-md border border-border p-3">
              <div>
                <p className="text-sm font-medium capitalize">{platform}</p>
                {connection ? (
                  <p className="text-xs text-muted-foreground">
                    {connection.connection.external_account_name} &middot;{" "}
                    {connection.capabilities.filter((c) => c.is_available).map((c) => c.capability).join(", ") ||
                      "no capabilities available"}
                  </p>
                ) : (
                  <p className="text-xs text-muted-foreground">Not connected</p>
                )}
              </div>
              <Button
                size="sm"
                variant={connectedPlatforms.has(platform) ? "outline" : "default"}
                disabled={connecting === platform}
                onClick={() => handleConnect(platform)}
              >
                {connectedPlatforms.has(platform) ? "Reconnect" : "Connect"}
              </Button>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function SchedulePost() {
  const queryClient = useQueryClient();
  const [contentItemId, setContentItemId] = useState("");
  const [connectionId, setConnectionId] = useState("");
  const [scheduledFor, setScheduledFor] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const { data: items } = useQuery({ queryKey: ["content", "items"], queryFn: api.listContentItems });
  const { data: connections } = useQuery({ queryKey: ["publishing", "connections"], queryFn: api.listConnections });

  const approvedItems = items?.filter((i) => i.status === "approved") ?? [];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!contentItemId || !connectionId) return;
    setSubmitting(true);
    try {
      await api.createPublicationPlan({
        content_item_id: contentItemId,
        platform_connection_id: connectionId,
        scheduled_for: scheduledFor ? new Date(scheduledFor).toISOString() : undefined,
      });
      toast.success("Scheduled — check Approvals once it's ready for review.");
      setContentItemId("");
      setConnectionId("");
      setScheduledFor("");
      await queryClient.invalidateQueries({ queryKey: ["publishing", "plans"] });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't schedule this post.";
      toast.error(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Schedule a post</CardTitle>
        <CardDescription>Pick approved content and a connected account.</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="content_item">Content</Label>
            <select
              id="content_item"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
              value={contentItemId}
              onChange={(e) => setContentItemId(e.target.value)}
            >
              <option value="">Select approved content...</option>
              {approvedItems.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title} ({item.content_type})
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="connection">Account</Label>
            <select
              id="connection"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
              value={connectionId}
              onChange={(e) => setConnectionId(e.target.value)}
            >
              <option value="">Select a connected account...</option>
              {connections?.map((c) => (
                <option key={c.connection.id} value={c.connection.id}>
                  {c.connection.platform} — {c.connection.external_account_name}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="scheduled_for">When (optional — leave blank to publish as soon as approved)</Label>
            <input
              id="scheduled_for"
              type="datetime-local"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
              value={scheduledFor}
              onChange={(e) => setScheduledFor(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={submitting || !contentItemId || !connectionId}>
            {submitting ? "Scheduling..." : "Schedule"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function ScheduledPosts() {
  const { data: plans } = useQuery({
    queryKey: ["publishing", "plans"],
    queryFn: api.listPublicationPlans,
    refetchInterval: 4000,
  });

  // Already-published plans belong to campaign history, not this
  // upcoming-schedule view — keeping them here just piles up over time
  // with nothing actionable to do about any of them.
  const upcoming = plans?.filter((p) => p.status !== "published") ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Scheduled</CardTitle>
      </CardHeader>
      <CardContent>
        {upcoming.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing scheduled yet.</p>
        ) : (
          <ul className="divide-y divide-border">
            {upcoming.map((plan) => (
              <li key={plan.id} className="flex items-center justify-between py-3 text-sm">
                <span>{STATUS_LABELS[plan.status] ?? plan.status}</span>
                <span className="text-xs text-muted-foreground">
                  {plan.scheduled_for ? new Date(plan.scheduled_for).toLocaleString() : "as soon as approved"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export default function CalendarPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Calendar</h1>
        <p className="text-muted-foreground">Connect accounts and schedule your approved content.</p>
      </div>
      <ConnectedAccounts />
      <SchedulePost />
      <ScheduledPosts />
    </div>
  );
}
