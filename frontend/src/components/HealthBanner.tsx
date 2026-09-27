import { useCapabilities } from "@/lib/capabilities";
import { t } from "@/i18n";

const SERVICE_LABEL = {
  chat: "service.chat",
  stt: "service.stt",
  tts: "service.tts",
} as const;

/**
 * Non-blocking banner: the backend does not answer, or a configured AI service
 * does not respond. Services that are simply not configured are not faults and
 * are explained where they matter (see Notice), not here.
 */
export function HealthBanner() {
  const { health, unreachable, checking, refresh } = useCapabilities();

  const lines: string[] = [];
  if (unreachable) {
    lines.push(t("health.offline"));
  } else if (health) {
    for (const key of ["chat", "stt", "tts"] as const) {
      const s = health.services[key];
      if (s.configured && s.reachable === false) {
        const name = t(SERVICE_LABEL[key]);
        lines.push(`${name}: ${s.detail ?? t("health.notResponding")}`);
      }
    }
  }
  if (lines.length === 0) return null;

  return (
    <div
      role="status"
      className="bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200 text-sm px-4 py-2"
    >
      <div className="mx-auto max-w-5xl flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-center">
        <div className="space-y-0.5">
          {lines.map((l) => (
            <p key={l}>{l}</p>
          ))}
        </div>
        <button
          onClick={() => void refresh()}
          disabled={checking}
          className="rounded-lg border border-amber-400 px-2.5 py-0.5 text-xs font-medium disabled:opacity-60"
        >
          {checking ? t("health.checking") : t("error.retry")}
        </button>
      </div>
    </div>
  );
}
