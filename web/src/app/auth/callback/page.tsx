"use client";

import { useEffect, useState } from "react";
import { userManager } from "@/lib/auth";
import { config } from "@/lib/config";
import { ErrorState, Spinner } from "@/components/ui";

export default function AuthCallback() {
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    userManager()
      .signinRedirectCallback()
      .then(() => {
        const returnTo = sessionStorage.getItem("cortex.returnTo") || `${config.basePath}/`;
        sessionStorage.removeItem("cortex.returnTo");
        // Client-side navigation keeps the in-memory token (a full reload would drop it).
        window.history.replaceState(null, "", returnTo);
        window.dispatchEvent(new PopStateEvent("popstate"));
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Sign-in failed"));
  }, []);
  return <div className="p-8">{error ? <ErrorState message={`Sign-in failed: ${error}`} /> : <Spinner label="Completing sign-in" />}</div>;
}
