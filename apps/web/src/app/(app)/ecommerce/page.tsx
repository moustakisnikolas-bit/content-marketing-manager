"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { WooCommerceConnectForm } from "@/components/woocommerce-connect-form";
import { api, type StorePlatform } from "@/lib/api";
import { ApiError } from "@/lib/api-client";

const PLATFORM_LABELS: Record<StorePlatform, string> = {
  woocommerce: "WooCommerce",
  shopify: "Shopify",
};

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

function PluginPairingCard() {
  const [pairing, setPairing] = useState<{ token: string; expiresInMinutes: number } | null>(null);
  const [generating, setGenerating] = useState(false);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const result = await api.createPluginPairingCode();
      setPairing({ token: result.pairing_token, expiresInMinutes: result.expires_in_minutes });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't generate a pairing code.";
      toast.error(message);
    } finally {
      setGenerating(false);
    }
  };

  const handleCopy = async () => {
    if (!pairing) return;
    try {
      await navigator.clipboard.writeText(pairing.token);
      toast.success("Copied");
    } catch {
      toast.error("Couldn't copy — select and copy the code manually.");
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Connect automatically with our WordPress plugin</CardTitle>
        <CardDescription>
          Skip generating API keys yourself — install the plugin on your WooCommerce site and it connects for you.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {!pairing ? (
          <Button size="sm" disabled={generating} onClick={handleGenerate}>
            {generating ? "Generating..." : "Generate pairing code"}
          </Button>
        ) : (
          <div className="space-y-2">
            <ol className="list-inside list-decimal text-sm text-muted-foreground">
              <li>Install the plugin on your WordPress site</li>
              <li>Paste this code into its settings screen</li>
              <li>Click Connect there — it&apos;ll finish here automatically</li>
            </ol>
            <div className="flex gap-2">
              <Input readOnly value={pairing.token} className="font-mono text-xs" />
              <Button type="button" size="sm" variant="outline" onClick={handleCopy}>
                Copy
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">Expires in {pairing.expiresInMinutes} minutes.</p>
          </div>
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
      <PluginPairingCard />
      <ConnectedStoresCard />
    </div>
  );
}
