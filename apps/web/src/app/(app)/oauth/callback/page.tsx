"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type ConnectableAccountOut } from "@/lib/api";
import { ApiError } from "@/lib/api-client";
import { POST_OAUTH_REDIRECT_KEY } from "@/lib/oauth-redirect";

function OAuthCallbackInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<{ pendingToken: string; accounts: ConnectableAccountOut[] } | null>(null);
  const [selecting, setSelecting] = useState(false);
  const started = useRef(false);
  // Where to land after a successful connect — defaults to /calendar (today's
  // behavior) but /quick-start sets this before redirecting to Meta, since a
  // full-page OAuth redirect would otherwise strand it back here instead of
  // returning to the wizard. Read once and cleared immediately so a stale
  // value never redirects an unrelated, later connect-from-/calendar flow.
  const redirectTarget = useRef("/calendar");

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const stored = sessionStorage.getItem(POST_OAUTH_REDIRECT_KEY);
    if (stored) {
      redirectTarget.current = stored;
      sessionStorage.removeItem(POST_OAUTH_REDIRECT_KEY);
    }

    const code = searchParams.get("code");
    const state = searchParams.get("state");
    if (!code || !state) {
      toast.error("Missing code/state from the redirect — couldn't complete the connection.");
      router.replace(redirectTarget.current);
      return;
    }

    (async () => {
      try {
        const result = await api.completeOAuthCallback(code, state);
        if ("pending_token" in result) {
          // Meta returned more than one Facebook Page — need the user to
          // pick which one before a connection actually exists.
          setPending({ pendingToken: result.pending_token, accounts: result.accounts });
          return;
        }
        toast.success(`Connected ${result.connection.platform}`);
        await queryClient.invalidateQueries({ queryKey: ["publishing", "connections"] });
        router.replace(redirectTarget.current);
      } catch (err) {
        const message = err instanceof ApiError ? err.message : "Couldn't complete the connection.";
        toast.error(message);
        router.replace(redirectTarget.current);
      }
    })();
  }, [searchParams, router, queryClient]);

  const handleSelectPage = async (account: ConnectableAccountOut) => {
    if (!pending) return;
    setSelecting(true);
    try {
      await api.selectPage(pending.pendingToken, account.external_account_id);
      toast.success(`Connected ${account.external_account_name}`);
      await queryClient.invalidateQueries({ queryKey: ["publishing", "connections"] });
      router.replace(redirectTarget.current);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't complete the connection.";
      toast.error(message);
    } finally {
      setSelecting(false);
    }
  };

  if (!pending) {
    return <p className="text-sm text-muted-foreground">Connecting...</p>;
  }

  return (
    <Card className="mx-auto max-w-md">
      <CardHeader>
        <CardTitle className="text-base">Choose a Page</CardTitle>
        <CardDescription>You manage more than one Facebook Page — pick which one to connect.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {pending.accounts.map((account) => (
          <Button
            key={account.external_account_id}
            variant="outline"
            className="w-full justify-start"
            disabled={selecting}
            onClick={() => handleSelectPage(account)}
          >
            {account.external_account_name}
          </Button>
        ))}
      </CardContent>
    </Card>
  );
}

export default function OAuthCallbackPage() {
  return (
    <Suspense fallback={null}>
      <OAuthCallbackInner />
    </Suspense>
  );
}
