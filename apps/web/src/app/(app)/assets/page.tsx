"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError } from "@/lib/api-client";
import { api } from "@/lib/api";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function AssetsPage() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isUploading, setIsUploading] = useState(false);

  const { data: assets, isLoading } = useQuery({
    queryKey: ["assets"],
    queryFn: api.listAssets,
  });

  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    try {
      await api.uploadAsset(file);
      toast.success(`Uploaded ${file.name}`);
      await queryClient.invalidateQueries({ queryKey: ["assets"] });
      await queryClient.invalidateQueries({ queryKey: ["billing", "subscription"] });
    } catch (err) {
      const message =
        err instanceof ApiError && err.status === 402
          ? "Not enough credits to upload this file."
          : "Upload failed. Please try again.";
      toast.error(message);
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Assets</h1>
          <p className="text-muted-foreground">Upload logos, product photos, and other files to use in your content.</p>
        </div>
        <div>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            onChange={handleFileChange}
            disabled={isUploading}
          />
          <Button onClick={() => fileInputRef.current?.click()} disabled={isUploading}>
            {isUploading ? "Uploading..." : "Upload a file"}
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Your files</CardTitle>
          <CardDescription>{assets?.length ?? 0} uploaded</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : !assets || assets.length === 0 ? (
            <p className="text-sm text-muted-foreground">No files yet — upload your first one above.</p>
          ) : (
            <ul className="divide-y divide-border">
              {assets.map((asset) => (
                <li key={asset.id} className="flex items-center justify-between py-3">
                  <div>
                    <p className="text-sm font-medium">{asset.original_filename}</p>
                    <p className="text-xs text-muted-foreground">
                      {asset.content_type} · {formatBytes(asset.byte_size)}
                    </p>
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {new Date(asset.created_at).toLocaleString()}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
