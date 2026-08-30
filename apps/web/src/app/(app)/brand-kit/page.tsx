"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";

function splitList(value: string): string[] {
  return value
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
}

function CreateProfileCard() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [tone, setTone] = useState("");
  const [productLine, setProductLine] = useState("");
  const [vocabulary, setVocabulary] = useState("");
  const [colors, setColors] = useState("");
  const [audiences, setAudiences] = useState("");
  const [ctas, setCtas] = useState("");
  const [creating, setCreating] = useState(false);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try {
      await api.createBrandProfile({
        name: name.trim(),
        tone_description: tone.trim() || null,
        product_line_description: productLine.trim() || null,
        vocabulary: splitList(vocabulary),
        colors: splitList(colors),
        target_audiences: splitList(audiences),
        default_ctas: splitList(ctas),
      });
      toast.success(`Created brand profile '${name.trim()}'`);
      setName("");
      setTone("");
      setProductLine("");
      setVocabulary("");
      setColors("");
      setAudiences("");
      setCtas("");
      await queryClient.invalidateQueries({ queryKey: ["brand-profiles"] });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't create this brand profile.";
      toast.error(message);
    } finally {
      setCreating(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">New brand profile</CardTitle>
        <CardDescription>Content generation checks this before anything ships.</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={handleCreate}>
          <div className="space-y-2">
            <Label htmlFor="profile_name">Name</Label>
            <input
              id="profile_name"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Main brand voice"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="tone">Tone</Label>
            <textarea
              id="tone"
              rows={2}
              className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none"
              value={tone}
              onChange={(e) => setTone(e.target.value)}
              placeholder="Friendly, upbeat, never pushy"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="product_line">What do you sell?</Label>
            <textarea
              id="product_line"
              rows={2}
              className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none"
              value={productLine}
              onChange={(e) => setProductLine(e.target.value)}
              placeholder="Soy scented candles, room diffusers, car diffusers, plant-based wax melts"
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="vocabulary">Vocabulary (comma-separated)</Label>
              <input
                id="vocabulary"
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
                value={vocabulary}
                onChange={(e) => setVocabulary(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="colors">Colors (comma-separated hex)</Label>
              <input
                id="colors"
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
                value={colors}
                onChange={(e) => setColors(e.target.value)}
                placeholder="#1a73e8, #22c55e"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="audiences">Target audiences (comma-separated)</Label>
              <input
                id="audiences"
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
                value={audiences}
                onChange={(e) => setAudiences(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ctas">Default calls to action (comma-separated)</Label>
              <input
                id="ctas"
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
                value={ctas}
                onChange={(e) => setCtas(e.target.value)}
                placeholder="Shop now, Learn more"
              />
            </div>
          </div>
          <Button type="submit" size="sm" disabled={creating || !name.trim()}>
            {creating ? "Creating..." : "Create profile"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function RulesSection({ profileId }: { profileId: string }) {
  const queryClient = useQueryClient();
  const [ruleType, setRuleType] = useState("");
  const [description, setDescription] = useState("");
  const [isBlocking, setIsBlocking] = useState(true);
  const [adding, setAdding] = useState(false);

  const { data: detail } = useQuery({
    queryKey: ["brand-profiles", profileId],
    queryFn: () => api.getBrandProfile(profileId),
  });

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ruleType.trim() || !description.trim()) return;
    setAdding(true);
    try {
      await api.addBrandRule(profileId, { rule_type: ruleType.trim(), description: description.trim(), is_blocking: isBlocking });
      toast.success("Rule added");
      setRuleType("");
      setDescription("");
      await queryClient.invalidateQueries({ queryKey: ["brand-profiles", profileId] });
    } catch {
      toast.error("Couldn't add this rule.");
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = async (ruleId: string) => {
    try {
      await api.deleteBrandRule(ruleId);
      toast.success("Rule removed");
      await queryClient.invalidateQueries({ queryKey: ["brand-profiles", profileId] });
    } catch {
      toast.error("Couldn't remove this rule.");
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Rules</CardTitle>
        <CardDescription>Blocking rules stop generation outright; non-blocking rules are a warning.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {detail && detail.rules.length > 0 && (
          <ul className="space-y-2">
            {detail.rules.map((rule) => (
              <li key={rule.id} className="flex items-center justify-between rounded-md border border-border p-3 text-sm">
                <div>
                  <p className="font-medium">
                    {rule.rule_type} {rule.is_blocking && <span className="text-xs text-destructive">(blocking)</span>}
                  </p>
                  <p className="text-xs text-muted-foreground">{rule.description}</p>
                </div>
                <Button size="sm" variant="outline" onClick={() => handleDelete(rule.id)}>
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}

        <form className="grid gap-3 sm:grid-cols-[160px_1fr_auto_auto] sm:items-end" onSubmit={handleAdd}>
          <div className="space-y-2">
            <Label htmlFor="rule_type">Type</Label>
            <input
              id="rule_type"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
              value={ruleType}
              onChange={(e) => setRuleType(e.target.value)}
              placeholder="forbidden_claim"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="rule_description">Description</Label>
            <input
              id="rule_description"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Never claim 'guaranteed results'"
            />
          </div>
          <label className="flex items-center gap-2 pb-1 text-sm">
            <input type="checkbox" checked={isBlocking} onChange={(e) => setIsBlocking(e.target.checked)} className="h-4 w-4 rounded border-input" />
            Blocking
          </label>
          <Button type="submit" size="sm" disabled={adding || !ruleType.trim() || !description.trim()}>
            {adding ? "Adding..." : "Add rule"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

export default function BrandKitPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { data: profiles } = useQuery({ queryKey: ["brand-profiles"], queryFn: api.listBrandProfiles });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Brand Kit</h1>
        <p className="text-muted-foreground">Define your voice and rules — content generation enforces them automatically.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">Profiles</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {!profiles || profiles.length === 0 ? (
              <p className="text-sm text-muted-foreground">No brand profiles yet.</p>
            ) : (
              profiles.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setSelectedId(p.id)}
                  className={cn(
                    "block w-full rounded-md px-3 py-2 text-left text-sm transition-colors",
                    selectedId === p.id ? "bg-accent text-accent-foreground" : "hover:bg-muted",
                  )}
                >
                  <p className="font-medium">{p.name}</p>
                  <p className="text-xs text-muted-foreground">{p.is_active ? "Active" : "Inactive"}</p>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <CreateProfileCard />
          {selectedId && <RulesSection profileId={selectedId} />}
        </div>
      </div>
    </div>
  );
}
