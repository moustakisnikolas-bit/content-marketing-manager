"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, type StorePlatform } from "@/lib/api";
import { ApiError } from "@/lib/api-client";

const PLATFORM_LABELS: Record<StorePlatform, string> = {
  woocommerce: "WooCommerce",
  shopify: "Shopify",
};

function WooCommerceConnectForm({ onConnected }: { onConnected: () => void }) {
  const [storeDomain, setStoreDomain] = useState("");
  const [consumerKey, setConsumerKey] = useState("");
  const [consumerSecret, setConsumerSecret] = useState("");
  const [connecting, setConnecting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setConnecting(true);
    try {
      await api.connectStoreWithCredentials({
        platform: "woocommerce",
        store_domain: storeDomain,
        consumer_key: consumerKey,
        consumer_secret: consumerSecret,
      });
      toast.success("Connected WooCommerce");
      setStoreDomain("");
      setConsumerKey("");
      setConsumerSecret("");
      onConnected();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't connect — check your store URL and keys.";
      toast.error(message);
    } finally {
      setConnecting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3 rounded-md border border-border p-3">
      <p className="text-sm font-medium">WooCommerce</p>
      <p className="text-xs text-muted-foreground">
        Generate a Consumer Key/Secret in WP Admin → WooCommerce → Settings → Advanced → REST API (permissions
        &quot;Read/Write&quot;), then paste them here. Keys never leave your account — sealed on the way in, never
        shown again.
      </p>
      <div className="space-y-1">
        <Label htmlFor="wc-domain">Store URL</Label>
        <Input
          id="wc-domain"
          placeholder="https://yourshop.com"
          value={storeDomain}
          onChange={(e) => setStoreDomain(e.target.value)}
          required
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor="wc-key">Consumer Key</Label>
        <Input
          id="wc-key"
          placeholder="ck_..."
          value={consumerKey}
          onChange={(e) => setConsumerKey(e.target.value)}
          required
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor="wc-secret">Consumer Secret</Label>
        <Input
          id="wc-secret"
          type="password"
          placeholder="cs_..."
          value={consumerSecret}
          onChange={(e) => setConsumerSecret(e.target.value)}
          required
        />
      </div>
      <Button type="submit" size="sm" disabled={connecting}>
        {connecting ? "Connecting..." : "Connect"}
      </Button>
    </form>
  );
}

function ConnectStoreCard() {
  const queryClient = useQueryClient();
  const [connecting, setConnecting] = useState(false);

  const { data: stores } = useQuery({ queryKey: ["commerce", "stores"], queryFn: api.listStores });

  const handleConnectShopify = async () => {
    setConnecting(true);
    try {
      const { authorization_url } = await api.getStoreAuthorizationUrl("shopify");
      const url = new URL(authorization_url);
      if (url.hostname === "stub-oauth.local") {
        // Dev mode: no real Shopify app is registered in this environment,
        // so there's nowhere to redirect the browser to. Simulate what a
        // real OAuth redirect+callback would produce instead — see
        // backend adapters/store_connector/stub.py.
        const state = url.searchParams.get("state")!;
        await api.completeStoreOAuthCallback("dev-simulated-code", state);
      } else {
        window.location.assign(authorization_url);
        return;
      }
      toast.success("Connected Shopify");
      await queryClient.invalidateQueries({ queryKey: ["commerce", "stores"] });
    } catch {
      toast.error("Couldn't connect. Please try again.");
    } finally {
      setConnecting(false);
    }
  };

  const handleWooCommerceConnected = async () => {
    await queryClient.invalidateQueries({ queryKey: ["commerce", "stores"] });
  };

  const connectedPlatforms = new Set(stores?.map((s) => s.connection.platform));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Connect a store</CardTitle>
        <CardDescription>WooCommerce and Shopify — no API keys ever touch your store admin.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <WooCommerceConnectForm onConnected={handleWooCommerceConnected} />
        <div className="flex items-center justify-between rounded-md border border-border p-3">
          <p className="text-sm font-medium">{PLATFORM_LABELS.shopify}</p>
          <Button size="sm" disabled={connecting} onClick={handleConnectShopify}>
            {connecting ? "Connecting..." : "Connect"}
          </Button>
        </div>
        {connectedPlatforms.size === 0 && (
          <p className="text-xs text-muted-foreground">Not connected to any store yet.</p>
        )}
      </CardContent>
    </Card>
  );
}

function ConnectedStoresCard() {
  const queryClient = useQueryClient();
  const [syncingId, setSyncingId] = useState<string | null>(null);

  const { data: stores } = useQuery({ queryKey: ["commerce", "stores"], queryFn: api.listStores });

  const handleSync = async (connectionId: string) => {
    setSyncingId(connectionId);
    try {
      const result = await api.syncStoreProducts(connectionId);
      toast.success(`Synced ${result.products_synced} product(s).`);
      await queryClient.invalidateQueries({ queryKey: ["commerce", "products"] });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't sync this store.";
      toast.error(message);
    } finally {
      setSyncingId(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Connected stores</CardTitle>
      </CardHeader>
      <CardContent>
        {!stores || stores.length === 0 ? (
          <p className="text-sm text-muted-foreground">No stores connected yet.</p>
        ) : (
          <ul className="space-y-3">
            {stores.map((s) => (
              <li key={s.connection.id} className="rounded-md border border-border p-3 text-sm">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium">
                      {PLATFORM_LABELS[s.connection.platform]} &middot; {s.connection.store_domain}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {s.connection.last_synced_at
                        ? `Last synced ${new Date(s.connection.last_synced_at).toLocaleString()}`
                        : "Never synced"}{" "}
                      &middot; {s.capabilities.filter((c) => c.is_available).map((c) => c.capability).join(", ") ||
                        "no capabilities available"}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={syncingId === s.connection.id}
                    onClick={() => handleSync(s.connection.id)}
                  >
                    {syncingId === s.connection.id ? "Syncing..." : "Sync products"}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export default function EcommercePage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">eCommerce</h1>
        <p className="text-muted-foreground">Connect your store to generate product-aware content.</p>
      </div>
      <ConnectStoreCard />
      <ConnectedStoresCard />
    </div>
  );
}
