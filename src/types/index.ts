/**
 * TypeScript types for linux_computer_use
 * Unified Linux desktop control layer
 */

export interface Element {
  index: number;
  elementToken?: string;
  role: string;
  name: string;
  description?: string;
  state?: string[];
  geometry?: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  parentIndex?: number;
  children?: number[];
  automationId?: string;
  className?: string;
  windowId: number;
  /** Accessible actions, e.g. "click", "activate". */
  actions?: string[];
  /** Current text of editable fields; never set for password fields. */
  value?: string | null;
}

export interface Window {
  windowId: number;
  pid: number;
  appId: string;
  title: string;
  geometry: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  workspace: number;
  visible: boolean;
  app: string;
}

export interface WindowState {
  windowId: number;
  pid: number;
  screenshotPath: string;
  treeMarkdown: string;
  elements: Element[];
  rawTree?: Record<string, unknown>;
  /** "atspi" for a real accessibility tree, "x11" for the window-only fallback. */
  source?: "atspi" | "x11";
  /** True when the window has a password field; input tools refuse to act on it. */
  sensitive?: boolean;
  sensitiveReasons?: string[];
  truncated?: boolean;
}

export interface ScreenshotResult {
  path: string;
  base64: string;
  windowId?: number;
  region?: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
}

export interface ClickOptions {
  element?: number;
  elementToken?: string;
  coordinate?: { x: number; y: number };
  windowId?: number;
}

export interface TypeOptions {
  text: string;
  element?: number;
  elementToken?: string;
  windowId?: number;
}

export interface ScrollOptions {
  direction: "up" | "down" | "left" | "right";
  amount?: number;
  element?: number;
  elementToken?: string;
  windowId?: number;
}

export interface ToolResult {
  success: boolean;
  effect: string;
  recommendation?: string;
  data?: Record<string, unknown>;
}