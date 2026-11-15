export const config = {
  apiUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  oidcAuthority: process.env.NEXT_PUBLIC_OIDC_AUTHORITY ?? "http://localhost:8080/realms/cortex",
  oidcClientId: process.env.NEXT_PUBLIC_OIDC_CLIENT_ID ?? "cortex-web",
  /** Demo mode: no back end; Mock Service Worker answers every API call with recorded data. */
  demo: process.env.NEXT_PUBLIC_DEMO === "1",
  /** Source repository, linked from the demo banner and About page. */
  repoUrl: process.env.NEXT_PUBLIC_REPO_URL ?? "",
  basePath: process.env.NEXT_PUBLIC_BASE_PATH ?? "",
} as const;
