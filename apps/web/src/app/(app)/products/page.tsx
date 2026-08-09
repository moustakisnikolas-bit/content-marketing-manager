"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";

function ProductCampaignForm({ productId, productTitle }: { productId: string; productTitle: string }) {
  const { data: goals } = useQuery({ queryKey: ["marketing", "goals"], queryFn: api.listMarketingGoals });
  const [goalSlug, setGoalSlug] = useState("");
  const [platforms, setPlatforms] = useState("facebook");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!goalSlug) return;
    setSubmitting(true);
    setResult(null);
    try {
      const proposal = await api.generateProductCampaign(productId, {
        goal_slug: goalSlug,
        mode: "guided",
        target_platforms: platforms.split(",").map((p) => p.trim()).filter(Boolean),
      });
      setResult(proposal.explanation);
      toast.success("Product campaign proposal generated.");
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't generate a campaign for this product.";
      toast.error(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Generate a product campaign</CardTitle>
        <CardDescription>Builds a real campaign proposal from {productTitle}&apos;s details.</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="goal">Goal</Label>
            <select
              id="goal"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
              value={goalSlug}
              onChange={(e) => setGoalSlug(e.target.value)}
            >
              <option value="">Select a goal...</option>
              {goals?.map((g) => (
                <option key={g.id} value={g.slug}>
                  {g.label}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="platforms">Target platforms (comma-separated)</Label>
            <input
              id="platforms"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
              value={platforms}
              onChange={(e) => setPlatforms(e.target.value)}
            />
          </div>
          <Button type="submit" size="sm" disabled={submitting || !goalSlug}>
            {submitting ? "Generating..." : "Generate campaign"}
          </Button>
        </form>
        {result && <p className="mt-4 rounded-md border border-border bg-muted/40 p-3 text-sm">{result}</p>}
      </CardContent>
    </Card>
  );
}

function AbandonedCartSection({ productId, productTitle }: { productId: string; productTitle: string }) {
  const [consentConfirmed, setConsentConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  const handleGenerate = async () => {
    setSubmitting(true);
    setResult(null);
    try {
      const proposal = await api.generateAbandonedCartContent(productId, { consent_confirmed: consentConfirmed });
      setResult({ ok: true, message: proposal.explanation });
      toast.success("Abandoned-cart content generated.");
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Couldn't generate abandoned-cart content.";
      setResult({ ok: false, message });
      toast.error(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Abandoned-cart reminder</CardTitle>
        <CardDescription>
          Only generated when customer marketing consent is explicitly confirmed for {productTitle} — never assumed.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={consentConfirmed}
            onChange={(e) => setConsentConfirmed(e.target.checked)}
            className="h-4 w-4 rounded border-input"
          />
          Customer has confirmed marketing consent
        </label>
        <Button size="sm" variant="outline" disabled={submitting} onClick={handleGenerate}>
          {submitting ? "Generating..." : "Generate reminder content"}
        </Button>
        {result && (
          <p
            className={cn(
              "rounded-md border p-3 text-sm",
              result.ok ? "border-border bg-muted/40" : "border-destructive/40 bg-destructive/10 text-destructive",
            )}
          >
            {result.message}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function ProductDetail({ productId }: { productId: string }) {
  const { data: detail } = useQuery({ queryKey: ["commerce", "product", productId], queryFn: () => api.getProduct(productId) });
  if (!detail) return null;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{detail.product.title}</CardTitle>
          <CardDescription>
            {detail.product.price ? `${detail.product.price} ${detail.product.currency ?? ""}` : "No price set"} &middot;{" "}
            {detail.product.status}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">{detail.product.description || "No description."}</p>
          {detail.variants.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium uppercase text-muted-foreground">Variants</p>
              <ul className="space-y-1 text-sm">
                {detail.variants.map((v) => (
                  <li key={v.id} className="flex justify-between">
                    <span>{v.title}</span>
                    <span className="text-muted-foreground">{v.price ?? "-"}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>

      <ProductCampaignForm productId={productId} productTitle={detail.product.title} />
      <AbandonedCartSection productId={productId} productTitle={detail.product.title} />
    </div>
  );
}

export default function ProductsPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { data: products } = useQuery({ queryKey: ["commerce", "products"], queryFn: api.listProducts });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Products</h1>
        <p className="text-muted-foreground">Synced from your connected stores.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">All products</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {!products || products.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No products yet — connect a store and sync from the eCommerce page.
              </p>
            ) : (
              products.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setSelectedId(p.id)}
                  className={cn(
                    "block w-full rounded-md px-3 py-2 text-left text-sm transition-colors",
                    selectedId === p.id ? "bg-accent text-accent-foreground" : "hover:bg-muted",
                  )}
                >
                  <p className="font-medium">{p.title}</p>
                  <p className="text-xs text-muted-foreground">{p.price ? `${p.price} ${p.currency ?? ""}` : "-"}</p>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        {selectedId ? (
          <ProductDetail productId={selectedId} />
        ) : (
          <Card>
            <CardContent className="pt-6">
              <p className="text-sm text-muted-foreground">Select a product to see details.</p>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
