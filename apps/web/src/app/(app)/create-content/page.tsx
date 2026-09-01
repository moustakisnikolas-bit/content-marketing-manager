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
import { RevisionPreview } from "@/components/revision-preview";
import { api } from "@/lib/api";
import { ApiError } from "@/lib/api-client";

const briefSchema = z.object({
  content_type: z.enum(["text", "image"]),
  title: z.string().min(1, "Give it a short title"),
  brief_text: z.string().min(1, "Tell us what you want created"),
  brand_profile_id: z.string().optional(),
});

type BriefValues = z.infer<typeof briefSchema>;

const STATUS_LABELS: Record<string, string> = {
  pending: "Getting ready...",
  generating: "Creating your draft...",
  quality_gate_failed: "Blocked by a brand rule",
  awaiting_review: "Ready for your review",
  approved: "Approved and packaged",
  rejected: "Rejected",
  failed: "Something went wrong",
};

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
      {job.status === "awaiting_review" && latestRevision && (
        <CardContent className="space-y-4">
          <RevisionPreview
            revision={latestRevision}
            contentType={detail?.item.content_type ?? "text"}
            onEdited={() => queryClient.invalidateQueries({ queryKey: ["content", "items", contentItemId] })}
          />
          <div className="flex gap-2">
            <Button onClick={() => handleReview("approved")} disabled={reviewing}>
              Approve
            </Button>
            <Button variant="outline" onClick={() => handleReview("rejected")} disabled={reviewing}>
              Reject
            </Button>
          </div>
        </CardContent>
      )}
      {job.status === "approved" && (
        <CardContent>
          <p className="text-sm text-primary">Your content is packaged and ready to use.</p>
        </CardContent>
      )}
    </Card>
  );
}

export default function CreateContentPage() {
  const [activeJob, setActiveJob] = useState<{ jobId: string; contentItemId: string } | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<BriefValues>({
    resolver: zodResolver(briefSchema),
    defaultValues: { content_type: "text" },
  });

  const { data: brandProfiles } = useQuery({ queryKey: ["brand-profiles"], queryFn: api.listBrandProfiles });

  const onSubmit = async (values: BriefValues) => {
    try {
      const result = await api.createBrief({
        ...values,
        brand_profile_id: values.brand_profile_id || undefined,
      });
      setActiveJob({ jobId: result.job_id, contentItemId: result.content_item_id });
      reset({ content_type: values.content_type, title: "", brief_text: "", brand_profile_id: values.brand_profile_id });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't start generation. Please try again.";
      toast.error(message);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Create Content</h1>
        <p className="text-muted-foreground">Describe what you need — we&apos;ll draft it for your review.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">New brief</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit(onSubmit)}>
            <div className="space-y-2">
              <Label htmlFor="content_type">What are we creating?</Label>
              <select
                id="content_type"
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
                {...register("content_type")}
              >
                <option value="text">Text (caption, description)</option>
                <option value="image">Image</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="title">Title</Label>
              <Input id="title" placeholder="Summer sale caption" {...register("title")} />
              {errors.title && <p className="text-sm text-destructive">{errors.title.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="brand_profile_id">Brand voice (optional)</Label>
              <select
                id="brand_profile_id"
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
                {...register("brand_profile_id")}
              >
                <option value="">No brand profile</option>
                {brandProfiles?.filter((p) => p.is_active).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="brief_text">Tell us what you want</Label>
              <textarea
                id="brief_text"
                rows={4}
                className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none"
                placeholder="A friendly, upbeat caption announcing our summer sale, 20% off everything"
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
