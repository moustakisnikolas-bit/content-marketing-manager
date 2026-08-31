"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type ContentRevisionOut } from "@/lib/api";

export function RevisionPreview({ revision, contentType }: { revision: ContentRevisionOut; contentType: string }) {
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
