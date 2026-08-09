import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AuthUser {
  id: string;
  email: string;
  display_name: string;
}

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: AuthUser | null;
  hasHydrated: boolean;
  setSession: (session: {
    accessToken: string;
    refreshToken: string;
    user: AuthUser;
  }) => void;
  clearSession: () => void;
  setHasHydrated: (value: boolean) => void;
}

// Phase 1 simplification: tokens live in localStorage via zustand's
// persist middleware. Fine for the local dev/demo build this phase
// targets; httpOnly-cookie-backed sessions (via a Next.js route handler
// proxying the FastAPI backend) are the hardening step before any real
// deployment, since localStorage tokens are readable by any script on
// the page (XSS exposure).
export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      hasHydrated: false,
      setSession: ({ accessToken, refreshToken, user }) =>
        set({ accessToken, refreshToken, user }),
      clearSession: () => set({ accessToken: null, refreshToken: null, user: null }),
      setHasHydrated: (value) => set({ hasHydrated: value }),
    }),
    {
      name: "content-studio-auth",
      // Tracks whether the persisted (localStorage) state has finished
      // loading, so consumers (the app shell's auth gate) can tell "no
      // token yet because we haven't checked" apart from "no token,
      // redirect to /login" — reading this from the store itself avoids
      // the react-hooks/set-state-in-effect lint violation a manual
      // mount-effect would trigger.
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true);
      },
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        user: state.user,
      }),
    },
  ),
);
