import { useAuthStore } from "@/stores/auth-store";
import { useWorkspaceStore } from "@/stores/workspace-store";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function parseErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body.detail ?? response.statusText;
  } catch {
    return response.statusText;
  }
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  auth?: boolean;
}

// Refresh tokens are single-use on the backend (each /auth/refresh call
// revokes the one it was given and issues a new pair) — several components
// fetching on the same page load can all hit a 401 within milliseconds of
// each other, so every concurrent 401 must await this *same* in-flight
// call rather than each independently spending the one refresh token,
// which would only let the first succeed and log everyone else out.
let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const { refreshToken, user } = useAuthStore.getState();
      if (!refreshToken || !user) return null;
      try {
        const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!response.ok) return null;
        const tokens = (await response.json()) as { access_token: string; refresh_token: string };
        useAuthStore.getState().setSession({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token, user });
        return tokens.access_token;
      } catch {
        return null;
      }
    })().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { auth = true, body, headers, ...rest } = options;
  const finalHeaders = new Headers(headers);

  let finalBody: BodyInit | undefined;
  if (body instanceof FormData) {
    finalBody = body;
  } else if (body !== undefined) {
    finalHeaders.set("Content-Type", "application/json");
    finalBody = JSON.stringify(body);
  }

  if (auth) {
    const token = useAuthStore.getState().accessToken;
    if (token) finalHeaders.set("Authorization", `Bearer ${token}`);
    const workspaceId = useWorkspaceStore.getState().activeWorkspaceId;
    if (workspaceId) finalHeaders.set("X-Workspace-Id", workspaceId);
  }

  let response = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    headers: finalHeaders,
    body: finalBody,
  });

  if (response.status === 401 && auth) {
    const newAccessToken = await refreshAccessToken();
    if (newAccessToken) {
      finalHeaders.set("Authorization", `Bearer ${newAccessToken}`);
      response = await fetch(`${API_BASE_URL}${path}`, {
        ...rest,
        headers: finalHeaders,
        body: finalBody,
      });
    } else {
      useAuthStore.getState().clearSession();
      if (typeof window !== "undefined") window.location.href = "/login";
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorMessage(response));
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const apiClient = {
  get: <T>(path: string, options?: RequestOptions) => request<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "POST", body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "PUT", body }),
  delete: <T>(path: string, options?: RequestOptions) => request<T>(path, { ...options, method: "DELETE" }),
};
