import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const config = [
  ...nextVitals,
  ...nextTs,
  { ignores: [".next/**", "out/**", "public/mockServiceWorker.js", "src/lib/api-types.ts", "playwright-report/**", "test-results/**"] },
  {
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "react/no-danger": "error",
    },
  },
];

export default config;
