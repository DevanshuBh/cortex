"use client";

import { clsx } from "clsx";
import { BarChart3, BookOpen, Info, LogOut, MessageSquareText, Moon, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useSyncExternalStore, type ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { config } from "@/lib/config";
import { useResearch } from "@/lib/research";
import { isRecorded } from "@/mocks/scenarios";
import { Button, Spinner } from "./ui";

const NAV = [
  { href: "/", label: "Research", icon: MessageSquareText, admin: false },
  { href: "/library/", label: "Library", icon: BookOpen, admin: false },
  { href: "/dashboard/", label: "Quality & cost", icon: BarChart3, admin: true },
  { href: "/about/", label: "About", icon: Info, admin: false },
];

function DemoBanner() {
  return (
    <div className="border-b border-[var(--color-border)] bg-[var(--color-accent-soft)] text-[13px]">
      <p className="mx-auto max-w-[1500px] px-4 py-2">
        <strong>Live demo.</strong> This page has no server behind it:{" "}
        {isRecorded
          ? "it replays answers recorded from the real system over the Kubernetes docs."
          : "a sample answer over the Kubernetes docs shows what the real system returns."}{" "}
        <Link href="/about/" className="font-medium text-[var(--color-accent)] underline underline-offset-2">How it works</Link>
        {config.repoUrl && (
          <>{" · "}<a href={config.repoUrl} className="font-medium text-[var(--color-accent)] underline underline-offset-2">Source code</a></>
        )}
      </p>
    </div>
  );
}

const themeListeners = new Set<() => void>();
function readTheme(): boolean {
  let stored: string | null = null;
  try {
    stored = localStorage.getItem("cortex.theme");
  } catch {
    /* storage blocked */
  }
  return stored ? stored === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
}

function ThemeToggle() {
  const dark = useSyncExternalStore(
    (cb) => {
      themeListeners.add(cb);
      return () => themeListeners.delete(cb);
    },
    readTheme,
    () => false,
  );
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dark]);
  const toggle = () => {
    try {
      localStorage.setItem("cortex.theme", dark ? "light" : "dark");
    } catch {
      /* ignore */
    }
    themeListeners.forEach((l) => l());
  };
  return (
    <Button variant="ghost" size="sm" onClick={toggle} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>
      {dark ? <Sun aria-hidden className="h-4 w-4" /> : <Moon aria-hidden className="h-4 w-4" />}
    </Button>
  );
}

function ConnectionDot() {
  const state = useResearch((s) => s.connection);
  if (state === "closed") return null;
  const label = { connecting: "Connecting", open: "Live", reconnecting: "Reconnecting" }[state];
  return (
    <span role="status" className="flex items-center gap-1.5 text-xs text-[var(--color-muted)]">
      <span aria-hidden className={clsx("h-2 w-2 rounded-full", state === "open" ? "bg-[var(--color-success)]" : "animate-pulse bg-[var(--color-warning)]")} />
      {label}
    </span>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { session, loading, login, logout } = useAuth();
  const pathname = usePathname();

  if (pathname.includes("/auth/callback")) return <>{children}</>;
  if (loading) {
    return <div className="grid min-h-dvh place-items-center"><Spinner label="Signing in" /></div>;
  }
  if (!session) {
    return (
      <main className="grid min-h-dvh place-items-center p-6">
        <div className="max-w-sm text-center">
          <h1 className="text-2xl font-semibold">CORTEX</h1>
          <p className="mt-2 text-sm text-[var(--color-muted)]">
            Ask questions about your team&apos;s documents and get answers that cite their sources.
          </p>
          <Button variant="primary" className="mt-6 w-full" onClick={login}>Sign in</Button>
        </div>
      </main>
    );
  }
  const current = pathname.replace(config.basePath, "") || "/";
  return (
    <div className="flex min-h-dvh flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:bg-[var(--color-surface)] focus:p-2">
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-[var(--color-border)] bg-[var(--color-surface)]/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1500px] items-center gap-3 px-4">
          <Link href="/" className="font-semibold tracking-tight">CORTEX</Link>
          {config.demo && <span className="rounded bg-[var(--color-accent-soft)] px-1.5 text-[11px] font-medium text-[var(--color-accent)]">demo</span>}
          <nav aria-label="Main" className="ml-2 flex items-center gap-1 overflow-x-auto">
            {NAV.filter((n) => !n.admin || session.isAdmin).map(({ href, label, icon: Icon }) => {
              const active = href === "/" ? current === "/" : current.startsWith(href);
              return (
                <Link key={href} href={href} aria-label={label} aria-current={active ? "page" : undefined}
                  className={clsx("flex items-center gap-1.5 whitespace-nowrap rounded-[var(--radius-md)] px-3 py-1.5 text-sm",
                    active ? "bg-[var(--color-accent-soft)] text-[var(--color-accent)]" : "text-[var(--color-muted)] hover:bg-[var(--color-surface-2)]")}>
                  <Icon aria-hidden className="h-4 w-4" />
                  <span className="hidden sm:inline">{label}</span>
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <ConnectionDot />
            <ThemeToggle />
            <span className="hidden text-right text-xs leading-tight md:block">
              <span className="block font-medium">{session.name}</span>
              <span className="block text-[var(--color-muted)]">{session.tenantId}{session.isAdmin ? " · admin" : ""}</span>
            </span>
            {!config.demo && (
              <Button variant="ghost" size="sm" onClick={logout} aria-label="Sign out"><LogOut aria-hidden className="h-4 w-4" /></Button>
            )}
          </div>
        </div>
      </header>
      {config.demo && <DemoBanner />}
      <main id="main" className="mx-auto w-full max-w-[1500px] flex-1 px-4 py-4">{children}</main>
    </div>
  );
}
