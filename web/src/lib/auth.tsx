"use client";

import { InMemoryWebStorage, UserManager, WebStorageStateStore, type User } from "oidc-client-ts";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { config } from "./config";

export interface Session {
  token: string;
  userId: string;
  name: string;
  tenantId: string;
  roles: string[];
  isAdmin: boolean;
}

interface AuthState {
  session: Session | null;
  loading: boolean;
  login: () => Promise<void>;
  logout: () => Promise<void>;
  getToken: () => string | null;
}

const AuthContext = createContext<AuthState | null>(null);

let manager: UserManager | null = null;
export function userManager(): UserManager {
  if (!manager) {
    const origin = typeof window === "undefined" ? "http://localhost:3000" : window.location.origin;
    manager = new UserManager({
      authority: config.oidcAuthority,
      client_id: config.oidcClientId,
      redirect_uri: `${origin}${config.basePath}/auth/callback/`,
      post_logout_redirect_uri: `${origin}${config.basePath}/`,
      response_type: "code", // Authorization Code + PKCE (S256)
      scope: "openid profile email",
      // Tokens live in memory only — never localStorage (front-end standard: tokens in memory).
      userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
      automaticSilentRenew: false,
    });
  }
  return manager;
}

function decodeClaims(token: string): Record<string, unknown> {
  const part = token.split(".")[1] ?? "";
  const json = atob(part.replace(/-/g, "+").replace(/_/g, "/"));
  return JSON.parse(decodeURIComponent(escape(json))) as Record<string, unknown>;
}

export function sessionFromUser(user: User): Session {
  const claims = decodeClaims(user.access_token);
  const roles = ((claims.realm_access as { roles?: string[] } | undefined)?.roles ?? []).filter(
    (r) => r === "admin" || r === "member",
  );
  return {
    token: user.access_token,
    userId: String(claims.sub),
    name: String(user.profile.name ?? user.profile.preferred_username ?? "User"),
    tenantId: String(claims.tenant_id ?? ""),
    roles,
    isAdmin: roles.includes("admin"),
  };
}

const DEMO_SESSION: Session = {
  token: "demo",
  userId: "demo-user",
  name: "Demo Admin",
  tenantId: "k8s-docs",
  roles: ["member", "admin"],
  isAdmin: true,
};

// Kept outside React so non-component code (the API client, SSE) can read the current token.
let currentToken: string | null = null;
export const tokenStore = { get: () => currentToken };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(config.demo ? DEMO_SESSION : null);
  const [loading, setLoading] = useState(!config.demo);

  useEffect(() => {
    currentToken = session?.token ?? null;
  }, [session]);

  useEffect(() => {
    if (config.demo) return;
    const um = userManager();
    um.getUser()
      .then((u) => {
        if (u && !u.expired) setSession(sessionFromUser(u));
      })
      .finally(() => setLoading(false));
    const onLoaded = (u: User) => setSession(sessionFromUser(u));
    const onExpired = () => setSession(null);
    um.events.addUserLoaded(onLoaded);
    um.events.addAccessTokenExpired(onExpired);
    return () => {
      um.events.removeUserLoaded(onLoaded);
      um.events.removeAccessTokenExpired(onExpired);
    };
  }, []);

  const login = useCallback(async () => {
    if (config.demo) return;
    sessionStorage.setItem("cortex.returnTo", window.location.pathname + window.location.search);
    await userManager().signinRedirect();
  }, []);

  const logout = useCallback(async () => {
    if (config.demo) return;
    setSession(null);
    await userManager().signoutRedirect();
  }, []);

  const value = useMemo<AuthState>(
    () => ({ session, loading, login, logout, getToken: () => session?.token ?? null }),
    [session, loading, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
