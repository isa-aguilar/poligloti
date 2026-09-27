import { useState } from "react";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { UiLangToggle } from "@/components/UiLangToggle";
import { useCapabilities } from "@/lib/capabilities";
import { getLocale, t } from "@/i18n";

const OLLAMA_ENV = `AI_BASE_URL=http://localhost:11434/v1
AI_MODEL=llama3.2:3b`;

const OPENAI_ENV = `AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=sk-...
AI_MODEL=gpt-4o-mini`;

function Snippet({ title, code }: { title: string; code: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable (insecure context): the text can still be selected */
    }
  };
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-sm font-medium text-ink-700 dark:text-ink-200">{title}</h3>
        <button onClick={() => void copy()} className="text-xs text-accent-600 hover:underline">
          {copied ? t("setupRequired.copied") : t("setupRequired.copy")}
        </button>
      </div>
      <pre className="rounded-xl bg-ink-900 text-ink-50 text-xs p-3 overflow-x-auto select-all">
        {code}
      </pre>
    </div>
  );
}

/**
 * Shown instead of the app when the backend has no chat model configured:
 * nothing works without one, so the only useful thing is how to set it up.
 */
export default function SetupRequiredPage() {
  const { health, checking, refresh } = useCapabilities();
  const [, setUiLang] = useState(getLocale());
  const details = health
    ? (["chat", "stt", "tts"] as const)
        .map((k) => ({ key: k, detail: health.services[k].detail }))
        .filter((d): d is { key: "chat" | "stt" | "tts"; detail: string } => Boolean(d.detail))
    : [];

  return (
    <div className="min-h-full flex flex-col items-center justify-center px-4 py-10">
      <div className="w-full max-w-xl space-y-5">
        <div className="flex justify-end">
          <UiLangToggle onChange={setUiLang} />
        </div>
        <header className="text-center">
          <h1 className="text-2xl font-semibold tracking-tight text-ink-900 dark:text-ink-50">
            {t("setupRequired.title")}
          </h1>
          <p className="mt-2 text-ink-600 dark:text-ink-400">{t("setupRequired.intro")}</p>
        </header>

        <Card className="p-6 space-y-5">
          <div>
            <h2 className="text-sm font-medium text-ink-700 dark:text-ink-200 mb-2">
              {t("setupRequired.vars")}
            </h2>
            <ul className="text-sm space-y-1 text-ink-700 dark:text-ink-200">
              <li>
                <code className="font-mono">AI_BASE_URL</code>: {t("setupRequired.var.baseUrl")}
              </li>
              <li>
                <code className="font-mono">AI_MODEL</code>: {t("setupRequired.var.model")}
              </li>
              <li>
                <code className="font-mono">AI_API_KEY</code>: {t("setupRequired.var.apiKey")}
              </li>
            </ul>
          </div>

          <Snippet title={t("setupRequired.ollama")} code={OLLAMA_ENV} />
          <Snippet title={t("setupRequired.openai")} code={OPENAI_ENV} />

          <p className="text-sm text-ink-600 dark:text-ink-300">{t("setupRequired.restart")}</p>
          <p className="text-sm text-ink-500">{t("setupRequired.readme")}</p>

          {details.length > 0 && (
            <div className="rounded-xl border border-ink-200 dark:border-ink-700 p-3 space-y-1">
              {details.map((d) => (
                <p key={d.key} className="text-xs text-ink-600 dark:text-ink-300">
                  <span className="font-medium">{t(`service.${d.key}`)}</span>: {d.detail}
                </p>
              ))}
            </div>
          )}

          <Button size="lg" className="w-full" disabled={checking} onClick={() => void refresh()}>
            {checking ? t("health.checking") : t("setupRequired.check")}
          </Button>
        </Card>
      </div>
    </div>
  );
}
