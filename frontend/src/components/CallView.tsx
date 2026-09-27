import { Card } from "@/components/Card";
import { MessageList } from "@/components/MessageList";
import { turnsToMessages } from "@/lib/messages";
import { MicButton } from "@/components/MicButton";
import type { MicState } from "@/hooks/useVoiceTurn";
import type { TurnEntry } from "@/hooks/useSession";
import { t } from "@/i18n";

/** "Call" view: big mic on top, the whole conversation below it. */
export function CallView({
  micState,
  micLabel,
  onMic,
  recorderError,
  turns,
  hasAudio,
  audioBlocked,
  onResumeAudio,
  onReplay,
}: {
  micState: MicState;
  micLabel: string;
  onMic: () => void;
  recorderError: string | null;
  turns: TurnEntry[];
  hasAudio: boolean;
  audioBlocked: boolean;
  onResumeAudio: () => void;
  onReplay: () => void;
}) {
  const last = turns.length > 0 ? turns[turns.length - 1] : null;
  const messages = turnsToMessages(turns);
  // The last reply keeps its replay button inside the thread.
  if (last && last.reply && hasAudio) {
    messages[messages.length - 1].teacherExtra = (
      <button
        onClick={onReplay}
        className="inline-flex items-center min-h-9 text-sm text-accent-600 hover:underline"
      >
        {t("call.replay")}
      </button>
    );
  }
  return (
    <div className="flex flex-col items-center gap-6 py-6">
      <MicButton
        state={micState}
        onClick={onMic}
        disabled={micState === "busy"}
        labelIdle={micLabel}
        labelRecording={t("call.recording")}
        labelBusy={micLabel}
      />
      {recorderError && (
        <Card className="p-4 max-w-md">
          <h3 className="font-medium mb-1">{t("call.permission.title")}</h3>
          <p className="text-sm text-ink-500">{t("call.permission.body")}</p>
        </Card>
      )}
      {audioBlocked && (
        <button
          onClick={onResumeAudio}
          className="rounded-xl bg-accent-600 px-5 py-3 text-white font-medium shadow hover:bg-accent-700"
        >
          {t("call.tapToListen")}
        </button>
      )}
      {last?.user && (
        <p className="text-xs text-ink-500 max-w-xl text-center">
          {t("call.heard")} “{last.user}”
        </p>
      )}
      {messages.length > 0 && (
        <Card className="w-full max-w-xl">
          <MessageList messages={messages} live className="max-h-[50vh] p-4" />
        </Card>
      )}
    </div>
  );
}
