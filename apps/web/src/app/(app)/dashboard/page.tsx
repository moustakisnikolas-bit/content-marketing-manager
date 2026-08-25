"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type ProductOut } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";

function TopProductsCard() {
  const { data: products, isLoading } = useQuery({ queryKey: ["commerce", "products"], queryFn: api.listProducts });

  const top3 = (products ?? [])
    .filter((p) => p.status === "active" && p.price !== null)
    .sort((a, b) => Number(b.price) - Number(a.price))
    .slice(0, 3);

  return (
    <Card className="border-primary/30">
      <CardHeader>
        <CardTitle>Top products from your store</CardTitle>
        <CardDescription>Your 3 highest-priced active products from your connected store.</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : top3.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No products yet —{" "}
            <Link href="/ecommerce" className="text-primary underline-offset-4 hover:underline">
              connect a store
            </Link>{" "}
            to see your top products here.
          </p>
        ) : (
          <ol className="space-y-3">
            {top3.map((product: ProductOut, i: number) => (
              <li key={product.id} className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                    {i + 1}
                  </span>
                  <span className="truncate text-sm font-medium">{product.title}</span>
                </div>
                <span className="shrink-0 text-sm font-semibold">
                  {product.price} {product.currency ?? ""}
                </span>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);
  const { data: balance, isLoading } = useQuery({
    queryKey: ["billing", "subscription"],
    queryFn: api.getSubscriptionBalance,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Welcome back{user ? `, ${user.display_name.split(" ")[0]}` : ""}</h1>
        <p className="text-muted-foreground">Here&apos;s where things stand today.</p>
      </div>

      <Card className="border-primary/30">
        <CardHeader>
          <CardTitle>What would you like to achieve?</CardTitle>
          <CardDescription>Tell us your goal and we&apos;ll build a plan around it.</CardDescription>
        </CardHeader>
        <CardContent>
          <Button render={<Link href="/quick-start" />} nativeButton={false}>Start a campaign</Button>
        </CardContent>
      </Card>

      <TopProductsCard />

      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Continue where you left off</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">Nothing in progress yet — your drafts will show up here.</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Needs your attention</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">You&apos;re all caught up.</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Upcoming publications</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">Nothing scheduled yet.</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Campaign results</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">Results will appear once a campaign has run.</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Usage summary</CardTitle>
          <CardDescription>Your available credit balance</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : (
            <p className="text-3xl font-semibold text-primary">
              {balance ? Number(balance.credit_balance).toFixed(2) : "—"}
              <span className="ml-2 text-sm font-normal text-muted-foreground">credits</span>
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
