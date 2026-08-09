"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";

function ContentApprovals() {
  const queryClient = useQueryClient();
  const [busyJobId, setBusyJobId] = useState<string | null>(null);

  const { data: jobs } = useQuery({ queryKey: ["content", "jobs"], queryFn: api.listGenerationJobs });
  const { data: items } = useQuery({ queryKey: ["content", "items"], queryFn: api.listContentItems });
  const pending = jobs?.filter((j) => j.status === "awaiting_review") ?? [];

  const handleReview = async (jobId: string, decision: "approved" | "rejected") => {
    setBusyJobId(jobId);
    try {
      const detail = await api.getContentItem(jobs!.find((j) => j.id === jobId)!.content_item_id);
      const latestRevision = detail.revisions.at(-1);
      if (!latestRevision) return;
      await api.reviewGenerationJob(jobId, { decision, revision_id: latestRevision.id });
      toast.success(decision === "approved" ? "Approved" : "Rejected");
      await queryClient.invalidateQueries({ queryKey: ["content", "jobs"] });
    } catch {
      toast.error("Couldn't submit review.");
    } finally {
      setBusyJobId(null);
    }
  };

  if (pending.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Content ready for review</CardTitle>
        <CardDescription>{pending.length} waiting</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {pending.map((job) => {
          const item = items?.find((i) => i.id === job.content_item_id);
          return (
            <div key={job.id} className="flex items-center justify-between rounded-md border border-border p-3">
              <span className="text-sm font-medium">{item?.title ?? "Content"}</span>
              <div className="flex gap-2">
                <Button size="sm" disabled={busyJobId === job.id} onClick={() => handleReview(job.id, "approved")}>
                  Approve
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busyJobId === job.id}
                  onClick={() => handleReview(job.id, "rejected")}
                >
                  Reject
                </Button>
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function ToolApprovals() {
  const queryClient = useQueryClient();
  const [busyApprovalId, setBusyApprovalId] = useState<string | null>(null);

  const { data: approvals } = useQuery({
    queryKey: ["governance", "approvals", "pending"],
    queryFn: api.listPendingToolApprovals,
  });
  const { data: tools } = useQuery({ queryKey: ["governance", "tools"], queryFn: api.listGovernanceTools });
  const toolName = (toolId: string) => tools?.find((t) => t.id === toolId)?.name ?? "AI tool";

  const handleApprove = async (approvalId: string) => {
    setBusyApprovalId(approvalId);
    try {
      await api.approveToolApproval(approvalId);
      toast.success("Approved — the agent can now run this once.");
      await queryClient.invalidateQueries({ queryKey: ["governance", "approvals", "pending"] });
    } catch {
      toast.error("Couldn't approve this.");
    } finally {
      setBusyApprovalId(null);
    }
  };

  if (!approvals || approvals.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">AI agent actions waiting for approval</CardTitle>
        <CardDescription>{approvals.length} high-impact action(s) need your explicit, one-time go-ahead.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {approvals.map((approval) => (
          <div key={approval.id} className="flex items-center justify-between rounded-md border border-border p-3">
            <div>
              <p className="text-sm font-medium capitalize">{toolName(approval.tool_registration_id).replace(/_/g, " ")}</p>
              <p className="text-xs text-muted-foreground">
                Expires {new Date(approval.expires_at).toLocaleString()}
              </p>
            </div>
            <Button size="sm" disabled={busyApprovalId === approval.id} onClick={() => handleApprove(approval.id)}>
              Approve
            </Button>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function PublicationApprovals() {
  const queryClient = useQueryClient();
  const [busyPlanId, setBusyPlanId] = useState<string | null>(null);

  const { data: plans } = useQuery({
    queryKey: ["publishing", "plans"],
    queryFn: api.listPublicationPlans,
    refetchInterval: 4000,
  });
  const pending = plans?.filter((p) => p.status === "pending_approval") ?? [];

  const handleReview = async (planId: string, decision: "approved" | "rejected") => {
    setBusyPlanId(planId);
    try {
      await api.reviewPublicationPlan(planId, { decision });
      toast.success(decision === "approved" ? "Approved" : "Rejected");
      await queryClient.invalidateQueries({ queryKey: ["publishing", "plans"] });
    } catch {
      toast.error("Couldn't submit review.");
    } finally {
      setBusyPlanId(null);
    }
  };

  if (pending.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Publishing ready for approval</CardTitle>
        <CardDescription>{pending.length} waiting</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {pending.map((plan) => (
          <div key={plan.id} className="flex items-center justify-between rounded-md border border-border p-3">
            <span className="text-sm font-medium">
              {plan.scheduled_for ? `Scheduled for ${new Date(plan.scheduled_for).toLocaleString()}` : "Publish as soon as approved"}
            </span>
            <div className="flex gap-2">
              <Button size="sm" disabled={busyPlanId === plan.id} onClick={() => handleReview(plan.id, "approved")}>
                Approve
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busyPlanId === plan.id}
                onClick={() => handleReview(plan.id, "rejected")}
              >
                Reject
              </Button>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

export default function ApprovalsPage() {
  const { data: jobs } = useQuery({ queryKey: ["content", "jobs"], queryFn: api.listGenerationJobs });
  const { data: plans } = useQuery({ queryKey: ["publishing", "plans"], queryFn: api.listPublicationPlans });
  const { data: toolApprovals } = useQuery({
    queryKey: ["governance", "approvals", "pending"],
    queryFn: api.listPendingToolApprovals,
  });
  const hasPending =
    (jobs?.some((j) => j.status === "awaiting_review") ?? false) ||
    (plans?.some((p) => p.status === "pending_approval") ?? false) ||
    (toolApprovals?.length ?? 0) > 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Approvals</h1>
        <p className="text-muted-foreground">Everything waiting on your decision.</p>
      </div>
      {!hasPending && (
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">You&apos;re all caught up — nothing needs your review.</p>
          </CardContent>
        </Card>
      )}
      <ContentApprovals />
      <PublicationApprovals />
      <ToolApprovals />
    </div>
  );
}
