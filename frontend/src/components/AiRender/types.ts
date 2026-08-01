export type UiHint = Record<string, unknown> | null | undefined;

export interface WorkspaceFileChange {
  path: string;
  operation: "write" | "delete";
}

export interface WorkspaceChangeNotice {
  changeSetId: string;
  changes: WorkspaceFileChange[];
}

export interface AiRenderProps {
  content?: string;
  uiHint?: UiHint;
  metadata?: Record<string, unknown>;
  compact?: boolean;
  onWorkspaceChanged?: (notice: WorkspaceChangeNotice) => void | Promise<void>;
}
