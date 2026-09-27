import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { PhotoOcr } from "@/components/PhotoOcr";
import { humanError } from "@/hooks/useSession";
import { Notice } from "@/components/Notice";
import { useCapabilities } from "@/lib/capabilities";
import {
  createBook,
  fetchBook,
  fetchBooks,
  type BookDetail,
  type BookMeta,
  type Lang,
  type SessionConfig,
} from "@/lib/api";
import { LS_USER, LS_LANG } from "@/lib/storage";
import { t } from "@/i18n";

export default function BooksPage() {
  const nav = useNavigate();
  const user = localStorage.getItem(LS_USER);
  const lang = localStorage.getItem(LS_LANG) as Lang | null;
  useEffect(() => {
    if (!user || !lang) nav("/");
  }, [user, lang, nav]);
  if (!user || !lang) return null;
  return <BooksInner user={user} lang={lang} />;
}

function BooksInner({ user, lang }: { user: string; lang: Lang }) {
  const nav = useNavigate();
  const [books, setBooks] = useState<BookMeta[] | null>(null);
  const [selected, setSelected] = useState<BookDetail | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchBooks(user, lang)
      .then((b) => !cancelled && setBooks(b))
      .catch((e) => !cancelled && (setErr(humanError(e)), setBooks([])));
    return () => {
      cancelled = true;
    };
  }, [user, lang]);

  const open = async (slug: string) => {
    setErr(null);
    setBusy(true);
    try {
      setSelected(await fetchBook(user, lang, slug));
    } catch (e) {
      setErr(humanError(e));
    } finally {
      setBusy(false);
    }
  };

  const onNew = async () => {
    const title = newTitle.trim();
    if (!title) return;
    setErr(null);
    setBusy(true);
    try {
      const book = await createBook(user, lang, title);
      setNewTitle("");
      setBooks((prev) => [
        {
          slug: book.slug,
          title: book.title,
          page: book.page,
          status: book.status,
          sessions: book.sessions,
          updated: book.updated,
        },
        ...(prev ?? []),
      ]);
      setSelected(book);
    } catch (e) {
      setErr(humanError(e));
    } finally {
      setBusy(false);
    }
  };

  if (selected) {
    return (
      <BookStart
        user={user}
        lang={lang}
        book={selected}
        onBack={() => setSelected(null)}
        onStart={(cfg) => nav("/talk", { state: { autostart: cfg } })}
      />
    );
  }

  return (
    <div className="min-h-full mx-auto max-w-3xl px-4 py-6 space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-ink-900 dark:text-ink-50">{t("books.title")}</h1>
        <Button variant="ghost" size="sm" onClick={() => nav("/talk")}>
          {t("books.back")}
        </Button>
      </div>
      <p className="text-sm text-ink-500">{t("books.desc")}</p>
      {err && <p className="text-sm text-red-600">{err}</p>}

      {books === null ? (
        <p className="text-sm text-ink-400">{t("scenario.loading")}</p>
      ) : books.length === 0 ? (
        <p className="text-sm text-ink-500">{t("books.empty")}</p>
      ) : (
        <div className="space-y-2">
          {books.map((b) => (
            <button
              key={b.slug}
              disabled={busy}
              onClick={() => void open(b.slug)}
              className="w-full text-left rounded-xl border border-ink-200 dark:border-ink-700 px-4 py-3 hover:border-accent-400"
            >
              <p className="text-sm font-medium text-ink-900 dark:text-ink-50">📖 {b.title}</p>
              <p className="text-xs text-ink-500">
                {t("books.page")} {b.page} · {b.sessions} {t("books.sessions")}
                {b.updated && ` · ${b.updated}`}
              </p>
            </button>
          ))}
        </div>
      )}

      <div className="space-y-2 pt-3 border-t border-ink-100 dark:border-ink-800">
        <input
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          placeholder={t("books.new.placeholder")}
          className="w-full rounded-xl border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500"
        />
        <Button size="lg" disabled={busy || !newTitle.trim()} onClick={() => void onNew()}>
          {t("books.new")}
        </Button>
      </div>
    </div>
  );
}

/** Start of a book session: recap + photo or screenshot + text review + page.
 * Without a vision model the page text is pasted instead of photographed. */
function BookStart({
  user,
  lang,
  book,
  onBack,
  onStart,
}: {
  user: string;
  lang: Lang;
  book: BookDetail;
  onBack: () => void;
  onStart: (cfg: SessionConfig) => void;
}) {
  const { caps } = useCapabilities();
  const [text, setText] = useState("");
  const [page, setPage] = useState(String(book.page + 1));
  // Multi-page capture: each photo appends its text to the session text.
  const [adding, setAdding] = useState(false);
  const photoStep = caps.vision && (!text || adding);
  const pageNum = parseInt(page, 10);
  const canStart = !!text.trim() && Number.isFinite(pageNum) && pageNum > 0;

  // Append the text of a new photo to the captured text (blank line between).
  const onOcr = (newText: string) => {
    const t2 = newText.trim();
    if (t2) setText((prev) => (prev.trim() ? `${prev.trim()}\n\n${t2}` : t2));
    setAdding(false);
  };

  return (
    <div className="min-h-full mx-auto max-w-3xl px-4 py-6 space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-ink-900 dark:text-ink-50">📖 {book.title}</h1>
        <Button variant="ghost" size="sm" onClick={onBack}>
          {t("books.back")}
        </Button>
      </div>

      {book.sessions > 0 && book.summary && (
        <Card className="p-4">
          <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-2">{t("books.recap")}</h3>
          <p className="text-sm whitespace-pre-wrap">{book.summary}</p>
        </Card>
      )}

      {photoStep ? (
        <div className="space-y-3">
          <p className="text-sm text-ink-500">{t("books.photo.desc")}</p>
          <PhotoOcr user={user} lang={lang} onText={onOcr} />
          {adding && (
            <Button variant="ghost" size="sm" onClick={() => setAdding(false)}>
              {t("books.addCancel")}
            </Button>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-ink-500">
            {caps.vision ? t("ocr.review") : t("books.paste.desc")}
          </p>
          {!caps.vision && <Notice>{t("notice.noVision")}</Notice>}
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={10}
            placeholder={caps.vision ? undefined : t("books.paste.placeholder")}
            className="w-full resize-y rounded-xl border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500"
          />
          {caps.vision && (
            <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
              {t("books.addPage")}
            </Button>
          )}
          <div className="flex items-center gap-3">
            <label className="text-sm text-ink-600 dark:text-ink-300">
              {t("books.page.label")}
            </label>
            <input
              value={page}
              onChange={(e) => setPage(e.target.value)}
              inputMode="numeric"
              className="w-24 rounded-xl border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500"
            />
          </div>
          <Button
            size="lg"
            disabled={!canStart}
            onClick={() =>
              onStart({
                user,
                lang,
                mode: 8,
                bookSlug: book.slug,
                context: text.trim(),
                page: pageNum,
                subject: book.title,
              })
            }
          >
            {caps.pronunciation ? t("books.start") : t("books.start.talk")}
          </Button>
          {!caps.pronunciation && (
            <Notice>
              {caps.pronunciationOff === "timestamps" ? t("pron.timestamps") : t("notice.noStt")}
            </Notice>
          )}
        </div>
      )}

      {(book.vocab?.length ?? 0) > 0 && (
        <Card className="p-4">
          <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-2">
            {t("books.vocab")} ({book.vocab.length})
          </h3>
          <ul className="space-y-1 max-h-48 overflow-y-auto">
            {book.vocab.map((v, i) => (
              <li key={i} className="text-sm text-ink-800 dark:text-ink-100">
                {v.replace(/\*\*/g, "")}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
