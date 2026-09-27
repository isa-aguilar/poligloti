# Architecture

In one sentence: a web page records you, a small server turns your recording into a lesson turn with the help of three AI services, and everything the teacher learns about you is kept in plain text files.

The pieces:

- **Web app** (React, installable on a phone as a PWA): the screens, the microphone and the audio player.
- **Backend** (FastAPI): the **API** receives each request; the **teacher** prepares every turn (instructions, memory, reply, voice); the **analyst** reviews a session when it ends and updates the progress.
- **Files on disk**: the teacher's instructions and teaching content (read only) and the learner memory (written as you practice).
- **Three AI services** with the OpenAI protocol, each configured on its own: local (Ollama, speaches, LM Studio, llama.cpp) or in the cloud (OpenAI, Groq and others).

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Inter, Helvetica, Arial, sans-serif","fontSize":"15px","lineColor":"#94A3B8","clusterBkg":"#FAFAFA","clusterBorder":"#E2E8F0","titleColor":"#475569","edgeLabelBackground":"#FFFFFF"},"flowchart":{"curve":"basis","nodeSpacing":28,"rankSpacing":50,"padding":14}}}%%
flowchart TB
    classDef user fill:#E0F2FE,stroke:#0284C7,stroke-width:1.5px,color:#0C4A6E
    classDef actor fill:#DCFCE7,stroke:#16A34A,stroke-width:1.5px,color:#14532D
    classDef hub fill:#EDE9FE,stroke:#7C3AED,stroke-width:2px,color:#2E1065
    classDef model fill:#FFEDD5,stroke:#EA580C,stroke-width:1.5px,color:#7C2D12
    classDef data fill:#F1F5F9,stroke:#64748B,stroke-width:1.5px,color:#1E293B

    web["<b>Web app</b><br/><small>React PWA: mic, audio queue, screens</small>"]:::user

    subgraph backend["Backend (FastAPI)"]
        api["<b>API</b><br/><small>routers and /health</small>"]:::hub
        teacher["<b>Teacher</b><br/><small>each turn: prompt, reply, voice</small>"]:::actor
        analyst["<b>Analyst</b><br/><small>end of session: progress, scores</small>"]:::actor
    end

    subgraph files["Files on disk"]
        prompts[("<b>Prompts and seeds</b><br/><small>modes, syllabus, scenarios</small>")]:::data
        memory[("<b>Learner memory</b><br/><small>markdown in DATA_DIR</small>")]:::data
    end

    subgraph ai["OpenAI-compatible services"]
        stt["<b>Speech-to-text</b><br/><small>/audio/transcriptions</small>"]:::model
        chat["<b>Chat model</b><br/><small>/chat/completions</small>"]:::model
        tts["<b>Text-to-speech</b><br/><small>/audio/speech</small>"]:::model
    end

    web <-- "audio or text / streamed reply" --> api
    api --> teacher
    api --> analyst
    api --> stt
    teacher --> chat
    teacher --> tts
    analyst --> chat
    prompts --> teacher
    teacher <--> memory
    analyst --> memory
```

## A spoken turn

What happens between you finishing a sentence and hearing the teacher:

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Inter, Helvetica, Arial, sans-serif","fontSize":"14px","actorBkg":"#EDE9FE","actorBorder":"#7C3AED","actorTextColor":"#2E1065","signalColor":"#64748B","signalTextColor":"#1E293B","noteBkgColor":"#F1F5F9","noteBorderColor":"#94A3B8","noteTextColor":"#1E293B","activationBkgColor":"#FFEDD5","activationBorderColor":"#EA580C","sequenceNumberColor":"#FFFFFF"}}}%%
sequenceDiagram
    autonumber
    participant B as Web app
    participant A as Backend
    participant S as Speech-to-text
    participant C as Chat model
    participant T as Text-to-speech
    B->>A: recording (POST /turn/stream)
    A->>S: audio + recent vocabulary hint
    S-->>A: what the learner said
    A-->>B: transcript
    Note over A: prompt = rules + mode + learner memory
    A->>C: prompt + transcript (streamed)
    loop every finished sentence of the reply
        C-->>A: next part of the JSON answer
        A->>T: the sentence
        T-->>A: audio
        A-->>B: audio of that sentence, plays at once
    end
    A-->>B: corrections, new vocabulary, follow-up
    Note over A: turn saved in the session log
```

1. The browser records the learner and posts the audio to `/turn/stream`.
2. The backend sends it to speech-to-text with a short hint (recent vocabulary, proper names from the profile) so rare words are recognised.
3. It builds the system prompt: shared rules (`prompts/shared.md`), the mode prompt (`prompts/<lang>/mode-N-*.md`), an optional block for the mode (a scenario, a text, a syllabus topic) and the learner memory (profile, recent progress, vocabulary, spaced-repetition terms, this week's focus).
4. The chat model answers in a fixed JSON contract: `reply`, `corrections`, `new_vocab`, `suggested_followup`. While it streams, `reply_stream.py` pulls the `reply` text out of the partial JSON and cuts it into sentences, and each sentence goes to text-to-speech at once. The first audio plays before the model has finished.
5. At the end of the stream, `llm_parse.py` parses the full answer (tolerant of broken JSON), drops corrections that quote something the learner did not say, and the turn is appended to the session log.
6. When the session ends, an analyst pass (`post_session.py`) reads only that session's turns, summarises it into `progress.md` (and into the session's notes, which the "My sessions" screen shows), consolidates vocabulary (deduplicated, then scheduled with FSRS spaced repetition), and updates the skill tracker: eight scores on a CEFR spine, active and resolved errors, and a history that draws the progress curve.

## Modes

| Mode | What it does | Needs |
|---|---|---|
| 1 Free talk | Conversation that follows the learner | chat |
| 2 Role-play | A scenario (work or everyday life) with the teacher in character | chat |
| 3 Guided reading | Discuss a text the learner pastes | chat |
| 4 Read aloud and minimal pairs | Per-word feedback on reading; pairs like *Hüte / Hütte* | speech-to-text with word timestamps |
| 5 Writing | Draft an email or chat message, get feedback, send it to a simulated colleague | chat |
| 6 Assessment | Initial level, weekly review, level-up test | chat |
| 7 Expressions | Idioms a native speaker really uses | chat |
| 8 Book | Read a page aloud, then talk about it; remembers the plot | chat, optional vision for page photos |
| 9 Lesson | A topic from the CEFR syllabus, with exercises | chat |

## Backend layout

```
backend/
  app.py            app assembly: CORS, /health, AI error handler, static files
  config.py         every setting, from environment variables
  services/         the three OpenAI-compatible clients + status probing
  routers/          HTTP endpoints (session, turn, progress, books, stories...)
  teacher.py        one teacher turn: prompt, model, TTS, persistence
  post_session.py   end-of-session analyst passes
  prompt_builder.py assembles system prompts from prompts/
  llm_parse.py      tolerant parser of the teacher JSON contract
  reply_stream.py   extracts the reply text from a streaming JSON answer
  memory.py         reads and writes the markdown memory
  srs.py            spaced repetition (FSRS) on top of vocab.md
  syllabus.py       CEFR syllabus and per-learner topic status
  prompts/          teacher prompts, scenarios, syllabus and seeds per language
```

## Graceful degradation

`services/status.py` probes each configured service at startup and on `/health?deep=1`. The web app reads `/health` and adapts:

| Missing | Behaviour |
|---|---|
| Chat model | Setup screen that explains which variables to set |
| Speech-to-text | The microphone is hidden; the learner types |
| Word timestamps | Read-aloud scoring and minimal pairs are disabled |
| Text-to-speech | The browser reads replies with an on-device voice, or text only |
| Vision model | The "photo of a page" option is hidden |

Errors from AI services are typed (`AIServiceError`) and returned as `{detail, service, code}` with HTTP 503 (501 for an unsupported capability), so the app never shows a 500 or invents a reply.

## Learner memory

```
DATA_DIR/
  <learner>/profile.md          name, languages, stt_hints
  <learner>/<lang>/USER.md      goals and level (cefr_estimate)
  <learner>/<lang>/sessions/    one file per day, every turn tagged with its session id
  <learner>/<lang>/sessions/notes/<session>.json  what the end-of-session pass produced
  <learner>/<lang>/progress.md  session summaries
  <learner>/<lang>/vocab.md     vocabulary; srs.json holds its review schedule
  <learner>/<lang>/skill-tracker.md, curriculum.md, syllabus.md, ...
  _shared/scenarios/            your own role-play scenarios (override the built-in ones)
```

Files are the source of truth and can be edited by hand. Session state lives in memory in a single process (one worker), which is enough for a household.
