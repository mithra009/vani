import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` serves on :5173 and proxies /api to the FastAPI backend (default :8010,
// override with the API_PORT environment variable).
const apiPort = process.env.API_PORT || "8010";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": `http://127.0.0.1:${apiPort}` },
  },
});
