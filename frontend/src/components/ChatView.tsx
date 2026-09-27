import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { MessageList } from "@/components/MessageList";
import { turnsToMessages } from "@/lib/messages";
import type { TurnEntry } from "@/hooks/useSession";
import { t } from "@/i18n";

/** Chat view: thread of turns + text box. */
export function ChatView({
  turns,
  draft,
  setDraft,
  onSend,
  disabled,
}: {
  turns: TurnEntry[];
  draft: string;
  setDraft: (s: string) => void;
  onSend: () => void;
  disabled: boolean;
}) {
  return (
    <Card className="flex-1 flex flex-col min-h-[60vh]">
      <MessageList
        messages={turnsToMessages(turns)}
        live
        className="flex-1 p-4"
        empty={<p className="text-sm text-ink-400 text-center py-8">{t("chat.empty")}</p>}
      />
      <div className="border-t border-ink-200 dark:border-ink-800 p-3 flex items-end gap-2">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSend();
            }
          }}
          rows={1}
          placeholder={t("chat.placeholder")}
          className="flex-1 resize-none rounded-xl border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500"
        />
        <Button onClick={onSend} disabled={disabled || !draft.trim()}>
          {t("chat.send")}
        </Button>
      </div>
    </Card>
  );
}
