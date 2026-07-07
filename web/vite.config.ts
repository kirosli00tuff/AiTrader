/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server on 5173. The backend runs on 127.0.0.1:8000 (CORS allows this
// origin). Override the backend location with VITE_API_BASE if needed.
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173 },
  preview: { host: "127.0.0.1", port: 4173 },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    css: false,
  },
});
