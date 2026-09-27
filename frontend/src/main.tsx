import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.tsx";
import { initAutoUpdate } from "@/lib/auto-update";

createRoot(document.getElementById("root")!).render(<App />);

// Auto-refresh after a deploy: reload the PWA when it comes back to the
// foreground with an old build in memory (outside a session). See auto-update.ts.
initAutoUpdate();

// Service worker in production only (in dev it would interfere with Vite HMR).
// Shows a useful screen when the PWA opens and the server cannot be reached.
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => undefined);
  });
}
