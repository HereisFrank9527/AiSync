import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";

function appVersion() {
  const packagePath = path.resolve(__dirname, "package.json");
  const packageJson = JSON.parse(fs.readFileSync(packagePath, "utf-8")) as { version?: string };
  return packageJson.version ?? "0.0.0";
}

function allowedDevHosts() {
  return (process.env.AISYNC_VITE_ALLOWED_HOSTS || "")
    .split(",")
    .map((host) => host.trim())
    .filter(Boolean);
}

export default defineConfig({
  plugins: [react()],
  define: {
    __AISYNC_APP_VERSION__: JSON.stringify(appVersion()),
  },
  server: {
    host: process.env.AISYNC_VITE_HOST || "127.0.0.1",
    allowedHosts: allowedDevHosts(),
    port: 1420,
    strictPort: true,
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${process.env.AISYNC_BACKEND_PORT || "27631"}`,
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
