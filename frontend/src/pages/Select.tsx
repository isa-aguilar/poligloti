import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchProfiles, fetchVoices, type Lang, type LanguageInfo, type Profile } from "@/lib/api";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { getLocale, t } from "@/i18n";
import { cn } from "@/lib/cn";
import { UiLangToggle } from "@/components/UiLangToggle";
import { NewLearnerForm } from "@/components/NewLearnerForm";
import { flagFor, langLabel } from "@/lib/lang";
import { LS_USER, LS_LANG } from "@/lib/storage";

function LangButton({
  lang,
  catalog,
  selected,
  primary,
  onSelect,
}: {
  lang: Lang;
  catalog: LanguageInfo[];
  selected: boolean;
  primary: boolean;
  onSelect: (l: Lang) => void;
}) {
  return (
    <button
      onClick={() => onSelect(lang)}
      className={cn(
        "h-16 rounded-2xl border text-base font-medium",
        "flex items-center justify-center gap-2 transition",
        selected
          ? "border-accent-500 bg-accent-500/10 text-accent-700"
          : "border-ink-200 hover:border-ink-400 text-ink-800 dark:border-ink-600 dark:text-ink-100",
      )}
    >
      <span className="text-2xl">{flagFor(lang)}</span>
      <span>{langLabel(lang, catalog)}</span>
      {primary && <span className="text-[10px] uppercase tracking-wider text-ink-400">★</span>}
    </button>
  );
}

export default function SelectPage() {
  const nav = useNavigate();
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [langs, setLangs] = useState<LanguageInfo[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const initialUser = localStorage.getItem(LS_USER);
  const [user, setUser] = useState<string | null>(initialUser);
  const [pickedLang, setLang] = useState<Lang | null>(
    (localStorage.getItem(LS_LANG) as Lang | null) ?? null,
  );
  // Only to repaint when the UI language changes (t() is not a hook).
  const [, setUiLang] = useState(getLocale());
  // "Add learner" form, when there are profiles already (with none it is
  // shown directly).
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    fetchProfiles()
      .then((data) => setProfiles(data))
      .catch((e) => setErr((e as Error).message));
    // The language catalog rules: EVERY supported language is offered to
    // everyone. If /voices fails, the list falls back to the profile's (below).
    fetchVoices()
      .then((v) => setLangs(v.languages ?? []))
      .catch(() => setLangs([]));
  }, []);

  const activeProfile = useMemo(
    () => profiles?.find((p) => p.user === user) ?? null,
    [profiles, user],
  );

  // When a profile is picked, suggest its primary language if none is chosen.
  // It is NOT reset when another is picked: anyone can start any supported
  // language, and the backend creates the new language's data on its own.
  const lang: Lang | null = pickedLang ?? activeProfile?.primary_language ?? null;

  // Offered languages: all the supported ones. languages_studied does not
  // filter, it orders: the learner's own first, the ones to try below.
  const { mine, others } = useMemo(() => {
    if (!activeProfile) return { mine: [] as Lang[], others: [] as Lang[] };
    const all: Lang[] = langs.length ? langs.map((l) => l.code) : activeProfile.languages_studied;
    const known = new Set<Lang>([
      ...activeProfile.languages_studied,
      ...(activeProfile.languages_started ?? []),
    ]);
    const rank = (l: Lang) =>
      l === activeProfile.primary_language
        ? 0
        : activeProfile.languages_studied.includes(l)
          ? 1
          : 2;
    return {
      mine: all.filter((l) => known.has(l)).sort((a, b) => rank(a) - rank(b)),
      others: all.filter((l) => !known.has(l)),
    };
  }, [activeProfile, langs]);

  const onCreated = async (newUser: string, newLang: Lang) => {
    try {
      setProfiles(await fetchProfiles());
    } catch (e) {
      setErr((e as Error).message);
    }
    setUser(newUser);
    setLang(newLang);
    setAdding(false);
  };

  const showForm = profiles !== null && (profiles.length === 0 || adding);

  const start = () => {
    if (!user || !lang) return;
    localStorage.setItem(LS_USER, user);
    localStorage.setItem(LS_LANG, lang);
    nav("/talk");
  };

  return (
    <div className="min-h-full flex flex-col items-center justify-center px-4 py-10">
      <div className="w-full max-w-md space-y-6">
        <div className="flex justify-end">
          <UiLangToggle onChange={setUiLang} />
        </div>
        <header className="text-center">
          <h1 className="text-3xl font-semibold tracking-tight text-ink-900 dark:text-ink-50">
            {t("select.heading")}
          </h1>
          <p className="mt-2 text-ink-600 dark:text-ink-400">{t("app.subtitle")}</p>
        </header>

        <Card className="p-6 space-y-6">
          <section>
            <h2 className="text-sm font-medium text-ink-600 dark:text-ink-400 mb-3">
              {t("select.who")}
            </h2>
            {err && (
              <p className="text-sm text-red-600">
                {t("select.error")}: {err}
              </p>
            )}
            {!profiles && !err && <p className="text-sm text-ink-400">{t("select.loading")}</p>}
            {showForm && (
              <div className="space-y-3">
                {profiles.length === 0 && (
                  <p className="text-sm text-ink-500">{t("newLearner.intro")}</p>
                )}
                <NewLearnerForm
                  catalog={langs}
                  onCreated={(u, l) => void onCreated(u, l)}
                  onCancel={profiles.length > 0 ? () => setAdding(false) : undefined}
                />
              </div>
            )}
            {profiles && profiles.length > 0 && !adding && (
              <div className="grid grid-cols-2 gap-3">
                {profiles.map((p) => (
                  <button
                    key={p.user}
                    onClick={() => setUser(p.user)}
                    className={cn(
                      "h-20 rounded-2xl border text-lg font-semibold capitalize",
                      "transition",
                      user === p.user
                        ? "border-accent-500 bg-accent-500/10 text-accent-700"
                        : "border-ink-200 hover:border-ink-400 text-ink-800 dark:border-ink-600 dark:text-ink-100",
                    )}
                  >
                    {p.name || p.user}
                  </button>
                ))}
                <button
                  onClick={() => setAdding(true)}
                  className="h-20 rounded-2xl border border-dashed border-ink-300 text-sm font-medium text-ink-500 hover:border-ink-400 dark:border-ink-600 dark:text-ink-300 transition"
                >
                  + {t("newLearner.add")}
                </button>
              </div>
            )}
          </section>

          {activeProfile && !showForm && (
            <section className="space-y-4">
              <div>
                <h2 className="text-sm font-medium text-ink-600 dark:text-ink-400 mb-3">
                  {mine.length && others.length ? t("select.lang.mine") : t("select.lang")}
                </h2>
                <div className="grid grid-cols-2 gap-3">
                  {mine.map((l) => (
                    <LangButton
                      key={l}
                      lang={l}
                      catalog={langs}
                      selected={lang === l}
                      primary={l === activeProfile.primary_language}
                      onSelect={setLang}
                    />
                  ))}
                </div>
              </div>

              {others.length > 0 && (
                <div>
                  <h2 className="text-sm font-medium text-ink-600 dark:text-ink-400 mb-3">
                    {t("select.lang.new")}
                  </h2>
                  <div className="grid grid-cols-2 gap-3">
                    {others.map((l) => (
                      <LangButton
                        key={l}
                        lang={l}
                        catalog={langs}
                        selected={lang === l}
                        primary={false}
                        onSelect={setLang}
                      />
                    ))}
                  </div>
                </div>
              )}
            </section>
          )}

          {!showForm && (
            <Button size="lg" className="w-full" disabled={!activeProfile || !lang} onClick={start}>
              {t("select.start")}
            </Button>
          )}
        </Card>
      </div>
    </div>
  );
}
