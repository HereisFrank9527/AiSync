import { useEffect, useState } from "react";
import type { ViewId } from "./types";
import { useAgentSocket } from "./hooks/useAgentSocket";
import { usePresets } from "./hooks/usePresets";
import Sidebar from "./components/Sidebar";
import ChatPanel from "./components/ChatPanel";
import SettingsPanel from "./components/SettingsPanel";
import "./style.css";

function App() {
  const [projectId, setProjectId] = useState("demo");
  const [activeView, setActiveView] = useState<ViewId>("chat");
  const [input, setInput] = useState("");
  const { connected, events, send, interrupt, setPresetId } =
    useAgentSocket(projectId);

  const preset = usePresets();

  /* keep socket aware of active preset */
  useEffect(() => {
    setPresetId(preset.activeId);
  }, [preset.activeId, setPresetId]);

  return (
    <div className="app-shell">
      <Sidebar
        projectId={projectId}
        onProjectIdChange={setProjectId}
        connected={connected}
        activeView={activeView}
        onViewChange={setActiveView}
      />

      <main className="main-content">
        {activeView === "chat" && (
          <ChatPanel
            events={events}
            connected={connected}
            onSend={send}
            onInterrupt={interrupt}
            input={input}
            onInputChange={setInput}
          />
        )}
        {activeView === "settings" && (
          <SettingsPanel
            presets={preset.presets}
            activeId={preset.activeId}
            activePreset={preset.activePreset}
            onSelect={preset.setActiveId}
            onCreate={preset.create}
            onUpdate={preset.update}
            onDelete={preset.remove}
            isBuiltin={preset.isBuiltin}
          />
        )}
        {activeView === "tools" && (
          <div style={{ padding: "var(--space-lg)" }}>
            <h2>工具</h2>
            <p style={{ color: "var(--color-text-tertiary)" }}>即将推出</p>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
