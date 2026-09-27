import { useRef, useState } from "react";
import { ocrPage, type Lang } from "@/lib/api";
import { humanError } from "@/hooks/useSession";
import { t } from "@/i18n";

/**
 * Photo of a page to text (needs a vision model on the backend). The image is
 * scaled down and converted to JPEG in the browser with a canvas: this
 * normalizes HEIC photos (Safari decodes them natively) and shrinks the upload.
 */
export function PhotoOcr({
  user,
  lang,
  onText,
}: {
  user: string;
  lang: Lang;
  onText: (text: string) => void;
}) {
  // Two inputs: the camera (capture) and the normal picker (gallery/files, e.g.
  // a screenshot of an online book). With `capture` iOS jumps to the camera
  // without offering a choice, so both are needed.
  const cameraRef = useRef<HTMLInputElement | null>(null);
  const uploadRef = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const toJpeg = (file: File): Promise<Blob> =>
    new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => {
        URL.revokeObjectURL(url);
        const scale = Math.min(1, 1600 / Math.max(img.width, img.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        canvas.getContext("2d")!.drawImage(img, 0, 0, canvas.width, canvas.height);
        canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("canvas"))), "image/jpeg", 0.85);
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error("unreadable image"));
      };
      img.src = url;
    });

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setErr(null);
    setBusy(true);
    try {
      const jpeg = await toJpeg(file);
      const res = await ocrPage(user, lang, jpeg);
      onText(res.text);
    } catch (e) {
      setErr(humanError(e));
    } finally {
      setBusy(false);
      if (cameraRef.current) cameraRef.current.value = "";
      if (uploadRef.current) uploadRef.current.value = "";
    }
  };

  const btnClass =
    "w-full rounded-xl border-2 border-dashed border-ink-200 dark:border-ink-700 px-4 py-5 text-sm text-ink-500 hover:border-accent-400 disabled:opacity-60";

  return (
    <div className="space-y-2">
      <input
        ref={cameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={(e) => void onFile(e.target.files?.[0])}
      />
      <input
        ref={uploadRef}
        type="file"
        accept="image/*"
        hidden
        onChange={(e) => void onFile(e.target.files?.[0])}
      />
      {busy ? (
        <div className={btnClass + " text-center"}>{t("ocr.working")}</div>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          <button onClick={() => cameraRef.current?.click()} className={btnClass}>
            {t("ocr.take")}
          </button>
          <button onClick={() => uploadRef.current?.click()} className={btnClass}>
            {t("ocr.upload")}
          </button>
        </div>
      )}
      {busy && <p className="text-xs text-ink-400 text-center">{t("ocr.hint")}</p>}
      {err && <p className="text-sm text-red-600">{err}</p>}
    </div>
  );
}
