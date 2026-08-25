import { CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { CampaignProposalOut } from "@/lib/api";

/** Read-only proposal display, shared by /marketing-manager and /quick-start —
 * the two pages differ only in what happens on approve (manual campaign name +
 * single approve button vs. an auto-derived name + a chained Auto-Pilot setup
 * sequence), never in how the proposal itself is shown. */
export function ProposalSummary({ proposal }: { proposal: CampaignProposalOut }) {
  return (
    <>
      <CardHeader>
        <CardTitle className="text-base">{proposal.objective}</CardTitle>
        <CardDescription>{proposal.plan_summary}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <p className="text-sm font-medium">Planned posts</p>
          <ul className="mt-2 space-y-2">
            {proposal.plan_items_draft.map((item, i) => (
              <li key={i} className="rounded-md border border-border p-3 text-sm">
                <p className="font-medium">{item.title}</p>
                <p className="text-muted-foreground">{item.brief_text}</p>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <p className="text-sm font-medium">Assumptions</p>
          <ul className="mt-1 list-inside list-disc text-sm text-muted-foreground">
            {proposal.assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
        <p className="text-sm text-muted-foreground">{proposal.explanation}</p>
        <p className="text-lg font-semibold text-primary">
          Estimated cost: {Number(proposal.estimated_cost).toFixed(2)} credits
        </p>
      </CardContent>
    </>
  );
}
