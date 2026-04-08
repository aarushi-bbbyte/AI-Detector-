import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    // Proxy API calls to avoid CORS issues during local dev
    // Remove this if you're using the live AWS API directly
    proxy: {
      "/analyze": { target: "http://localhost:8000", changeOrigin: true },
      "/results":  { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
