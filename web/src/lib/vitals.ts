import { onCLS, onINP, onLCP, type Metric } from "web-vitals";
import { config } from "./config";

/** Real-user Core Web Vitals, sent to the API (free replacement for CloudWatch RUM). */
export function reportWebVitals(): void {
  if (config.demo || typeof window === "undefined") return;
  const send = (m: Metric) => {
    const body = JSON.stringify({ name: m.name, value: m.value, rating: m.rating, path: location.pathname });
    navigator.sendBeacon?.(`${config.apiUrl}/v1/rum`, new Blob([body], { type: "application/json" }));
  };
  onLCP(send);
  onINP(send);
  onCLS(send);
  // JavaScript errors: counted (no stack or message leaves the browser — they could contain user data)
  const reportError = () => {
    const body = JSON.stringify({ name: "ERROR", value: 1, rating: "unknown" });
    navigator.sendBeacon?.(`${config.apiUrl}/v1/rum`, new Blob([body], { type: "application/json" }));
  };
  window.addEventListener("error", reportError);
  window.addEventListener("unhandledrejection", reportError);
}
