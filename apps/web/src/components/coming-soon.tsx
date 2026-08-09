import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function ComingSoon({ title, phase }: { title: string; phase: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">
          {title} is on the way — it&apos;s planned for {phase}. Nothing to do here yet.
        </p>
      </CardContent>
    </Card>
  );
}
