# Privacy

poligloti records your voice and keeps notes about how you learn. This page says exactly where that goes. Short version: **everything stays on your machine unless you point one of the three AI services at a cloud provider.**

## What stays on your machine

| Data                                                                       | Where                                                                      | For how long                                                                                                            |
| -------------------------------------------------------------------------- | -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Learner profiles, goals and level                                          | `DATA_DIR/<learner>/profile.md` and `<lang>/USER.md`                       | Until you delete them                                                                                                   |
| Session transcripts (what you said, what the teacher replied, corrections) | `DATA_DIR/<learner>/<lang>/sessions/`                                      | Until you delete them                                                                                                   |
| Notes of each session (summary, vocabulary, phrases you could have used) | `DATA_DIR/<learner>/<lang>/sessions/notes/` | Until you delete them |
| Progress: scores, errors, vocabulary, syllabus, weekly reviews             | Markdown files under `DATA_DIR/<learner>/<lang>/`                          | Until you delete them                                                                                                   |
| Your recordings                                                            | Sent to the speech-to-text service, **never written to disk** by poligloti | Only in memory during the request                                                                                       |
| The teacher's audio replies                                                | `AUDIO_ROOT` (a temporary folder)                                          | Deleted when the session ends; leftovers of interrupted sessions older than 48 hours are removed when the server starts |
| Photos of book pages                                                       | Sent to the vision model, never written to disk                            | Only in memory during the request                                                                                       |

All of it is plain text you can open, edit, back up or delete. There is no database, no account and no analytics. The browser keeps only small preferences (chosen learner, voice, speed) in `localStorage`.

## What leaves your machine, and to whom

Only what the AI services need, and only to the servers you configure:

| Service | What it receives | Configured by |
|---|---|---|
| Chat | Your transcribed words, the teacher's instructions, and a summary of your learner memory (profile, recent progress, vocabulary, weekly focus) | `AI_BASE_URL` |
| Speech-to-text | Your recording, the language, and a short hint with recent vocabulary and proper names | `STT_BASE_URL` (defaults to `AI_BASE_URL`) |
| Text-to-speech | The teacher's reply text | `TTS_BASE_URL` (defaults to `AI_BASE_URL`) |
| Vision (optional) | The photo of a book page | `AI_BASE_URL` with `AI_VISION_MODEL` |

If those URLs point to `localhost` (Ollama, speaches, LM Studio, llama.cpp), nothing leaves your computer. If they point to a cloud provider (OpenAI, Groq, or any other), that provider receives the data above and its own privacy policy applies. You can mix: for example chat in the cloud while your voice stays local with speaches.

Two details worth knowing:

- The learner id is **not** sent to the chat provider unless you set `AI_SEND_USER=true` (useful only behind your own gateway).
- Without a text-to-speech server, the browser reads the replies aloud. poligloti only uses voices the browser marks as on-device (`localService`), because other browser voices send the text to a cloud service without telling you. If no on-device voice exists for the language, it shows text only.

## Security

poligloti has **no login**. Anyone who can reach the port can open any learner. It listens on `127.0.0.1` by default and the Docker setup publishes the port on `127.0.0.1` only. To use it from your phone, put it behind a VPN or a reverse proxy with authentication that you control. Never expose it directly to the internet.
