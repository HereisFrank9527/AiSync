import { Component, StrictMode, useEffect, useMemo, useState, type ErrorInfo, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

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
  console.debug(`[AiSync ${APP_VERSION}] ${message}`);
}

const BOOT_MESSAGES = [
  "准备 Web 工作台",
  "加载写作组件",
  "连接后端服务",
  "整理项目入口",
  "恢复对话状态",
];

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
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    let cancelled = false;
    writeFrontendDiagnostics(`frontend bootstrap ${APP_VERSION}`);
    const frame = window.requestAnimationFrame(() => {
      if (!cancelled) setReady(true);
    });
    return () => {
      cancelled = true;
      window.cancelAnimationFrame(frame);
    };
  }, []);

  useEffect(() => {
    if (ready || error) return undefined;
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 500);
    return () => window.clearInterval(timer);
  }, [error, ready]);

  const bootMessage = useMemo(() => {
    return BOOT_MESSAGES[Math.floor(elapsedSeconds / 2) % BOOT_MESSAGES.length];
  }, [elapsedSeconds]);

  if (error) {
    return <div className="view-status view-status--error">前端启动失败：{error}</div>;
  }

  if (!ready) {
    return (
      <div className="app-boot-screen">
        <div className="app-boot-card">
          <div className="app-boot-mark">A</div>
          <div className="app-boot-spinner" aria-hidden="true" />
          <h1>AiSync {APP_VERSION}</h1>
          <p>{bootMessage}</p>
          <p className="app-boot-subtext">正在加载 Web 前端，已等待 {elapsedSeconds} 秒</p>
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
