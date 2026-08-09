import { create } from "zustand";
import { persist } from "zustand/middleware";

interface WorkspaceState {
  activeWorkspaceId: string | null;
  setActiveWorkspaceId: (workspaceId: string) => void;
  clearActiveWorkspaceId: () => void;
}

// Phase 8: which workspace the app is currently "in" — sent as
// X-Workspace-Id on every API call (see lib/api-client.ts) so a user with
// memberships in multiple workspaces (an agency team member, a client
// contractor) can switch between them. Unset means "use my first
// membership," matching the backend's default when the header is absent.
export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set) => ({
      activeWorkspaceId: null,
      setActiveWorkspaceId: (workspaceId) => set({ activeWorkspaceId: workspaceId }),
      clearActiveWorkspaceId: () => set({ activeWorkspaceId: null }),
    }),
    { name: "content-studio-workspace" },
  ),
);
