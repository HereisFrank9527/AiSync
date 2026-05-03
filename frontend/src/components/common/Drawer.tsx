import type { ReactNode } from "react";
import "./Drawer.css";

interface DrawerProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}

export default function Drawer({ open, title, onClose, children }: DrawerProps) {
  if (!open) return null;

  return (
    <div className="drawer-layer">
      <button className="drawer-backdrop" onClick={onClose} aria-label="关闭" />
      <aside className="drawer-panel">
        <header className="drawer-header">
          <h2>{title}</h2>
          <button className="btn-ghost" onClick={onClose}>关闭</button>
        </header>
        <div className="drawer-body">{children}</div>
      </aside>
    </div>
  );
}
