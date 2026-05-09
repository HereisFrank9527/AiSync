declare global {
  interface Window {
    __AISYNC_API_BASE__?: string;
  }
}

function normalizeBase(value: string | undefined) {
  if (!value) return "";
  return value.replace(/\/+$/, "");
}

export function getApiBase() {
  const injected = typeof window !== "undefined" ? window.__AISYNC_API_BASE__ : undefined;
  const envBase = import.meta.env.VITE_API_BASE as string | undefined;
  return normalizeBase(injected || envBase || "http://localhost:8000/api");
}

export function apiBaseToWsBase(apiBase = getApiBase()) {
  const base = normalizeBase(apiBase).replace(/\/api$/, "");
  if (base.startsWith("https://")) return `wss://${base.slice("https://".length)}`;
  if (base.startsWith("http://")) return `ws://${base.slice("http://".length)}`;
  return base;
}
