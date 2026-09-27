import { getRate, getVoice } from "./storage";

export type Lang = "de" | "en" | "fr";

export type LessonMode = 1 | 2 | 3 | 4 | 5 | 7 | 9;
export type WriteAction = "talk" | "feedback" | "send";
export type SubMode = "email" | "chat";
export type Mode6Sub = "assessment" | "weekly_review" | "test";

export interface Profile {
  user: string;
  /** Display name from profile.md; falls back to the user id. */
  name?: string;
  primary_language: Lang;
  /** Declared in profile.md. Orders the language picker, does not filter it. */
  languages_studied: Lang[];
  /** Languages with a data folder, i.e. the ones actually started. */
  languages_started: Lang[];
  ui_language: string;
}

export interface Scenario {
  id: string; // "work/kpi-meeting"
  category: string; // "work" | "everyday" | a custom one
  title: string;
  description: string;
  level: string;
}

export interface ScenarioInfo {
  id: string;
  category: string;
  title: string;
  description: string;
  level: string;
  register: string;
  vocab: string[];
  phrases: string[];
}

export interface Correction {
  original: string;
  corrected: string;
  note?: string;
}

export interface VocabItem {
  term: string;
  translation?: string;
  example?: string;
}

export interface TurnResponse {
  session_id: string;
  turn: number;
  transcript: string;
  reply: string;
  corrections: Correction[];
  new_vocab: VocabItem[];
  suggested_followup: string;
  revised: string; // only filled by the mode 5 feedback action
  audio_url: string | null;
}

export interface SessionStartResponse {
  session_id: string;
  user: string;
  target_language: Lang;
  mode: number;
  system_prompt: string;
  scenario_info: ScenarioInfo | null;
  opening: TurnResponse | null;
  // The opening arrives through /turn/stream with kickoff (modes that open
  // talking, with defer_opening): first audio in ~2s instead of a full turn.
  opening_pending: boolean;
  reference_text: string | null; // mode 4: text to read
  weekly_review?: boolean;
  pairs: MinimalPair[] | null; // mode 4 pair_mode: pre-synthesized pairs
}

export interface SessionConfig {
  user: string;
  lang: Lang;
  mode: LessonMode | 6 | 8;
  scenario?: string; // mode 2
  context?: string; // mode 3 / mode 4 (pasted text) / mode 8 (page text)
  subMode?: SubMode | Mode6Sub; // mode 5 (email|chat) / mode 6 (assessment|weekly_review|test)
  subject?: string; // mode 5 subject / modes 3-4 title
  generate?: boolean; // mode 4: generate the text
  topic?: string; // mode 4: topic to generate from; mode 7: expressions theme
  bookSlug?: string; // mode 8: current book
  page?: number; // mode 8: page number being read
  topicId?: string; // mode 9: syllabus topic
  pairMode?: boolean; // mode 4: minimal pairs exercise
}

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------

// In dev: "/api" (Vite proxies to the backend and strips the prefix). The
// production build is served by the backend itself, so it calls root routes.
// VITE_API_BASE overrides both (e.g. a backend on another origin).
const BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? (import.meta.env.DEV ? "/api" : "");

// Timeouts: short calls fail fast; turns wait for speech-to-text plus a cold
// model, which on a CPU-only machine can take minutes (the backend's STT_TIMEOUT
// and AI_TIMEOUT). Without a limit, a hung backend leaves the UI "Thinking..." forever.
const T_SHORT_MS = 15_000;
const T_TURN_MS = 300_000;
const STREAM_IDLE_MS = 240_000;

/**
 * An HTTP error from the backend. AI service failures come as
 * `{detail, service, code}` with 503 (or 501 when the server cannot do it at
 * all); `detail` is written for the learner and is what the UI shows.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | null;
  readonly service: string | null;
  readonly code: string | null;

  constructor(status: number, detail: string | null, service: string | null, code: string | null) {
    super(detail ?? `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.service = service;
    this.code = code;
  }
}

async function toApiError(res: Response): Promise<ApiError> {
  const body = await res.text().catch(() => "");
  let detail: string | null = null;
  let service: string | null = null;
  let code: string | null = null;
  try {
    const data = JSON.parse(body) as { detail?: unknown; service?: unknown; code?: unknown };
    // FastAPI validation errors put a list in `detail`: not for the learner.
    if (typeof data.detail === "string") detail = data.detail;
    if (typeof data.service === "string") service = data.service;
    if (typeof data.code === "string") code = data.code;
  } catch {
    /* not JSON: keep the status only */
  }
  return new ApiError(res.status, detail, service, code);
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) throw await toApiError(res);
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Health and capabilities
// ---------------------------------------------------------------------------

interface ServiceBase {
  configured: boolean;
  /** Absent until the backend has probed the service. */
  reachable?: boolean;
  detail?: string;
}

export interface ChatService extends ServiceBase {
  vision: boolean;
}

export interface SttService extends ServiceBase {
  /** null: not known yet (learned on the first transcription). */
  word_timestamps: boolean | null;
}

export interface TtsService extends ServiceBase {
  /** Target languages with a server voice. */
  languages: string[];
}

export interface HealthResponse {
  status: "ok" | "degraded" | "setup_required";
  version?: string;
  services: {
    chat: ChatService;
    stt: SttService;
    tts: TtsService;
  };
  active_sessions?: number;
}

/** deep=true makes the backend probe every service again before answering. */
export async function fetchHealth(deep = false): Promise<HealthResponse> {
  const res = await fetch(`${BASE}/health${deep ? "?deep=1" : ""}`, {
    // A deep probe waits for each service (up to ~12s each on the backend).
    signal: AbortSignal.timeout(deep ? 45_000 : T_SHORT_MS),
  });
  return jsonOrThrow<HealthResponse>(res);
}

// ---------------------------------------------------------------------------
// Mode 4: read aloud and pronunciation
// ---------------------------------------------------------------------------
export type WordStatus = "ok" | "weak" | "miss";

export interface WordScore {
  text: string;
  status: WordStatus;
  heard: string | null;
  prob: number | null;
}

export interface ReadSummary {
  total: number;
  ok: number;
  weak: number;
  miss: number;
  accuracy: number;
}

export interface FlaggedWord {
  word: string;
  audio_url: string | null;
}

export interface ReadScoreResponse {
  session_id: string;
  heard_text: string;
  words: WordScore[];
  summary: ReadSummary;
  flagged: FlaggedWord[];
}

// --- Minimal pairs ---------------------------------------------------------
export interface MinimalPair {
  contrast: string;
  tip: string;
  words: [string, string];
  gloss: string;
  audio_urls: (string | null)[];
}

export interface PairVerdict {
  session_id: string;
  pair_index: number;
  status: "ok" | "same" | "unclear";
  heard_as: string | null;
  heard: string[];
}

export async function scorePair(
  session_id: string,
  pair_index: number,
  audio: Blob,
  filename = "pair.webm",
): Promise<PairVerdict> {
  const form = new FormData();
  form.append("session_id", session_id);
  form.append("pair_index", String(pair_index));
  form.append("audio", audio, filename);
  const res = await fetch(`${BASE}/pairs/score`, {
    method: "POST",
    body: form,
    signal: AbortSignal.timeout(T_TURN_MS),
  });
  return jsonOrThrow(res);
}

// ---------------------------------------------------------------------------
// Teacher voice and speech rate
// ---------------------------------------------------------------------------
export interface VoiceOption {
  id: string;
  label: string;
}

export interface LanguageInfo {
  code: Lang;
  name: string;
}

export interface VoicesResponse {
  voices: Record<string, VoiceOption[]>;
  /** Supported target languages, derived from the backend's config.LANGUAGES. */
  languages: LanguageInfo[];
  rates: Record<string, number>;
}

let voicesCache: VoicesResponse | null = null;

export async function fetchVoices(): Promise<VoicesResponse> {
  if (voicesCache) return voicesCache;
  const res = await fetch(`${BASE}/voices`, {
    signal: AbortSignal.timeout(T_SHORT_MS),
  });
  voicesCache = await jsonOrThrow<VoicesResponse>(res);
  return voicesCache;
}

// Current speech rate: sent with every turn, the backend applies it to the
// synthesis. Managed by RateToggle; null = normal.
let currentSpeechRate: number | null = null;

export function setSpeechRate(rate: number | null): void {
  currentSpeechRate = rate;
}

function appendSpeechRate(form: FormData): void {
  if (currentSpeechRate) form.append("speech_rate", String(currentSpeechRate));
}

// ---------------------------------------------------------------------------
// Profiles, scenarios, sessions and turns
// ---------------------------------------------------------------------------
export async function fetchProfiles(): Promise<Profile[]> {
  const res = await fetch(`${BASE}/profiles`, {
    signal: AbortSignal.timeout(T_SHORT_MS),
  });
  const data = await jsonOrThrow<{ profiles: Profile[] }>(res);
  return data.profiles;
}

export interface NewProfile {
  name: string;
  target_language: Lang;
  /** Why the learner studies the language; the teacher reads it. */
  goals?: string;
  ui_language?: string;
}

/** Create a learner. 409 if one with that name exists, 400 if invalid. */
export async function createProfile(
  profile: NewProfile,
): Promise<{ user: string; name: string; primary_language: Lang }> {
  const res = await fetch(`${BASE}/profiles`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile),
    signal: AbortSignal.timeout(T_SHORT_MS),
  });
  return jsonOrThrow(res);
}

export async function fetchScenarios(): Promise<Scenario[]> {
  const res = await fetch(`${BASE}/scenarios`, {
    signal: AbortSignal.timeout(T_SHORT_MS),
  });
  const data = await jsonOrThrow<{ scenarios: Scenario[] }>(res);
  return data.scenarios;
}

export async function startSession(config: SessionConfig): Promise<SessionStartResponse> {
  const body: Record<string, unknown> = {
    user_id: config.user,
    target_language: config.lang,
    mode: config.mode,
    // Modes that open talking stream their opening (kickoff).
    defer_opening: true,
  };
  // Learner voice settings (persisted in localStorage).
  const voice = getVoice(config.user, config.lang);
  if (voice) body.voice = voice;
  const rate = getRate(config.user);
  setSpeechRate(rate); // initial rate sent with the turns
  if (rate) body.speech_rate = rate;
  if (config.scenario) body.scenario = config.scenario;
  if (config.context) body.context = config.context;
  if (config.subMode) body.sub_mode = config.subMode;
  if (config.subject) body.subject = config.subject;
  if (config.generate) body.generate = config.generate;
  if (config.topic) body.topic = config.topic;
  if (config.bookSlug) body.book_slug = config.bookSlug;
  if (config.page) body.page = config.page;
  if (config.topicId) body.topic_id = config.topicId;
  if (config.pairMode) body.pair_mode = true;
  const res = await fetch(`${BASE}/session/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    // Some modes run a full model turn to open the session.
    signal: AbortSignal.timeout(T_TURN_MS),
  });
  return jsonOrThrow<SessionStartResponse>(res);
}

export async function sendTextTurn(
  session_id: string,
  text: string,
  action: WriteAction = "talk",
): Promise<TurnResponse> {
  const form = new FormData();
  form.append("session_id", session_id);
  form.append("text", text);
  form.append("action", action);
  appendSpeechRate(form);
  const res = await fetch(`${BASE}/turn`, {
    method: "POST",
    body: form,
    signal: AbortSignal.timeout(T_TURN_MS),
  });
  return jsonOrThrow<TurnResponse>(res);
}

export async function sendAudioTurn(
  session_id: string,
  audio: Blob,
  filename = "turn.webm",
): Promise<TurnResponse> {
  const form = new FormData();
  form.append("session_id", session_id);
  form.append("audio", audio, filename);
  appendSpeechRate(form);
  const res = await fetch(`${BASE}/turn`, {
    method: "POST",
    body: form,
    signal: AbortSignal.timeout(T_TURN_MS),
  });
  return jsonOrThrow<TurnResponse>(res);
}

// --- Streaming (SSE): conversational turn with audio per sentence ----------
export interface StreamMeta {
  turn: number;
  transcript: string;
  reply: string;
  corrections: Correction[];
  new_vocab: VocabItem[];
  suggested_followup: string;
  revised: string;
  audio_urls: string[];
  warnings: string[];
}

export interface StreamError {
  detail: string;
  code: string | null;
  service: string | null;
}

export interface StreamHandlers {
  onTranscript?: (text: string) => void;
  /** `url` is null when the server did not synthesize the sentence (no
   * text-to-speech for this language): `text` is still the sentence. */
  onAudio?: (url: string | null, text: string) => void;
  onMeta?: (meta: StreamMeta) => void;
  onDone?: () => void;
  onError?: (err: StreamError) => void;
}

/** POST to /turn/stream and dispatch the SSE events to the handlers.
 * `opts.signal` cancels from outside (barge-in): a deliberate cancel does NOT
 * throw, the function just returns. */
export async function streamTurn(
  session_id: string,
  payload: { text?: string; audio?: Blob; filename?: string; kickoff?: boolean },
  handlers: StreamHandlers,
  opts: { signal?: AbortSignal } = {},
): Promise<void> {
  const form = new FormData();
  form.append("session_id", session_id);
  if (payload.kickoff) {
    form.append("kickoff", "1");
  } else if (payload.audio) {
    form.append("audio", payload.audio, payload.filename ?? "turn.webm");
  } else if (payload.text) {
    form.append("text", payload.text);
  }
  appendSpeechRate(form);
  // Idle watchdog: if STREAM_IDLE_MS pass without a frame from the backend
  // (model server hung mid-stream), abort with TimeoutError instead of leaving
  // the state in "Thinking..." forever.
  const ac = new AbortController();
  let timedOut = false;
  if (opts.signal?.aborted) return;
  opts.signal?.addEventListener("abort", () => ac.abort(), { once: true });
  let watchdog: ReturnType<typeof setTimeout> | undefined;
  const arm = () => {
    clearTimeout(watchdog);
    watchdog = setTimeout(() => {
      timedOut = true;
      ac.abort();
    }, STREAM_IDLE_MS);
  };
  arm();
  try {
    const res = await fetch(`${BASE}/turn/stream`, {
      method: "POST",
      body: form,
      signal: ac.signal,
    });
    if (!res.ok) throw await toApiError(res);
    if (!res.body) throw new ApiError(res.status, null, null, null);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      arm();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const line = frame.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        let ev: { type: string; [k: string]: unknown };
        try {
          ev = JSON.parse(line.slice(5).trim());
        } catch {
          continue;
        }
        switch (ev.type) {
          case "transcript":
            handlers.onTranscript?.(ev.text as string);
            break;
          case "audio":
            handlers.onAudio?.((ev.url as string | null) ?? null, (ev.text as string) ?? "");
            break;
          case "meta":
            handlers.onMeta?.(ev as unknown as StreamMeta);
            break;
          case "done":
            handlers.onDone?.();
            break;
          case "error":
            handlers.onError?.({
              detail: String(ev.detail ?? ""),
              code: typeof ev.code === "string" ? ev.code : null,
              service: typeof ev.service === "string" ? ev.service : null,
            });
            break;
        }
      }
    }
  } catch (e) {
    if (timedOut) throw new DOMException("stream idle", "TimeoutError");
    if (opts.signal?.aborted) return; // deliberate cancel (barge-in): not an error
    throw e;
  } finally {
    clearTimeout(watchdog);
  }
}

// Mode 4: upload the read-aloud recording and get the per-word scoring.
export async function scoreReading(
  session_id: string,
  audio: Blob,
  filename = "read.webm",
): Promise<ReadScoreResponse> {
  const form = new FormData();
  form.append("session_id", session_id);
  form.append("audio", audio, filename);
  const res = await fetch(`${BASE}/read/score`, {
    method: "POST",
    body: form,
    signal: AbortSignal.timeout(T_TURN_MS),
  });
  return jsonOrThrow<ReadScoreResponse>(res);
}

// ---------------------------------------------------------------------------
// Mode 6: "My progress" screen
// ---------------------------------------------------------------------------
export interface ProgressDim {
  key: string;
  label: string;
  score: number | null;
}

export interface WeeklyReview {
  week: string;
  text: string;
}

export interface ProgressHistoryPoint {
  date: string;
  scores: Record<string, number>;
  note: string;
}

export interface ProgressData {
  user: string;
  lang: Lang;
  has_data: boolean;
  /** Not the same as has_data: there can be a tracker without an assessment. */
  has_assessment: boolean;
  cefr: string;
  next_cefr: string | null;
  target_cefr: string | null;
  avg_score: number;
  levelup_eligible: boolean;
  dims: ProgressDim[];
  active_errors: string[];
  resolved_errors: string[];
  focus: string;
  milestones: string[];
  weekly_reviews: WeeklyReview[];
  expressions_count: number;
  /** Time series of the 8 skills, oldest first. */
  history: ProgressHistoryPoint[];
  updated: string | null;
}

export async function fetchProgress(user: string, lang: Lang, ui?: string): Promise<ProgressData> {
  const q = ui ? `?ui=${encodeURIComponent(ui)}` : "";
  const res = await fetch(`${BASE}/progress/${user}/${lang}${q}`, {
    // Translating the panel to the UI language may call the model the first time.
    signal: AbortSignal.timeout(60_000),
  });
  return jsonOrThrow<ProgressData>(res);
}

// Best-effort close when the tab closes (uses the right BASE in dev and prod).
export function endSessionBeacon(session_id: string): void {
  const body = JSON.stringify({ session_id });
  navigator.sendBeacon?.(`${BASE}/session/end`, new Blob([body], { type: "application/json" }));
}

export interface SessionEndResponse {
  /** Only in assessment sessions (mode 6, assessment). */
  cefr?: string;
  assessment_summary?: string;
  strengths?: string[];
  weaknesses?: string[];
  focus?: string;
  closed: string;
  turns: number;
  progress_updated?: boolean;
  vocab_added?: number;
  expressions_added?: number;
  tracker_updated?: boolean;
  // Post-session report computed by the analyst pass.
  summary?: string;
  session_vocab?: VocabItem[];
  missed_opportunities?: string[];
  /** Set when the end-of-session analysis failed (the turns are saved anyway). */
  analysis_error?: string;
}

export async function endSession(
  session_id: string,
  /** Mode 8: the page where the learner actually stopped. Without it the start page is kept. */
  end_page?: number,
): Promise<SessionEndResponse> {
  const res = await fetch(`${BASE}/session/end`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(end_page ? { session_id, end_page } : { session_id }),
    // The post-session pass (summary + tracker) is several model calls.
    signal: AbortSignal.timeout(T_TURN_MS),
  });
  return jsonOrThrow<SessionEndResponse>(res);
}

// ---------------------------------------------------------------------------
// Session history ("My sessions")
// ---------------------------------------------------------------------------
export interface SessionListItem {
  id: string;
  /** YYYY-MM-DD */
  day: string;
  /** HH:MM */
  started: string;
  mode: number | null;
  label: string;
  turns: number;
  preview: string;
  has_notes: boolean;
}

export interface SessionTurn {
  /** HH:MM:SS */
  time: string;
  /** Empty for an opening or a read-aloud turn. */
  learner: string;
  teacher: string;
  corrections: Correction[];
  new_vocab: VocabItem[];
  suggestion: string;
}

/** The analyst's report saved when the session was closed. */
export interface SessionNotes {
  summary?: string;
  session_vocab?: VocabItem[];
  missed_opportunities?: string[];
  analysis_error?: string | null;
  cefr?: string;
  assessment_summary?: string;
  strengths?: string[];
  weaknesses?: string[];
  focus?: string;
}

export interface SessionDetail {
  id: string;
  day: string;
  started: string;
  mode: number | null;
  label: string;
  turns: SessionTurn[];
  notes: SessionNotes | null;
}

export async function fetchSessions(user: string, lang: Lang): Promise<SessionListItem[]> {
  const res = await fetch(`${BASE}/sessions/${user}/${lang}`, {
    signal: AbortSignal.timeout(T_SHORT_MS),
  });
  const data = await jsonOrThrow<{ sessions: SessionListItem[] }>(res);
  return data.sessions ?? [];
}

export async function fetchSessionDetail(
  user: string,
  lang: Lang,
  id: string,
): Promise<SessionDetail> {
  const res = await fetch(`${BASE}/sessions/${user}/${lang}/${encodeURIComponent(id)}`, {
    signal: AbortSignal.timeout(T_SHORT_MS),
  });
  return jsonOrThrow<SessionDetail>(res);
}

// ---------------------------------------------------------------------------
// Spaced repetition (FSRS)
// ---------------------------------------------------------------------------
export interface SrsCard {
  term: string;
  translation: string;
  example: string;
  due: string;
}

export interface SrsDueResponse {
  due: SrsCard[];
  total_cards: number;
  due_count: number;
}

export async function fetchSrsDue(user: string, lang: Lang): Promise<SrsDueResponse> {
  const res = await fetch(`${BASE}/srs/${user}/${lang}/due`, {
    signal: AbortSignal.timeout(T_SHORT_MS),
  });
  return jsonOrThrow<SrsDueResponse>(res);
}

/** rating: 1 Again, 2 Hard, 3 Good, 4 Easy (FSRS/Anki scale). */
export async function reviewSrsCard(
  user: string,
  lang: Lang,
  term: string,
  rating: 1 | 2 | 3 | 4,
): Promise<{ term: string; next_due: string }> {
  const res = await fetch(`${BASE}/srs/${user}/${lang}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ term, rating }),
    signal: AbortSignal.timeout(T_SHORT_MS),
  });
  return jsonOrThrow(res);
}

export async function syncSrs(user: string, lang: Lang): Promise<{ added: number; total: number }> {
  const res = await fetch(`${BASE}/srs/${user}/${lang}/sync`, {
    method: "POST",
    signal: AbortSignal.timeout(T_SHORT_MS),
  });
  return jsonOrThrow(res);
}

// ---------------------------------------------------------------------------
// Graded stories (chaptered reader)
// ---------------------------------------------------------------------------
export interface StoryMeta {
  slug: string;
  title: string;
  level: string;
  chapters: number;
  updated?: string;
}

export async function fetchStories(user: string, lang: Lang): Promise<StoryMeta[]> {
  const res = await fetch(`${BASE}/stories/${user}/${lang}`, {
    signal: AbortSignal.timeout(T_SHORT_MS),
  });
  const data = await jsonOrThrow<{ stories: StoryMeta[] } | StoryMeta[]>(res);
  return Array.isArray(data) ? data : data.stories;
}

export async function createStory(
  user: string,
  lang: Lang,
  topic?: string,
): Promise<{ slug: string; title: string; chapter: number; text: string }> {
  const res = await fetch(`${BASE}/stories/${user}/${lang}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(topic ? { topic } : {}),
    // Writes a chapter with the model.
    signal: AbortSignal.timeout(T_TURN_MS),
  });
  return jsonOrThrow(res);
}

export async function nextChapter(
  user: string,
  lang: Lang,
  slug: string,
): Promise<{ slug: string; title?: string; chapter: number; text: string }> {
  const res = await fetch(`${BASE}/stories/${user}/${lang}/${slug}/next`, {
    method: "POST",
    signal: AbortSignal.timeout(T_TURN_MS),
  });
  return jsonOrThrow(res);
}

// ---------------------------------------------------------------------------
// Page photo to text (needs a vision model)
// ---------------------------------------------------------------------------
export async function ocrPage(
  user: string,
  lang: Lang,
  image: Blob,
): Promise<{ text: string; chars: number }> {
  const form = new FormData();
  form.append("user_id", user);
  form.append("target_language", lang);
  form.append("image", image, "page.jpg");
  const res = await fetch(`${BASE}/ocr`, {
    method: "POST",
    body: form,
    // A vision model can take tens of seconds per page.
    signal: AbortSignal.timeout(T_TURN_MS),
  });
  return jsonOrThrow(res);
}

export function audioUrl(path: string | null): string | null {
  // The backend returns "/audio/<sid>/NNN.wav". Vite proxies /audio to the
  // backend without a rewrite, so the absolute path works as is.
  return path;
}

// ---------------------------------------------------------------------------
// My Books (mode 8)
// ---------------------------------------------------------------------------
export interface BookMeta {
  slug: string;
  title: string;
  page: number;
  status: string;
  sessions: number;
  updated: string;
}

export interface BookDetail extends BookMeta {
  created: string;
  summary: string;
  history: string[];
  vocab: string[];
}

export async function fetchBooks(user: string, lang: Lang): Promise<BookMeta[]> {
  const res = await fetch(`${BASE}/books/${user}/${lang}`, {
    signal: AbortSignal.timeout(T_SHORT_MS),
  });
  const data = await jsonOrThrow<{ books: BookMeta[] }>(res);
  return data.books;
}

export async function createBook(user: string, lang: Lang, title: string): Promise<BookDetail> {
  const res = await fetch(`${BASE}/books/${user}/${lang}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
    signal: AbortSignal.timeout(T_SHORT_MS),
  });
  return jsonOrThrow(res);
}

export async function fetchBook(user: string, lang: Lang, slug: string): Promise<BookDetail> {
  const res = await fetch(`${BASE}/books/${user}/${lang}/${slug}`, {
    signal: AbortSignal.timeout(T_SHORT_MS),
  });
  return jsonOrThrow(res);
}

// ---------------------------------------------------------------------------
// Home: greeting + class suggestion ("Today's class" card)
// ---------------------------------------------------------------------------
export interface Greeting {
  name: string;
  /** null while nobody has measured the level. */
  cefr: string | null;
  streak: number;
  vocab_count: number;
}

export type SuggestionKind =
  "assessment" | "review" | "srs" | "focus" | "skill" | "lesson" | "free";

export interface Suggestion {
  kind: SuggestionKind;
  mode: (LessonMode | 6 | 8) | null;
  route: string | null;
  count: number | null;
  focus: string | null;
  skill: string | null;
  topic_id: string | null;
}

export interface HomeData {
  greeting: Greeting;
  suggestion: Suggestion;
}

export async function fetchHome(user: string, lang: Lang): Promise<HomeData> {
  const res = await fetch(`${BASE}/suggestion/${user}/${lang}`, {
    signal: AbortSignal.timeout(T_SHORT_MS),
  });
  return jsonOrThrow(res);
}

// ---------------------------------------------------------------------------
// Mode 9: CEFR syllabus
// ---------------------------------------------------------------------------
export type TopicStatus = "pending" | "seen" | "practiced" | "mastered";

export interface TopicOverview {
  id: string;
  title: string;
  status: TopicStatus;
  date: string | null;
}

export interface SyllabusLevel {
  level: string;
  topics: TopicOverview[];
}

export interface SyllabusData {
  levels: SyllabusLevel[];
  next: { id: string; title: string } | null;
}

export async function fetchSyllabus(user: string, lang: Lang): Promise<SyllabusData> {
  const res = await fetch(`${BASE}/syllabus/${user}/${lang}`, {
    signal: AbortSignal.timeout(T_SHORT_MS),
  });
  return jsonOrThrow<SyllabusData>(res);
}
