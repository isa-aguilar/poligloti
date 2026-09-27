import { cn } from "@/lib/cn";

interface Props {
  state: "idle" | "recording" | "busy";
  onClick: () => void;
  disabled?: boolean;
  labelIdle: string;
  labelRecording: string;
  labelBusy: string;
}

export function MicButton({
  state,
  onClick,
  disabled,
  labelIdle,
  labelRecording,
  labelBusy,
}: Props) {
  const label = state === "recording" ? labelRecording : state === "busy" ? labelBusy : labelIdle;
  return (
    <div className="flex flex-col items-center gap-4">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-label={label}
        className={cn(
          "relative h-40 w-40 rounded-full transition shadow-xl",
          "focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent-500/40",
          "disabled:opacity-60",
          state === "recording"
            ? "bg-red-500 ring-8 ring-red-200 animate-pulse"
            : "bg-accent-600 hover:bg-accent-700",
        )}
      >
        <svg
          viewBox="0 0 24 24"
          className="absolute inset-0 m-auto h-16 w-16 text-white"
          fill="currentColor"
          aria-hidden="true"
        >
          <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3z" />
          <path d="M19 11a1 1 0 1 0-2 0 5 5 0 0 1-10 0 1 1 0 1 0-2 0 7 7 0 0 0 6 6.93V21a1 1 0 1 0 2 0v-3.07A7 7 0 0 0 19 11z" />
        </svg>
      </button>
      <p className="text-center text-ink-600 dark:text-ink-400">{label}</p>
    </div>
  );
}
