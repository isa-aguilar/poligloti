import { Card } from "@/components/Card";
import { t } from "@/i18n";
import type { TurnEntry } from "@/hooks/useSession";
import type { Correction, VocabItem } from "@/lib/api";

interface Props {
  /** All turns of the current session. A new session remounts with none. */
  turns: TurnEntry[];
}

/**
 * Accumulates the whole session: every correction and every new word (newest
 * first, words deduplicated by term), plus the follow-up of the last turn.
 * Derived from `turns`, so it resets with the session and needs no own state.
 */
export function SidePanel({ turns }: Props) {
  const corrections: Correction[] = [];
  const vocab: VocabItem[] = [];
  const seen = new Set<string>();
  for (let i = turns.length - 1; i >= 0; i--) {
    corrections.push(...turns[i].corrections);
    for (const v of turns[i].new_vocab) {
      const key = v.term.trim().toLowerCase();
      if (!key || seen.has(key)) continue;
      seen.add(key);
      vocab.push(v);
    }
  }
  const followup = turns.length > 0 ? turns[turns.length - 1].suggested_followup : "";

  if (corrections.length === 0 && vocab.length === 0 && !followup) {
    return <Card className="p-4 text-sm text-ink-500 dark:text-ink-400">{t("talk.empty")}</Card>;
  }

  return (
    <div className="space-y-3">
      {followup && (
        <Card className="p-4">
          <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-2">
            {t("talk.followup")}
          </h3>
          <p className="text-sm">{followup}</p>
        </Card>
      )}

      {corrections.length > 0 && (
        <Card className="p-4">
          <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-2">
            {t("talk.corrections")} ({corrections.length})
          </h3>
          <ul className="space-y-2 max-h-[40vh] overflow-y-auto">
            {corrections.map((c, i) => (
              <li key={i} className="text-sm">
                <span className="line-through text-red-500/80">{c.original}</span>{" "}
                <span aria-hidden>→</span>{" "}
                <span className="text-green-700 dark:text-green-400 font-medium">
                  {c.corrected}
                </span>
                {c.note && <p className="text-xs text-ink-500 mt-0.5">{c.note}</p>}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {vocab.length > 0 && (
        <Card className="p-4">
          <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-2">
            {t("talk.vocab")} ({vocab.length})
          </h3>
          <ul className="space-y-2 max-h-[40vh] overflow-y-auto">
            {vocab.map((v) => (
              <li key={v.term} className="text-sm">
                <span className="font-semibold">{v.term}</span>
                {v.translation && <span className="text-ink-500">: {v.translation}</span>}
                {v.example && <p className="text-xs italic text-ink-500 mt-0.5">{v.example}</p>}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
