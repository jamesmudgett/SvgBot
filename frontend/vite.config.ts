import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8000";

const proxy = {
  "/api": {
    target: backend,
    changeOrigin: true,
    timeout: 120_000,
  },
  "/health": {
    target: backend,
    changeOrigin: true,
  },
  "/.well-known": {
    target: backend,
    changeOrigin: true,
  },
};

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    strictPort: false,
    proxy,
  },
  preview: {
    host: true,
    port: 4173,
    proxy,
  },
});
