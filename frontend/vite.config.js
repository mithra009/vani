import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` serves on :5173 and proxies /api to the FastAPI backend on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
