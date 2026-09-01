"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api, type ContentRevisionOut } from "@/lib/api";

export function RevisionPreview({
  revision,
  contentType,
  onEdited,
}: {
  revision: ContentRevisionOut;
  contentType: string;
  onEdited?: (appliedToSiblings: number) => void;
}) {
  const { data } = useQuery({
    queryKey: ["assets", revision.asset_id, "download-url"],
    queryFn: () => api.getAssetDownloadUrl(revision.asset_id!),
    enabled: !!revision.asset_id,
  });
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(revision.text_body ?? "");
  const [saving, setSaving] = useState(false);

  const handleStartEdit = () => {
    setDraft(revision.text_body ?? "");
    setIsEditing(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const result = await api.editRevisionText(revision.id, draft);
      setIsEditing(false);
      toast.success(
        result.applied_to_siblings > 0
          ? `Saved — applied the same removal to ${result.applied_to_siblings} other pending item(s)`
          : "Saved",
      );
      onEdited?.(result.applied_to_siblings);
    } catch {
      toast.error("Couldn't save your edit.");
    } finally {
      setSaving(false);
    }
  };

  if (revision.text_body !== null) {
    if (isEditing) {
      return (
        <div className="space-y-2">
          <textarea
            rows={5}
            className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            autoFocus
          />
          <div className="flex gap-2">
            <Button size="sm" disabled={saving} onClick={handleSave}>
              {saving ? "Saving..." : "Save"}
            </Button>
            <Button size="sm" variant="ghost" disabled={saving} onClick={() => setIsEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      );
    }
    return (
      <div className="space-y-2">
        <p className="whitespace-pre-wrap text-sm">{revision.text_body}</p>
        <Button size="sm" variant="outline" onClick={handleStartEdit}>
          Edit text
        </Button>
      </div>
    );
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
