"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";

export default function BillingPage() {
  const { data: balance, isLoading } = useQuery({
    queryKey: ["billing", "subscription"],
    queryFn: api.getSubscriptionBalance,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Billing</h1>
        <p className="text-muted-foreground">Your plan and credit balance.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Credit balance</CardTitle>
          <CardDescription>
            Credits are reserved before any paid action and settled once it&apos;s complete — you&apos;ll never be
            charged more than you approved.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : (
            <p className="text-3xl font-semibold text-primary">
              {balance ? Number(balance.credit_balance).toFixed(2) : "—"}
              <span className="ml-2 text-sm font-normal text-muted-foreground">credits available</span>
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
