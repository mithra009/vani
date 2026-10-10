import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` serves on :5173 and proxies /api to the FastAPI backend (default :8010,
// override with the API_PORT environment variable).
const apiPort = process.env.API_PORT || "8010";

export default defineConfig(({ mode }) => {
  // Read the repo-root .env, but expose ONLY the two public Supabase values to the browser.
  // The secret key and other API keys never reach the bundle.
  const env = loadEnv(mode, "..", "");
  return {
    plugins: [react()],
    define: {
      "import.meta.env.VITE_SUPABASE_URL": JSON.stringify(env.SUPABASE_URL || ""),
      "import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY": JSON.stringify(env.SUPABASE_PUBLISHABLE_KEY || ""),
    },
    server: {
      port: 5173,
      proxy: { "/api": `http://127.0.0.1:${apiPort}` },
    },
  };
});
