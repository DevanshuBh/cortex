import { setupWorker } from "msw/browser";
import { config } from "@/lib/config";
import { handlers } from "./handlers";

const RELOAD_FLAG = "cortex.demo.reloaded";
const START_TIMEOUT_MS = 6000;

function timeout(ms: number): Promise<never> {
  return new Promise((_, reject) => setTimeout(() => reject(new Error("demo start timed out")), ms));
}

/**
 * Start the service worker that answers API calls in the static demo.
 *
 * On a first visit the worker can install without taking control of the page in time (slow phones, busy browsers),
 * which would leave the app waiting forever. Bound the wait, reload once — a registered worker controls the page
 * after a reload — and only then give up with an error the page can show.
 */
export async function startDemo(): Promise<void> {
  try {
    await Promise.race([
      setupWorker(...handlers).start({
        serviceWorker: { url: `${config.basePath}/mockServiceWorker.js` },
        onUnhandledRequest: "bypass",
        quiet: true,
      }),
      timeout(START_TIMEOUT_MS),
    ]);
    try {
      sessionStorage.removeItem(RELOAD_FLAG);
    } catch {
      /* storage blocked */
    }
  } catch (err) {
    let reloaded = true;
    try {
      reloaded = sessionStorage.getItem(RELOAD_FLAG) === "1";
      if (!reloaded) sessionStorage.setItem(RELOAD_FLAG, "1");
    } catch {
      /* storage blocked: don't risk a reload loop */
    }
    if (!reloaded) {
      location.reload();
      return new Promise(() => {}); // the page is going away
    }
    throw err;
  }
}
