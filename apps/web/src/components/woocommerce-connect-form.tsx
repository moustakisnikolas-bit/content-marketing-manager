"use client";

import { type FormEvent, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { ApiError } from "@/lib/api-client";

export function WooCommerceConnectForm({ onConnected }: { onConnected: () => void }) {
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
