"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { api, type RecommendationConfidence } from "@/lib/api";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";

const CONFIDENCE_STYLES: Record<RecommendationConfidence, string> = {
  low: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  medium: "bg-blue-500/15 text-blue-600 dark:text-blue-400",
  high: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
};

const WINNER_LABELS: Record<string, string> = {
  a: "Campaign A wins",
  b: "Campaign B wins",
  inconclusive: "Inconclusive",
};

function ConfidenceBadge({ confidence }: { confidence: RecommendationConfidence }) {
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium capitalize", CONFIDENCE_STYLES[confidence])}>
      {confidence} confidence
    </span>
  );
}

function IngestMetricsSection() {
  const queryClient = useQueryClient();
  const [planId, setPlanId] = useState("");
  const [ingestingAttemptId, setIngestingAttemptId] = useState<string | null>(null);

  const { data: plans } = useQuery({ queryKey: ["publishing", "plans"], queryFn: api.listPublicationPlans });
  const publishedPlans = plans?.filter((p) => p.status === "published") ?? [];

  const { data: attempts } = useQuery({
    queryKey: ["publishing", "attempts", planId],
    queryFn: () => api.listPublicationAttempts(planId),
    enabled: !!planId,
  });

  const { data: definitions } = useQuery({
    queryKey: ["analytics", "metric-definitions"],
    queryFn: api.listMetricDefinitions,
  });
  const definitionName = (id: string) => definitions?.find((d) => d.id === id)?.name ?? id;

  const [lastIngested, setLastIngested] = useState<Record<string, string>[]>([]);

  const handleIngest = async (attemptId: string) => {
    setIngestingAttemptId(attemptId);
    try {
      const { snapshots } = await api.ingestMetrics(attemptId);
      setLastIngested(
        snapshots.map((s) => ({ metric: definitionName(s.metric_definition_id), value: s.normalized_value })),
      );
      toast.success(`Pulled ${snapshots.length} metric(s) from the platform.`);
      await queryClient.invalidateQueries({ queryKey: ["publishing", "attempts", planId] });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't pull metrics for this post.";
      toast.error(message);
    } finally {
      setIngestingAttemptId(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Pull post metrics</CardTitle>
        <CardDescription>
          Refresh a published post&apos;s metrics from the platform — this is what recommendations are built from.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="plan">Published post</Label>
          <select
            id="plan"
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
            value={planId}
            onChange={(e) => setPlanId(e.target.value)}
          >
            <option value="">Select a published post...</option>
            {publishedPlans.map((p) => (
              <option key={p.id} value={p.id}>
                {p.id.slice(0, 8)} · published {new Date(p.created_at).toLocaleDateString()}
              </option>
            ))}
          </select>
          {publishedPlans.length === 0 && (
            <p className="text-xs text-muted-foreground">
              No published posts yet — schedule and publish something from the Calendar first.
            </p>
          )}
        </div>

        {planId && (
          <ul className="space-y-2">
            {attempts
              ?.filter((a) => a.attempt.status === "succeeded")
              .map((a) => (
                <li
                  key={a.attempt.id}
                  className="flex items-center justify-between rounded-md border border-border p-3 text-sm"
                >
                  <span>Attempt #{a.attempt.attempt_number}</span>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={ingestingAttemptId === a.attempt.id}
                    onClick={() => handleIngest(a.attempt.id)}
                  >
                    {ingestingAttemptId === a.attempt.id ? "Pulling..." : "Pull metrics"}
                  </Button>
                </li>
              ))}
          </ul>
        )}

        {lastIngested.length > 0 && (
          <div className="rounded-md border border-border bg-muted/40 p-3 text-sm">
            <p className="mb-2 text-xs font-medium uppercase text-muted-foreground">Just pulled</p>
            <ul className="space-y-1">
              {lastIngested.map((m, i) => (
                <li key={i} className="flex justify-between">
                  <span className="capitalize">{m.metric.replace(/_/g, " ")}</span>
                  <span className="font-mono">{m.value}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function RecommendationsSection() {
  const queryClient = useQueryClient();
  const [generating, setGenerating] = useState(false);
  const [recordingId, setRecordingId] = useState<string | null>(null);

  const { data: recommendations } = useQuery({
    queryKey: ["analytics", "recommendations"],
    queryFn: api.listRecommendations,
  });

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      await api.generateBestPostingTime();
      toast.success("New recommendation ready.");
      await queryClient.invalidateQueries({ queryKey: ["analytics", "recommendations"] });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "Couldn't generate a recommendation.";
      toast.error(message);
    } finally {
      setGenerating(false);
    }
  };

  const handleOutcome = async (recommendationId: string, outcome: "acted_on" | "dismissed") => {
    setRecordingId(recommendationId);
    try {
      await api.recordRecommendationOutcome(recommendationId, { outcome });
      toast.success(outcome === "acted_on" ? "Marked as acted on." : "Dismissed.");
      await queryClient.invalidateQueries({ queryKey: ["analytics", "recommendations"] });
    } catch {
      toast.error("Couldn't save that.");
    } finally {
      setRecordingId(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Recommendations</CardTitle>
        <CardDescription>
          Best posting time, based on your own historical engagement data — not a guess, and never causal.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Button size="sm" disabled={generating} onClick={handleGenerate}>
          {generating ? "Analyzing..." : "Generate best-posting-time recommendation"}
        </Button>

        {!recommendations || recommendations.length === 0 ? (
          <p className="text-sm text-muted-foreground">No recommendations yet.</p>
        ) : (
          <ul className="space-y-3">
            {recommendations.map((r) => (
              <li key={r.id} className="rounded-md border border-border p-3 text-sm">
                <div className="mb-1 flex items-center justify-between">
                  <p className="font-medium">{r.objective}</p>
                  <ConfidenceBadge confidence={r.confidence} />
                </div>
                <p className="text-muted-foreground">{r.explanation}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Based on {r.sample_size} sample(s) over the last {r.data_window_days} days.
                </p>
                <div className="mt-2 flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={recordingId === r.id}
                    onClick={() => handleOutcome(r.id, "acted_on")}
                  >
                    Acted on
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={recordingId === r.id}
                    onClick={() => handleOutcome(r.id, "dismissed")}
                  >
                    Dismiss
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function CampaignComparisonSection() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [campaignAId, setCampaignAId] = useState("");
  const [campaignBId, setCampaignBId] = useState("");
  const [comparing, setComparing] = useState(false);

  const { data: campaigns } = useQuery({ queryKey: ["marketing", "campaigns"], queryFn: api.listCampaigns });
  const { data: experiments } = useQuery({ queryKey: ["analytics", "experiments"], queryFn: api.listExperiments });

  const campaignName = (id: string) => campaigns?.find((c) => c.id === id)?.name ?? id.slice(0, 8);

  const handleCompare = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !campaignAId || !campaignBId) return;
    setComparing(true);
    try {
      await api.generateCampaignComparison({ name, campaign_a_id: campaignAId, campaign_b_id: campaignBId });
      toast.success("Comparison ready.");
      setName("");
      setCampaignAId("");
      setCampaignBId("");
      await queryClient.invalidateQueries({ queryKey: ["analytics", "experiments"] });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't compare these campaigns.";
      toast.error(message);
    } finally {
      setComparing(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Compare two campaigns</CardTitle>
        <CardDescription>See which campaign performed better on a given metric — no guesswork.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <form className="space-y-4" onSubmit={handleCompare}>
          <div className="space-y-2">
            <Label htmlFor="comparison_name">Comparison name</Label>
            <input
              id="comparison_name"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Summer sale vs. autumn sale"
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="campaign_a">Campaign A</Label>
              <select
                id="campaign_a"
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
                value={campaignAId}
                onChange={(e) => setCampaignAId(e.target.value)}
              >
                <option value="">Select...</option>
                {campaigns?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="campaign_b">Campaign B</Label>
              <select
                id="campaign_b"
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
                value={campaignBId}
                onChange={(e) => setCampaignBId(e.target.value)}
              >
                <option value="">Select...</option>
                {campaigns?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <Button type="submit" size="sm" disabled={comparing || !name || !campaignAId || !campaignBId}>
            {comparing ? "Comparing..." : "Compare"}
          </Button>
        </form>

        {experiments && experiments.length > 0 && (
          <ul className="space-y-3">
            {experiments.map((exp) => (
              <li key={exp.id} className="rounded-md border border-border p-3 text-sm">
                <div className="mb-1 flex items-center justify-between">
                  <p className="font-medium">{exp.name}</p>
                  <span className="text-xs font-medium text-muted-foreground">
                    {WINNER_LABELS[exp.winner] ?? exp.winner}
                  </span>
                </div>
                <p className="text-muted-foreground">{exp.result_summary}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {campaignName(exp.campaign_a_id)} vs. {campaignName(exp.campaign_b_id)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export default function AnalyticsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Analytics</h1>
        <p className="text-muted-foreground">
          Real metrics from your published posts, and honest, data-backed recommendations.
        </p>
      </div>
      <IngestMetricsSection />
      <RecommendationsSection />
      <CampaignComparisonSection />
    </div>
  );
}
