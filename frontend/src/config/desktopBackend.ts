import { invoke, isTauri } from "@tauri-apps/api/core";
import { getApiBase, setApiBase } from "./runtime";

let backendReadyPromise: Promise<void> | null = null;

function healthUrl() {
  return getApiBase().replace(/\/api$/, "/health");
}

async function backendDiagnostics() {
  try {
    return await invoke<string>("backend_diagnostics");
  } catch (error) {
    return `无法获取桌面诊断信息：${error instanceof Error ? error.message : String(error)}`;
  }
}

async function loadBackendApiBase() {
  const apiBase = await invoke<string>("backend_api_base");
  setApiBase(apiBase);
  return apiBase;
}

async function waitForBackendReady() {
  const deadline = Date.now() + 30_000;
  let lastError: unknown = null;
  while (Date.now() < deadline) {
    try {
      await loadBackendApiBase();
      const response = await fetch(healthUrl(), { cache: "no-store" });
      if (response.ok) return;
      lastError = new Error(`health check returned ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 500));
  }
  const diagnostics = await backendDiagnostics();
  throw new Error(
    `后端启动超时：${lastError instanceof Error ? lastError.message : String(lastError)}\n\n${diagnostics}`,
  );
}

export function ensureDesktopBackendStarted() {
  if (!isTauri()) return Promise.resolve();
  if (!backendReadyPromise) {
    backendReadyPromise = waitForBackendReady().catch((error) => {
      backendReadyPromise = null;
      throw error;
    });
  }
  return backendReadyPromise;
}
