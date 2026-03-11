import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiProxyTarget = "http://127.0.0.1:8787";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/healthz": apiProxyTarget,
      "/jobs": apiProxyTarget,
      "/positions": apiProxyTarget,
      "/plans": apiProxyTarget,
      "/fills": apiProxyTarget,
      "/nav": apiProxyTarget,
      "/reports": apiProxyTarget,
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
  },
  build: {
    outDir: "dist",
    assetsDir: "static",
    emptyOutDir: true,
  },
});
