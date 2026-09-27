import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "ghost" | "outline";
type Size = "sm" | "md" | "lg";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

const base =
  "inline-flex items-center justify-center font-medium rounded-xl transition " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 " +
  "disabled:opacity-50 disabled:cursor-not-allowed";

const variants: Record<Variant, string> = {
  primary: "bg-accent-600 text-white hover:bg-accent-700 active:scale-[0.98] shadow-sm",
  ghost: "text-ink-600 hover:bg-ink-100 dark:text-ink-300 dark:hover:bg-ink-800",
  outline:
    "border border-ink-200 text-ink-800 hover:bg-ink-100 dark:border-ink-600 dark:text-ink-100 dark:hover:bg-ink-800",
};

const sizes: Record<Size, string> = {
  sm: "h-9 px-3 text-sm",
  md: "h-11 px-4 text-base",
  lg: "h-14 px-6 text-lg",
};

export function Button({ variant = "primary", size = "md", className, ...rest }: Props) {
  return <button {...rest} className={cn(base, variants[variant], sizes[size], className)} />;
}
