import { useEffect, useRef, type ReactNode } from "react";
import type { Message } from "@/lib/messages";
import { cn } from "@/lib/cn";

/**
 * Conversation thread, newest at the bottom. Empty bubbles are skipped (an
 * opening has no learner text). With `live`, the list scrolls itself to follow
 * the newest message, also while the last reply grows during streaming, and an
 * empty last reply shows a typing indicator.
 */
export function MessageList({
  messages,
  live = false,
  empty,
  className,
}: {
  messages: Message[];
  live?: boolean;
  empty?: ReactNode;
  className?: string;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const last = messages.length > 0 ? messages[messages.length - 1] : null;
  const lastLen = last ? last.teacher.length + last.learner.length : 0;
  useEffect(() => {
    if (!live) return;
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [live, messages.length, lastLen]);

  return (
    <div ref={scrollRef} className={cn("overflow-y-auto space-y-4", className)}>
      {messages.length === 0 && empty}
      {messages.map((m) => {
        const typing = live && m === last && !m.teacher;
        return (
          <div key={m.id} className="space-y-2">
            {m.learner && (
              <div className="flex flex-col items-end gap-1">
                <div className="max-w-[80%] rounded-2xl bg-accent-600 text-white px-4 py-2 text-sm whitespace-pre-wrap">
                  {m.learner}
                </div>
                {(m.corrections?.length ?? 0) > 0 && (
                  <ul className="max-w-[80%] space-y-0.5 text-right">
                    {m.corrections!.map((c, i) => (
                      <li key={i} className="text-xs">
                        <span className="line-through text-red-500/80">{c.original}</span>{" "}
                        <span aria-hidden>→</span>{" "}
                        <span className="text-green-700 dark:text-green-400 font-medium">
                          {c.corrected}
                        </span>
                        {c.note && <span className="text-ink-500"> ({c.note})</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            {(m.teacher || typing) && (
              <div className="flex flex-col items-start gap-1">
                <div className="max-w-[80%] rounded-2xl bg-ink-100 dark:bg-ink-800 text-ink-900 dark:text-ink-50 px-4 py-2 text-sm whitespace-pre-wrap">
                  {typing ? (
                    <span className="animate-pulse text-ink-400" aria-hidden>
                      …
                    </span>
                  ) : (
                    m.teacher
                  )}
                </div>
                {m.teacherExtra}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
