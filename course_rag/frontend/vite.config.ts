import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig(({ command }) => ({
  base: command === "build" ? "/static/frontend/" : "/",
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    outDir: "../app/static/frontend",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/health": "http://127.0.0.1:8000",
      "/ingest": "http://127.0.0.1:8000",
      "/ask": "http://127.0.0.1:8000",
      "/search": "http://127.0.0.1:8000",
    },
  },
}));
