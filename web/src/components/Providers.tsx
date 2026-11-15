"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { AuthProvider } from "@/lib/auth";
import { config } from "@/lib/config";
import { ApiError } from "@/lib/errors";
import { reportWebVitals } from "@/lib/vitals";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );
  const [ready, setReady] = useState(!config.demo);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    reportWebVitals();
    if (!config.demo) return;
    import("@/mocks/browser")
      .then(({ startDemo }) => startDemo())
      .then(() => setReady(true))
      .catch(() => setFailed(true));
  }, []);

  if (!ready) {
    return (
      <div role="status" className="grid min-h-dvh place-items-center p-6 text-center text-sm text-[var(--color-muted)]">
        {failed ? (
          <div>
            <p>The demo couldn&apos;t start in this browser (it needs service workers, which private windows sometimes block).</p>
            <button className="mt-3 font-medium text-[var(--color-accent)] underline underline-offset-2" onClick={() => location.reload()}>
              Try again
            </button>
          </div>
        ) : (
          "Starting the demo…"
        )}
      </div>
    );
  }
  return (
    <QueryClientProvider client={client}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}
