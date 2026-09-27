/**
 * Compile-time check that the hand-written API types match the backend.
 *
 * `api.gen.ts` is generated from the backend OpenAPI schema (`npm run gen:api`
 * after changing the contract). If the types in `api.ts` drift from the
 * backend, the build fails here naming the keys that are missing on each side.
 * Emits no runtime code.
 */
import type { components } from "./api.gen";
import type { ProgressData, ReadScoreResponse, SessionStartResponse, TurnResponse } from "./api";

type Gen = components["schemas"];

// Both halves must be `never`; otherwise the type is not `true` and tsc fails.
type SameKeys<Hand, G> = [Exclude<keyof Hand, keyof G>, Exclude<keyof G, keyof Hand>] extends [
  never,
  never,
]
  ? true
  : {
      missingInBackend: Exclude<keyof Hand, keyof G>;
      missingInFrontend: Exclude<keyof G, keyof Hand>;
    };

const turnOk: SameKeys<TurnResponse, Gen["TurnResult"]> = true;
const startOk: SameKeys<SessionStartResponse, Gen["SessionStartResult"]> = true;
const readOk: SameKeys<ReadScoreResponse, Gen["ReadScoreResult"]> = true;
const progressOk: SameKeys<ProgressData, Gen["ProgressData"]> = true;

export const contractChecks = { turnOk, startOk, readOk, progressOk } as const;
