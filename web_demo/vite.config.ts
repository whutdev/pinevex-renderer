import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const RENDERER_API = process.env.RENDERER_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "^/render$": { target: RENDERER_API, changeOrigin: true },
      "^/preview\\.png$": { target: RENDERER_API, changeOrigin: true },
      "^/health$": { target: RENDERER_API, changeOrigin: true },
      "^/font-health$": { target: RENDERER_API, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
