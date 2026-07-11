import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: `vite dev` on :5173 proxies /api (and public avatar assets) to the FastAPI
// server on :8001. Prod: `vite build` emits hashed assets into dist/, which app.py
// mounts with immutable cache headers + an SPA fallback for BrowserRouter paths.
export default defineConfig({
  plugins: [react()],
  test: {
    include: ["src/**/*.test.{js,jsx}"],
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ["react", "react-dom", "react-router-dom", "@tanstack/react-query"],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": process.env.VITE_API_PROXY || "http://localhost:8001",
      "/assets/_users": process.env.VITE_API_PROXY || "http://localhost:8001",
      "/health": process.env.VITE_API_PROXY || "http://localhost:8001",
    },
  },
});
