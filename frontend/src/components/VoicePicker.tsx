import { useEffect, useState } from "react";
import { fetchVoices, type Lang, type VoiceOption } from "@/lib/api";
import { useTeacherVoice } from "@/hooks/useTeacherVoice";
import { Notice } from "@/components/Notice";
import { getVoice, setBrowserVoice, setVoice } from "@/lib/storage";
import { langLabel } from "@/lib/lang";
import { t } from "@/i18n";

const selectClass =
  "rounded-lg border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 px-2 py-1.5 text-sm text-ink-800 dark:text-ink-100 focus:outline-none focus:ring-2 focus:ring-accent-500";

/**
 * Teacher voice picker (per learner and language), chosen before a session.
 * Lists the server voices when the server can speak this language, otherwise
 * the on-device browser voices. With neither, says the teacher will be text only.
 */
export function VoicePicker({ user, lang }: { user: string; lang: Lang }) {
  const [refresh, setRefresh] = useState(0);
  const voice = useTeacherVoice(user, lang, refresh);
  const [serverOptions, setServerOptions] = useState<VoiceOption[]>([]);
  const [serverValue, setServerValue] = useState<string>(getVoice(user, lang) ?? "");

  useEffect(() => {
    if (voice.source !== "server") return;
    let cancelled = false;
    fetchVoices()
      .then((v) => {
        if (!cancelled) setServerOptions(v.voices[lang] ?? []);
      })
      .catch(() => undefined); // offline: the picker simply does not show
    return () => {
      cancelled = true;
    };
  }, [lang, voice.source]);

  if (voice.source === "none") {
    return <Notice>{t("notice.noVoice").replace("{language}", langLabel(lang))}</Notice>;
  }

  if (voice.source === "browser") {
    if (voice.localVoices.length < 2 || !voice.browserVoice) return null;
    return (
      <label className="flex items-center gap-2 text-sm text-ink-500">
        {t("settings.voice")}
        <select
          value={voice.browserVoice.voiceURI}
          onChange={(e) => {
            setBrowserVoice(user, lang, e.target.value);
            setRefresh((n) => n + 1);
          }}
          className={selectClass}
        >
          {voice.localVoices.map((v) => (
            <option key={v.voiceURI} value={v.voiceURI}>
              {v.name}
            </option>
          ))}
        </select>
      </label>
    );
  }

  if (serverOptions.length < 2) return null;
  const current = serverValue || serverOptions[0].id;

  return (
    <label className="flex items-center gap-2 text-sm text-ink-500">
      {t("settings.voice")}
      <select
        value={current}
        onChange={(e) => {
          const v = e.target.value;
          setServerValue(v);
          // The language default is stored as "no preference".
          setVoice(user, lang, v === serverOptions[0].id ? null : v);
        }}
        className={selectClass}
      >
        {serverOptions.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
