import { useCallback, useRef, useState } from "react";

export interface Recording {
  blob: Blob;
  mimeType: string;
  filename: string;
}

export type RecorderState = "idle" | "permission" | "recording" | "error";

function pickMimeType(): string {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/mp4;codecs=mp4a.40.2",
    "audio/ogg;codecs=opus",
  ];
  for (const m of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(m)) {
      return m;
    }
  }
  return "";
}

function extFor(mime: string): string {
  if (mime.includes("webm")) return "webm";
  if (mime.includes("mp4")) return "m4a";
  if (mime.includes("ogg")) return "ogg";
  return "bin";
}

export function useRecorder() {
  const [state, setState] = useState<RecorderState>("idle");
  const [error, setError] = useState<string | null>(null);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const stopResolveRef = useRef<((r: Recording) => void) | null>(null);

  const start = useCallback(async () => {
    setError(null);
    setState("permission");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;
      const mimeType = pickMimeType();
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        const effective = recorder.mimeType || mimeType || "audio/webm";
        const blob = new Blob(chunksRef.current, { type: effective });
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        setState("idle");
        const rec: Recording = {
          blob,
          mimeType: effective,
          filename: `turn.${extFor(effective)}`,
        };
        stopResolveRef.current?.(rec);
        stopResolveRef.current = null;
      };
      mediaRef.current = recorder;
      recorder.start();
      setState("recording");
    } catch (e) {
      setError((e as Error).message);
      setState("error");
    }
  }, []);

  const stop = useCallback((): Promise<Recording> => {
    return new Promise((resolve) => {
      const rec = mediaRef.current;
      if (!rec || rec.state === "inactive") {
        resolve({
          blob: new Blob([], { type: "audio/webm" }),
          mimeType: "audio/webm",
          filename: "turn.webm",
        });
        return;
      }
      stopResolveRef.current = resolve;
      rec.stop();
    });
  }, []);

  const cancel = useCallback(() => {
    const rec = mediaRef.current;
    if (rec && rec.state !== "inactive") rec.stop();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    chunksRef.current = [];
    setState("idle");
  }, []);

  return { state, error, start, stop, cancel };
}
