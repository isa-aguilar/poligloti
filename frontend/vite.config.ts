import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// The dev server proxies the API and the audio files to the backend.
// Point it elsewhere with VITE_BACKEND_URL (e.g. in .env.local).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, "");
  const BACKEND_URL = env.VITE_BACKEND_URL || "http://127.0.0.1:8100";

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      host: true,
      port: 5173,
      proxy: {
        "/api": {
          target: BACKEND_URL,
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/api/, ""),
        },
        "/audio": {
          target: BACKEND_URL,
          changeOrigin: true,
        },
      },
    },
  };
});
