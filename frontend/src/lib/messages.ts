import type { ReactNode } from "react";
import type { Correction } from "@/lib/api";
import type { TurnEntry } from "@/hooks/useSession";

/** One exchange for MessageList: what the learner said and what the teacher answered. */
export interface Message {
  id: string | number;
  learner: string;
  teacher: string;
  /** Shown compactly under the learner bubble (history view). */
  corrections?: Correction[];
  /** Extra controls under the teacher bubble (e.g. replay). */
  teacherExtra?: ReactNode;
}

/** Live session turns as MessageList messages. */
export function turnsToMessages(turns: TurnEntry[]): Message[] {
  return turns.map((tn) => ({ id: tn.id, learner: tn.user, teacher: tn.reply }));
}
