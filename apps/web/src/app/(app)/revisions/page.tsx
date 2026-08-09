"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type ContentRevisionOut } from "@/lib/api";
import { cn } from "@/lib/utils";

const REVISION_KIND_LABELS: Record<string, string> = {
  draft_preview: "Draft",
  final_render: "Final",
};

function RevisionPreview({ revision, contentType }: { revision: ContentRevisionOut; contentType: string }) {
  const { data } = useQuery({
    queryKey: ["assets", revision.asset_id, "download-url"],
    queryFn: () => api.getAssetDownloadUrl(revision.asset_id!),
    enabled: !!revision.asset_id,
  });

  if (revision.text_body) {
    return <p className="whitespace-pre-wrap text-sm">{revision.text_body}</p>;
  }
  if (!revision.asset_id || !data) {
    return <p className="text-sm text-muted-foreground">No preview available.</p>;
  }
  if (contentType === "image") {
    // eslint-disable-next-line @next/next/no-img-element -- presigned storage URL, not a local/optimizable asset
    return <img src={data.url} alt="Generated content" className="max-h-64 rounded-md border border-border" />;
  }
  if (contentType === "audio") {
    return <audio controls className="w-full" src={data.url} />;
  }
  return null;
}

function ItemRevisions({ itemId }: { itemId: string }) {
  const { data: detail } = useQuery({ queryKey: ["content", "items", itemId], queryFn: () => api.getContentItem(itemId) });

  if (!detail) return null;

  return (
    <div className="space-y-4">
      {detail.revisions.length === 0 ? (
        <p className="text-sm text-muted-foreground">No revisions yet.</p>
      ) : (
        [...detail.revisions].reverse().map((revision) => (
          <Card key={revision.id}>
            <CardHeader>
              <CardTitle className="text-sm">
                Revision {revision.revision_number} &middot; {REVISION_KIND_LABELS[revision.kind] ?? revision.kind}
                <span className="ml-2 text-xs font-normal text-muted-foreground">
                  {new Date(revision.created_at).toLocaleString()}
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <RevisionPreview revision={revision} contentType={detail.item.content_type} />
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
}

export default function RevisionsPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { data: items } = useQuery({ queryKey: ["content", "items"], queryFn: api.listContentItems });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Revisions</h1>
        <p className="text-muted-foreground">Every version of every piece of content, in order.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">Content items</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {!items || items.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nothing created yet.</p>
            ) : (
              items.map((item) => (
                <button
                  key={item.id}
                  onClick={() => setSelectedId(item.id)}
                  className={cn(
                    "block w-full rounded-md px-3 py-2 text-left text-sm transition-colors",
                    selectedId === item.id ? "bg-accent text-accent-foreground" : "hover:bg-muted",
                  )}
                >
                  <p className="font-medium">{item.title}</p>
                  <p className="text-xs text-muted-foreground">
                    {item.content_type} &middot; {item.status}
                  </p>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        {selectedId ? (
          <ItemRevisions itemId={selectedId} />
        ) : (
          <Card>
            <CardContent className="pt-6">
              <p className="text-sm text-muted-foreground">Select a content item to see its revision history.</p>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
