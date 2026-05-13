import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";

function appVersion() {
  const configPath = path.resolve(__dirname, "src-tauri", "tauri.conf.json");
  const config = JSON.parse(fs.readFileSync(configPath, "utf-8")) as { version?: string };
  return config.version ?? "0.0.0";
}

export default defineConfig({
  plugins: [react()],
  define: {
    __AISYNC_APP_VERSION__: JSON.stringify(appVersion()),
  },
  server: {
    port: 1420,
    strictPort: true,
  },
});
