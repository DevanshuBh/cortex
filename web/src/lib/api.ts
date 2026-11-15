import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./api-types";
import { tokenStore } from "./auth";
import { config } from "./config";
import { ApiError, type Problem } from "./errors";

export type Schemas = components["schemas"];
export type Document = Schemas["Document"];
export type Answer = Schemas["Answer"];
export type Task = Schemas["Task"];
export type EvidenceItem = Schemas["EvidenceItem"];
export type GraphPath = Schemas["GraphPathOut"];
export type Chunk = Schemas["ChunkOut"];
export type Usage = Schemas["Usage"];
export type EvalRun = Schemas["EvalRun"];

const auth: Middleware = {
  onRequest({ request }) {
    const token = tokenStore.get();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  async onResponse({ response }) {
    if (!response.ok) {
      let problem: Problem = { title: response.statusText || "Error", status: response.status };
      try {
        problem = (await response.clone().json()) as Problem;
      } catch {
        /* not JSON */
      }
      throw new ApiError(response.status, problem);
    }
    return response;
  },
};

export const api = createClient<paths>({ baseUrl: config.apiUrl });
api.use(auth);

/** Unwrap an openapi-fetch result; errors were already thrown by the middleware. */
export function data<T>(res: { data?: T }): T {
  if (res.data === undefined) throw new Error("empty response");
  return res.data;
}

export async function uploadToPresignedUrl(
  url: string,
  file: File,
  headers: Record<string, string>,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  // XMLHttpRequest, not fetch: fetch has no upload progress events.
  await new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => (xhr.status < 300 ? resolve() : reject(new Error(`upload failed (${xhr.status})`)));
    xhr.onerror = () => reject(new TypeError("network error during upload"));
    signal?.addEventListener("abort", () => {
      xhr.abort();
      reject(new DOMException("aborted", "AbortError"));
    });
    xhr.send(file);
  });
}
