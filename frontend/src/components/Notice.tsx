import type { ReactNode } from "react";

/** One discreet line explaining why something is off (a missing AI service). */
export function Notice({ children }: { children: ReactNode }) {
  return <p className="text-xs text-ink-500 dark:text-ink-400">{children}</p>;
}
