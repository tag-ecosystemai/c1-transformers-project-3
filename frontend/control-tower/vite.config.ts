import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Dev proxy avoids CORS: the FastAPI app runs on :8000
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": { target: "http://localhost:8000", rewrite: p => p.replace(/^\/api/, "") } } },
});
