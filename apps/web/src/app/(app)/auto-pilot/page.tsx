"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type CampaignOut } from "@/lib/api";

function AutoPilotRow({ campaign }: { campaign: CampaignOut }) {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);

  const { data: policy, isError } = useQuery({
    queryKey: ["marketing", "autopilot-policy", campaign.id],
    queryFn: () => api.getAutoPilotPolicy(campaign.id),
    retry: false,
  });

  if (isError || !policy) return null;

  const handleHalt = async () => {
    setBusy(true);
    try {
      await api.haltAutoPilot(campaign.id);
      toast.success(`Kill switch activated for '${campaign.name}'`);
      await queryClient.invalidateQueries({ queryKey: ["marketing", "autopilot-policy", campaign.id] });
    } catch {
      toast.error("Couldn't activate the kill switch.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="flex items-center justify-between rounded-md border border-border p-3 text-sm">
      <div>
        <Link href={`/campaigns?campaign=${campaign.id}`} className="font-medium hover:underline">
          {campaign.name}
        </Link>
        <p className="text-xs text-muted-foreground">
          Allowed: {policy.allowed_platforms.join(", ") || "none"} &middot; Limit: {policy.max_total_spend} credits
          {policy.kill_switch_active && " · Kill switch is ACTIVE"}
        </p>
      </div>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" render={<Link href={`/campaigns?campaign=${campaign.id}`} />}>
          Manage
        </Button>
        <Button size="sm" variant="outline" disabled={busy || policy.kill_switch_active} onClick={handleHalt}>
          Kill switch
        </Button>
      </div>
    </li>
  );
}

export default function AutoPilotPage() {
  const { data: campaigns } = useQuery({ queryKey: ["marketing", "campaigns"], queryFn: api.listCampaigns });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Auto-Pilot</h1>
        <p className="text-muted-foreground">Every campaign with Auto-Pilot configured, across your workspace.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Active policies</CardTitle>
          <CardDescription>Manage a campaign&apos;s full policy from the Campaigns page.</CardDescription>
        </CardHeader>
        <CardContent>
          {!campaigns || campaigns.length === 0 ? (
            <p className="text-sm text-muted-foreground">No campaigns yet.</p>
          ) : (
            <ul className="space-y-2">
              {campaigns.map((c) => (
                <AutoPilotRow key={c.id} campaign={c} />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
