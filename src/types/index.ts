/**
 * TypeScript types for the linux-computer-use MCP server.
 *
 * These mirror the server's wire format exactly (snake_case, as sent over
 * MCP). `tests/unit/test_ts_types.py` checks every interface here against
 * the Python server, so a field added or renamed on one side fails CI until
 * the other side matches.
 */

// ---------------------------------------------------------------------------
// Shared shapes
// ---------------------------------------------------------------------------

/** Screen-pixel rectangle; x/y are absolute screen coordinates. */
export interface Geometry {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** One node of a window's element tree (from `get_window_state`). */
export interface Element {
  /** Pass this as `element` to click, type_text, scroll, screenshot_element. */
  index: number;
  /** AT-SPI role, e.g. "push button", "text", "check box", "menu item". */
  role: string;
  name: string;
  description: string;
  /** e.g. "focused", "checked", "editable", "disabled". */
  state: string[];
  geometry: Geometry;
  /** -1 for the root (the window itself). */
  parent_index: number;
  children: number[];
  automation_id: string;
  class_name: string;
  window_id: number;
  /** Accessible actions, e.g. "click", "activate". */
  actions: string[];
  /** Current text of editable fields; always null for password fields. */
  value: string | null;
}

export interface Window {
  window_id: number;
  pid: number;
  app_id: string;
  title: string;
  geometry: Geometry;
  workspace: number;
  visible: boolean;
  app: string;
}

/** An installed application, from its XDG .desktop entry. */
export interface App {
  id: string;
  name: string;
  exec: string;
  categories: string[];
}

export interface WindowRef {
  window_id: number;
  title: string;
}

/** "success" for reads, "confirmed"/"failed" for actions. */
export type Effect = "success" | "confirmed" | "failed";
export type ActionEffect = "confirmed" | "failed";
export type ScrollDirection = "up" | "down" | "left" | "right";

// ---------------------------------------------------------------------------
// Tool arguments
// ---------------------------------------------------------------------------

export type ListAppsArgs = Record<string, never>;
export type ListWindowsArgs = Record<string, never>;

export interface GetWindowStateArgs {
  window_id: number;
}

export interface GetAppInfoArgs {
  window_id: number;
}

/** Give either `element`, or both `x` and `y` (absolute, inside the window). */
export interface ClickArgs {
  window_id: number;
  element?: number | null;
  x?: number | null;
  y?: number | null;
}

/** Without `element`, types into whatever has focus in the window. */
export interface TypeTextArgs {
  text: string;
  window_id: number;
  element?: number | null;
}

/** xdotool key syntax, e.g. "Return", "ctrl+c"; space-separated keys run in order. */
export interface PressKeyArgs {
  keys: string;
  window_id?: number | null;
}

export interface ScrollArgs {
  direction: ScrollDirection;
  window_id: number;
  /** Wheel steps, 1-100. Default 3. */
  amount?: number;
  /** Default 0 (the whole window). */
  element?: number;
}

/** Give all four for a region, or none for the whole desktop. */
export interface ScreenshotDesktopArgs {
  x?: number | null;
  y?: number | null;
  width?: number | null;
  height?: number | null;
}

export interface ScreenshotWindowArgs {
  window_id: number;
}

export interface ScreenshotElementArgs {
  window_id: number;
  element: number;
}

// ---------------------------------------------------------------------------
// Tool results (structured content)
// ---------------------------------------------------------------------------

export interface ListAppsResult {
  effect: "success";
  count: number;
  apps: App[];
}

export interface ListWindowsResult {
  effect: "success";
  count: number;
  windows: Window[];
}

export interface WindowStateResult {
  effect: "success";
  window_id: number;
  pid: number;
  /** "atspi" for a real accessibility tree, "x11" for the window-only fallback. */
  source: "atspi" | "x11";
  /** True when the window has a password field; input tools refuse to act on it. */
  sensitive: boolean;
  sensitive_reasons: string[];
  /** True when the tree was cut off at the element limit. */
  truncated: boolean;
  /** Elements skipped because they lie outside the window's visible area; scroll to reveal them. */
  offscreen: number;
  /**
   * "screen": element geometry is in screen pixels (X11).
   * "window": geometry is relative to the window's top-left corner (Wayland,
   * where a window's screen position is unknown); window geometry is 0,0 there.
   */
  coordinates: "screen" | "window";
  tree_markdown: string;
  elements: Element[];
}

export interface AppInfoResult {
  effect: "success";
  app_id: string;
  name: string;
  pid: number;
  windows: WindowRef[];
}

export interface ClickResult {
  effect: ActionEffect;
  window_id: number;
}

export interface TypeTextResult {
  effect: ActionEffect;
  characters_typed: number;
  window_id: number;
}

export interface PressKeyResult {
  effect: ActionEffect;
  keys: string;
  window_id: number | null;
}

export interface ScrollResult {
  effect: ActionEffect;
  direction: ScrollDirection;
  amount: number;
  window_id: number;
}

/**
 * Screenshot tools return two content blocks instead of structured content:
 * an `image/png` image, then a text block holding one of these as JSON.
 */
export interface ScreenshotDesktopMeta {
  path: string;
  /** [x, y, width, height], or null for the whole desktop. */
  region: [number, number, number, number] | null;
}

export interface ScreenshotWindowMeta {
  path: string;
  window_id: number;
}

export interface ScreenshotElementMeta {
  path: string;
  window_id: number;
  element: number;
}

// ---------------------------------------------------------------------------
// Tool map
// ---------------------------------------------------------------------------

export interface ToolArgs {
  list_apps: ListAppsArgs;
  list_windows: ListWindowsArgs;
  get_window_state: GetWindowStateArgs;
  get_app_info: GetAppInfoArgs;
  click: ClickArgs;
  type_text: TypeTextArgs;
  press_key: PressKeyArgs;
  scroll: ScrollArgs;
  screenshot_desktop: ScreenshotDesktopArgs;
  screenshot_window: ScreenshotWindowArgs;
  screenshot_element: ScreenshotElementArgs;
}

export interface ToolResults {
  list_apps: ListAppsResult;
  list_windows: ListWindowsResult;
  get_window_state: WindowStateResult;
  get_app_info: AppInfoResult;
  click: ClickResult;
  type_text: TypeTextResult;
  press_key: PressKeyResult;
  scroll: ScrollResult;
  screenshot_desktop: ScreenshotDesktopMeta;
  screenshot_window: ScreenshotWindowMeta;
  screenshot_element: ScreenshotElementMeta;
}

export type ToolName = keyof ToolArgs;
