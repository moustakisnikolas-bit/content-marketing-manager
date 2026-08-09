"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { api, type OrganizationBrandingOut } from "@/lib/api";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import { useWorkspaceStore } from "@/stores/workspace-store";

function WorkspacesSection() {
  const queryClient = useQueryClient();
  const { activeWorkspaceId, setActiveWorkspaceId } = useWorkspaceStore();
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  const { data: workspaces } = useQuery({ queryKey: ["organizations", "workspaces"], queryFn: api.listMyWorkspaces });

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const workspace = await api.createWorkspace({ name: newName.trim() });
      toast.success(`Created workspace '${workspace.name}'`);
      setNewName("");
      await queryClient.invalidateQueries({ queryKey: ["organizations", "workspaces"] });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't create this workspace.";
      toast.error(message);
    } finally {
      setCreating(false);
    }
  };

  const handleSwitch = (workspaceId: string) => {
    setActiveWorkspaceId(workspaceId);
    toast.success("Switched workspace");
    // Every workspace-scoped query key includes nothing about the
    // workspace itself (the backend resolves it from X-Workspace-Id), so
    // a full invalidation is what makes the switch actually show new data.
    queryClient.invalidateQueries();
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Workspaces</CardTitle>
        <CardDescription>
          Switch between workspaces you belong to, or create another client/brand workspace.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ul className="space-y-2">
          {workspaces?.map(({ workspace, role }) => {
            const isActive = activeWorkspaceId ? activeWorkspaceId === workspace.id : workspaces[0]?.workspace.id === workspace.id;
            return (
              <li
                key={workspace.id}
                className={cn(
                  "flex items-center justify-between rounded-md border p-3 text-sm",
                  isActive ? "border-primary bg-accent/40" : "border-border",
                )}
              >
                <div>
                  <p className="font-medium">{workspace.name}</p>
                  <p className="text-xs text-muted-foreground">{role.name}</p>
                </div>
                {isActive ? (
                  <span className="text-xs font-medium text-primary">Active</span>
                ) : (
                  <Button size="sm" variant="outline" onClick={() => handleSwitch(workspace.id)}>
                    Switch to this
                  </Button>
                )}
              </li>
            );
          })}
        </ul>

        <form className="flex items-end gap-2" onSubmit={handleCreate}>
          <div className="flex-1 space-y-2">
            <Label htmlFor="new_workspace">New workspace name</Label>
            <input
              id="new_workspace"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="e.g. Client B"
            />
          </div>
          <Button type="submit" size="sm" disabled={creating || !newName.trim()}>
            {creating ? "Creating..." : "Create"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function TeamSection() {
  const queryClient = useQueryClient();
  const { activeWorkspaceId } = useWorkspaceStore();
  const { data: workspaces } = useQuery({ queryKey: ["organizations", "workspaces"], queryFn: api.listMyWorkspaces });
  const workspaceId = activeWorkspaceId ?? workspaces?.[0]?.workspace.id;

  const [email, setEmail] = useState("");
  const [roleName, setRoleName] = useState("Editor");
  const [inviting, setInviting] = useState(false);
  const [lastToken, setLastToken] = useState<string | null>(null);

  const { data: invitations } = useQuery({
    queryKey: ["organizations", "invitations", workspaceId],
    queryFn: () => api.listPendingInvitations(workspaceId!),
    enabled: !!workspaceId,
  });

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!workspaceId || !email.trim()) return;
    setInviting(true);
    setLastToken(null);
    try {
      const { invite_token } = await api.createInvitation(workspaceId, { email: email.trim(), role_name: roleName });
      setLastToken(invite_token);
      toast.success(`Invited ${email.trim()}`);
      setEmail("");
      await queryClient.invalidateQueries({ queryKey: ["organizations", "invitations", workspaceId] });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't send this invitation.";
      toast.error(message);
    } finally {
      setInviting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Team &amp; clients</CardTitle>
        <CardDescription>Invite people to your active workspace with a role.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <form className="grid gap-3 sm:grid-cols-[1fr_180px_auto] sm:items-end" onSubmit={handleInvite}>
          <div className="space-y-2">
            <Label htmlFor="invite_email">Email</Label>
            <input
              id="invite_email"
              type="email"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="invite_role">Role</Label>
            <select
              id="invite_role"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
              value={roleName}
              onChange={(e) => setRoleName(e.target.value)}
            >
              <option value="Admin">Admin</option>
              <option value="Editor">Editor</option>
              <option value="Client Viewer">Client Viewer</option>
            </select>
          </div>
          <Button type="submit" size="sm" disabled={inviting || !email.trim()}>
            {inviting ? "Inviting..." : "Invite"}
          </Button>
        </form>

        {lastToken && (
          <p className="rounded-md border border-border bg-muted/40 p-3 text-xs">
            Invite link (dev mode — normally emailed):{" "}
            <span className="font-mono break-all">{lastToken}</span>
          </p>
        )}

        {invitations && invitations.length > 0 && (
          <ul className="space-y-2">
            {invitations.map((inv) => (
              <li key={inv.id} className="flex items-center justify-between rounded-md border border-border p-3 text-sm">
                <span>{inv.email}</span>
                <span className="text-xs text-muted-foreground">
                  {inv.status} &middot; expires {new Date(inv.expires_at).toLocaleDateString()}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function AcceptInvitationSection() {
  const queryClient = useQueryClient();
  const [token, setToken] = useState("");
  const [accepting, setAccepting] = useState(false);

  const handleAccept = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token.trim()) return;
    setAccepting(true);
    try {
      await api.acceptInvitation(token.trim());
      toast.success("Joined the workspace — switch to it above.");
      setToken("");
      await queryClient.invalidateQueries({ queryKey: ["organizations", "workspaces"] });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "That invite link isn't valid or has expired.";
      toast.error(message);
    } finally {
      setAccepting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Have an invite?</CardTitle>
        <CardDescription>Paste the invite token someone sent you to join their workspace.</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="flex items-end gap-2" onSubmit={handleAccept}>
          <div className="flex-1 space-y-2">
            <Label htmlFor="invite_token">Invite token</Label>
            <input
              id="invite_token"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none font-mono"
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          </div>
          <Button type="submit" size="sm" disabled={accepting || !token.trim()}>
            {accepting ? "Joining..." : "Join workspace"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function ApiKeysSection() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [lastRawKey, setLastRawKey] = useState<string | null>(null);

  const { data: keys } = useQuery({ queryKey: ["api-keys"], queryFn: api.listApiKeys });

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setLastRawKey(null);
    try {
      const { raw_key } = await api.createApiKey({ name: name.trim(), scopes: ["analytics:read", "commerce:read"] });
      setLastRawKey(raw_key);
      toast.success("API key created");
      setName("");
      await queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't create this API key.";
      toast.error(message);
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (id: string) => {
    try {
      await api.revokeApiKey(id);
      toast.success("Revoked");
      await queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    } catch {
      toast.error("Couldn't revoke this key.");
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Public API keys</CardTitle>
        <CardDescription>Rate-limited, read-only access to your workspace&apos;s data.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <form className="flex items-end gap-2" onSubmit={handleCreate}>
          <div className="flex-1 space-y-2">
            <Label htmlFor="key_name">Key name</Label>
            <input
              id="key_name"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Client reporting dashboard"
            />
          </div>
          <Button type="submit" size="sm" disabled={creating || !name.trim()}>
            {creating ? "Creating..." : "Create key"}
          </Button>
        </form>

        {lastRawKey && (
          <p className="rounded-md border border-border bg-muted/40 p-3 text-xs">
            Copy this now — it won&apos;t be shown again: <span className="font-mono break-all">{lastRawKey}</span>
          </p>
        )}

        {keys && keys.length > 0 && (
          <ul className="space-y-2">
            {keys.map((k) => (
              <li key={k.id} className="flex items-center justify-between rounded-md border border-border p-3 text-sm">
                <div>
                  <p className="font-medium">
                    {k.name} <span className="text-xs text-muted-foreground">({k.key_prefix}...)</span>
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {k.status} &middot; {k.scopes.join(", ")}
                  </p>
                </div>
                {k.status === "active" && (
                  <Button size="sm" variant="outline" onClick={() => handleRevoke(k.id)}>
                    Revoke
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function BrandingForm({ branding }: { branding: OrganizationBrandingOut }) {
  const queryClient = useQueryClient();
  const [productName, setProductName] = useState(branding.product_name ?? "");
  const [logoUrl, setLogoUrl] = useState(branding.logo_url ?? "");
  const [primaryColor, setPrimaryColor] = useState(branding.primary_color ?? "");
  const [saving, setSaving] = useState(false);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.updateOrganizationBranding({
        product_name: productName || null,
        logo_url: logoUrl || null,
        primary_color: primaryColor || null,
      });
      toast.success("Branding saved");
      await queryClient.invalidateQueries({ queryKey: ["organizations", "branding"] });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Couldn't save branding.";
      toast.error(message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="space-y-4" onSubmit={handleSave}>
      <div className="space-y-2">
        <Label htmlFor="product_name">Product name</Label>
        <input
          id="product_name"
          className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
          value={productName}
          onChange={(e) => setProductName(e.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="logo_url">Logo URL</Label>
        <input
          id="logo_url"
          className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
          value={logoUrl}
          onChange={(e) => setLogoUrl(e.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="primary_color">Primary color (hex)</Label>
        <input
          id="primary_color"
          className="flex h-9 w-40 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none"
          value={primaryColor}
          onChange={(e) => setPrimaryColor(e.target.value)}
          placeholder="#1a73e8"
        />
      </div>
      <Button type="submit" size="sm" disabled={saving}>
        {saving ? "Saving..." : "Save branding"}
      </Button>
    </form>
  );
}

function BrandingSection() {
  const { data: branding } = useQuery({ queryKey: ["organizations", "branding"], queryFn: api.getOrganizationBranding });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">White-label branding</CardTitle>
        <CardDescription>A starting point — product name, logo, and accent color.</CardDescription>
      </CardHeader>
      <CardContent>
        {branding ? (
          // Keyed by the loaded data so a fresh save (which invalidates and
          // refetches) remounts the form with the new values as initial
          // state, instead of syncing props into state via an effect.
          <BrandingForm key={JSON.stringify(branding)} branding={branding} />
        ) : (
          <p className="text-sm text-muted-foreground">Loading...</p>
        )}
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="text-muted-foreground">Workspaces, team, API access, and branding.</p>
      </div>
      <WorkspacesSection />
      <TeamSection />
      <AcceptInvitationSection />
      <ApiKeysSection />
      <BrandingSection />
    </div>
  );
}
