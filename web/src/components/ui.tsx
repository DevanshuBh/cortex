"use client";

import { clsx } from "clsx";
import { AlertTriangle, Inbox, Loader2 } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
}>(function Button({ variant = "secondary", size = "md", loading, className, children, disabled, ...rest }, ref) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-[var(--radius-md)] font-medium transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-sm" : "h-10 px-4 text-sm",
        variant === "primary" && "bg-[var(--color-accent)] text-[var(--color-accent-fg)] hover:bg-[color-mix(in_srgb,var(--color-accent)_82%,black)]",
        variant === "secondary" &&
          "border border-[var(--color-border)] bg-[var(--color-surface)] hover:bg-[var(--color-surface-2)]",
        variant === "ghost" && "hover:bg-[var(--color-surface-2)]",
        variant === "danger" && "bg-[var(--color-danger)] text-white hover:bg-[color-mix(in_srgb,var(--color-danger)_82%,black)]",
        className,
      )}
      {...rest}
    >
      {loading && <Loader2 aria-hidden className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  );
});

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={clsx("rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)]", className)}>
      {children}
    </div>
  );
}

const TONES = {
  neutral: "bg-[var(--color-surface-2)] text-[var(--color-muted)]",
  accent: "bg-[var(--color-accent-soft)] text-[var(--color-accent)]",
  success: "bg-[color-mix(in_srgb,var(--color-success)_15%,transparent)] text-[var(--color-success)]",
  warning: "bg-[color-mix(in_srgb,var(--color-warning)_15%,transparent)] text-[var(--color-warning)]",
  danger: "bg-[color-mix(in_srgb,var(--color-danger)_15%,transparent)] text-[var(--color-danger)]",
} as const;

export function Badge({ tone = "neutral", children }: { tone?: keyof typeof TONES; children: ReactNode }) {
  return <span className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium", TONES[tone])}>{children}</span>;
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 text-sm text-[var(--color-muted)]">
      <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> {label}…
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <Inbox aria-hidden className="h-10 w-10 text-[var(--color-muted)]" />
      <h2 className="text-lg font-semibold">{title}</h2>
      {children && <div className="max-w-md text-sm text-[var(--color-muted)]">{children}</div>}
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-[var(--radius-md)] border border-[var(--color-danger)] p-4 text-sm">
      <AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-danger)]" />
      <div className="flex-1">{message}</div>
      {onRetry && <Button size="sm" onClick={onRetry}>Retry</Button>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={clsx("animate-pulse rounded bg-[var(--color-surface-2)]", className)} />;
}
