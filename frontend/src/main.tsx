import { Component, StrictMode, useEffect, useState, type ErrorInfo, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { invoke, isTauri } from "@tauri-apps/api/core";
import App from "./App";
import { ensureDesktopBackendStarted } from "./config/desktopBackend";

const APP_VERSION = __AISYNC_APP_VERSION__;

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (char) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[char] || char;
  });
}

function renderFatalError(error: unknown) {
  const root = document.getElementById("root");
  if (!root) return;
  const message = error instanceof Error ? error.stack || error.message : String(error);
  root.innerHTML = `
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;padding:24px;color:#37352f;white-space:pre-wrap;">
      <h1 style="margin:0 0 8px;font-size:18px;color:#e03e3e;">AiSync 前端启动失败</h1>
      <div>${escapeHtml(message)}</div>
    </div>
  `;
}

function writeFrontendDiagnostics(message: string) {
  if (!isTauri()) return;
  void invoke("frontend_diagnostics", {
    message: `[${new Date().toISOString()}] ${message}`,
  }).catch(() => undefined);
}

class BootErrorBoundary extends Component<{ children: ReactNode }, { error: unknown }> {
  state = { error: null as unknown };

  static getDerivedStateFromError(error: unknown) {
    return { error };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    writeFrontendDiagnostics(`react error: ${error instanceof Error ? error.stack || error.message : String(error)}\n${info.componentStack}`);
  }

  render() {
    if (this.state.error) {
      const message = this.state.error instanceof Error
        ? this.state.error.stack || this.state.error.message
        : String(this.state.error);
      return (
        <div className="view-status view-status--error" style={{ whiteSpace: "pre-wrap", textAlign: "left" }}>
          前端渲染失败：{message}
        </div>
      );
    }
    return this.props.children;
  }
}

function Bootstrap() {
  const [ready, setReady] = useState(!isTauri());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    writeFrontendDiagnostics(`frontend bootstrap ${APP_VERSION}`);
    void ensureDesktopBackendStarted()
      .then(() => {
        writeFrontendDiagnostics("backend health check passed");
      })
      .catch((error) => {
        console.error("Failed to start backend", error);
        writeFrontendDiagnostics(`backend startup failed: ${error instanceof Error ? error.stack || error.message : String(error)}`);
        if (!cancelled) setError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return <div className="view-status view-status--error">后端启动失败：{error}</div>;
  }

  if (!ready) {
    return (
      <div className="app-boot-screen">
        <div className="app-boot-card">
          <div className="app-boot-mark">A</div>
          <div className="app-boot-spinner" aria-hidden="true" />
          <h1>AiSync {APP_VERSION}</h1>
          <p>正在启动后端服务</p>
        </div>
      </div>
    );
  }

  return <App />;
}

try {
  writeFrontendDiagnostics(`main module loaded ${APP_VERSION}`);
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <BootErrorBoundary>
        <Bootstrap />
      </BootErrorBoundary>
    </StrictMode>,
  );
} catch (error) {
  writeFrontendDiagnostics(`fatal startup error: ${error instanceof Error ? error.stack || error.message : String(error)}`);
  renderFatalError(error);
}
