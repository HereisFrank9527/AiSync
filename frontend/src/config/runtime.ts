declare global {
  interface Window {
    __AISYNC_API_BASE__?: string;
  }
}

function normalizeBase(value: string | undefined) {
  if (!value) return "";
  return value.replace(/\/+$/, "");
}

function defaultApiBase() {
  if (typeof window !== "undefined" && window.location.protocol.startsWith("http")) {
    return "/api";
  }
  return "http://127.0.0.1:27631/api";
}

export function getApiBase() {
  const injected = typeof window !== "undefined" ? window.__AISYNC_API_BASE__ : undefined;
  const envBase = import.meta.env.VITE_API_BASE as string | undefined;
  return normalizeBase(injected || envBase || defaultApiBase());
}

export function setApiBase(value: string) {
  if (typeof window === "undefined") return;
  window.__AISYNC_API_BASE__ = normalizeBase(value);
}

export function apiBaseToWsBase(apiBase = getApiBase()) {
  const base = normalizeBase(apiBase).replace(/\/api$/, "");
  if (base.startsWith("https://")) return `wss://${base.slice("https://".length)}`;
  if (base.startsWith("http://")) return `ws://${base.slice("http://".length)}`;
  if (typeof window !== "undefined" && window.location.protocol.startsWith("http")) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}${base}`;
  }
  return base;
}
