import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      {...rest}
      className={cn(
        "rounded-2xl border border-ink-200 bg-white shadow-sm",
        "dark:border-ink-800 dark:bg-ink-800",
        className,
      )}
    />
  );
}
