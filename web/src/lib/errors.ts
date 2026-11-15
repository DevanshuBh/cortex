/** RFC 9457 problem details from the API, mapped to messages people can act on. */
export interface Problem {
  title: string;
  status: number;
  detail?: string;
  errors?: { field: string; message: string }[];
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly problem: Problem,
  ) {
    super(problem.detail ?? problem.title);
    this.name = "ApiError";
  }

  get friendly(): string {
    switch (this.status) {
      case 401:
        return "Your session has expired. Please sign in again.";
      case 403:
        return "You don't have permission to do that.";
      case 404:
        return "That item no longer exists.";
      case 413:
        return this.problem.detail ?? "The file is too large.";
      case 415:
        return this.problem.detail ?? "That file type isn't supported.";
      case 422:
        return "Some fields need attention.";
      case 503:
        return "The service is temporarily unavailable. Please try again shortly.";
      default:
        return this.status >= 500 ? "Something went wrong on our side. Please try again." : this.message;
    }
  }

  fieldErrors(): Record<string, string> {
    return Object.fromEntries((this.problem.errors ?? []).map((e) => [e.field, e.message]));
  }
}

export function describeError(e: unknown): string {
  if (e instanceof ApiError) return e.friendly;
  if (e instanceof TypeError) return "Can't reach the server. Check your connection.";
  return e instanceof Error ? e.message : "Unexpected error";
}
