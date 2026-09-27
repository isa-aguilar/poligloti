# poligloti frontend

The web app (installable PWA) of poligloti: React + TypeScript + Vite + Tailwind. It talks to the FastAPI backend in `../backend`; see the main README for the backend setup and the "Configuration" section for the AI services.

## Development

```bash
npm ci
npm run dev          # http://localhost:5173
```

The dev server proxies `/api/*` and `/audio/*` to the backend at `http://127.0.0.1:8100`. To use a backend elsewhere, create `.env.local`:

```bash
VITE_BACKEND_URL=http://my-backend-host:8100
```

## Production build

```bash
npm run build        # type check + bundle into dist/
```

The backend serves `dist/` itself (single-page app catch-all), so a production build calls the API on its own origin. To call a backend on another origin, set `VITE_API_BASE` (e.g. `VITE_API_BASE=https://api.example.com`) at build time and add that origin to the backend's `CORS_ORIGINS`.

## Scripts

| Script                            | What it does                                                                                                                                  |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `npm run lint`                    | ESLint (TypeScript + React hooks rules)                                                                                                       |
| `npm run format` / `format:check` | Prettier                                                                                                                                      |
| `npm run gen:api`                 | Exports the backend OpenAPI schema and generates `src/lib/api.gen.ts` (optional; the hand-written types in `src/lib/api.ts` are the contract) |

## How it adapts to the backend

At startup the app reads `GET /health` and adapts to what the AI services can do:

- **No chat model**: a setup screen explains which variables to set.
- **A configured service that does not answer**: a banner with a retry button.
- **No speech-to-text**: the microphone is hidden and the learner types; pronunciation practice is off.
- **Speech-to-text without word timestamps**: pronunciation practice is off.
- **No server voice for the language**: the teacher speaks with an on-device browser voice (only voices that run locally), or shows text only.
- **No vision model**: the "photo of a page" option is hidden.

## Structure

- `src/pages/`: one component per route (`Select`, `Talk`, `Progress`, `Review`, `Books`, `SetupRequired`).
- `src/components/`: UI pieces; `setup/SetupPanel.tsx` is the per-mode setup screen.
- `src/hooks/`: session, voice turn, audio queue, recorder, teacher voice.
- `src/lib/api.ts`: every backend call and its types.
- `src/lib/capabilities.ts`: what the backend can do, from `/health`.
- `src/lib/lang.ts`: the only per-language map (name and flag).
- `src/i18n/`: UI strings (`en` is the base, plus `es` and `de`).
