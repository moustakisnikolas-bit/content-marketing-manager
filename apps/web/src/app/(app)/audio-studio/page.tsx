"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { ApiError } from "@/lib/api-client";

const briefSchema = z.object({
  title: z.string().min(1, "Give it a short title"),
  brief_text: z.string().min(1, "Describe the voiceover or music you want"),
});

type BriefValues = z.infer<typeof briefSchema>;

const STATUS_LABELS: Record<string, string> = {
  pending: "Getting ready...",
  generating: "Generating your audio...",
  quality_gate_failed: "Blocked by a brand rule",
  awaiting_review: "Ready for your review",
  approved: "Approved and packaged",
  rejected: "Rejected",
  failed: "Something went wrong",
};

function AudioPlayer({ assetId }: { assetId: string }) {
  const { data } = useQuery({
    queryKey: ["assets", assetId, "download-url"],
    queryFn: () => api.getAssetDownloadUrl(assetId),
  });

  if (!data) return <p className="text-sm text-muted-foreground">Loading audio...</p>;

  return <audio controls className="w-full" src={data.url} />;
}

function JobTracker({ jobId, contentItemId }: { jobId: string; contentItemId: string }) {
  const queryClient = useQueryClient();
  const [reviewing, setReviewing] = useState(false);

  const { data: job } = useQuery({
    queryKey: ["content", "jobs", jobId],
    queryFn: () => api.getGenerationJob(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      const settled = status === "approved" || status === "rejected" || status === "failed" || status === "quality_gate_failed";
      return settled ? false : 2000;
    },
  });

  const { data: detail } = useQuery({
    queryKey: ["content", "items", contentItemId],
    queryFn: () => api.getContentItem(contentItemId),
    enabled: job?.status === "awaiting_review" || job?.status === "approved",
  });

  const latestRevision = detail?.revisions.at(-1);

  const handleReview = async (decision: "approved" | "rejected") => {
    if (!latestRevision) return;
    setReviewing(true);
    try {
      await api.reviewGenerationJob(jobId, { decision, revision_id: latestRevision.id });
      toast.success(decision === "approved" ? "Approved" : "Rejected");
      await queryClient.invalidateQueries({ queryKey: ["content", "jobs", jobId] });
    } catch {
      toast.error("Couldn't submit your review. Please try again.");
    } finally {
      setReviewing(false);
    }
  };

  if (!job) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{STATUS_LABELS[job.status] ?? job.status}</CardTitle>
        {job.failure_reason && <CardDescription>{job.failure_reason}</CardDescription>}
      </CardHeader>
      {(job.status === "awaiting_review" || job.status === "approved") && latestRevision?.asset_id && (
        <CardContent className="space-y-4">
          <AudioPlayer assetId={latestRevision.asset_id} />
          {job.status === "awaiting_review" && (
            <div className="flex gap-2">
              <Button onClick={() => handleReview("approved")} disabled={reviewing}>
                Approve
              </Button>
              <Button variant="outline" onClick={() => handleReview("rejected")} disabled={reviewing}>
                Reject
              </Button>
            </div>
          )}
          {job.status === "approved" && <p className="text-sm text-primary">Your audio is packaged and ready to use.</p>}
        </CardContent>
      )}
    </Card>
  );
}

export default function AudioStudioPage() {
  const [activeJob, setActiveJob] = useState<{ jobId: string; contentItemId: string } | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<BriefValues>({ resolver: zodResolver(briefSchema) });

  const onSubmit = async (values: BriefValues) => {
    try {
      const result = await api.createBrief({ ...values, content_type: "audio" });
      setActiveJob({ jobId: result.job_id, contentItemId: result.content_item_id });
      reset({ title: "", brief_text: "" });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't start generation. Please try again.";
      toast.error(message);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Audio Studio</h1>
        <p className="text-muted-foreground">Generate voiceover or music — listen, then approve or reject.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">New audio brief</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit(onSubmit)}>
            <div className="space-y-2">
              <Label htmlFor="title">Title</Label>
              <Input id="title" placeholder="Summer sale voiceover" {...register("title")} />
              {errors.title && <p className="text-sm text-destructive">{errors.title.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="brief_text">Describe what you want</Label>
              <textarea
                id="brief_text"
                rows={4}
                className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none"
                placeholder="An upbeat 15-second voiceover announcing our summer sale, friendly female voice"
                {...register("brief_text")}
              />
              {errors.brief_text && <p className="text-sm text-destructive">{errors.brief_text.message}</p>}
            </div>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Starting..." : "Generate"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {activeJob && <JobTracker jobId={activeJob.jobId} contentItemId={activeJob.contentItemId} />}
    </div>
  );
}
