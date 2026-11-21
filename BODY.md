# Deep Brainstorm: linux_computer_use

## Memory Check — What Memorius Tells Us

From memorius vault:
> "the next project to build is **linux_computer_use**, the better version of computer-use-linux extension which working well without issues, we meet"

## Current State Analysis

### What Works Well Currently
- **Agness Computer Use Skill** (from Agnes harness) - Provides a robust, safety-first workflow
- **Cloudroom Computer Use** - Works in virtual Linux environment with Xvfb + Cua Driver
- **Room CLI** - Has `computer-use` subcommand for start, launch, tools, call, status
- **MCP Integration** - The `@agent-sh/computer-use-linux` package provides MCP tools

### Known Issues / Pain Points
1. **Platform Limitations**: 
   - X11-only (no Wayland support)
   - AT-SPI accessibility dependency (some apps don't expose it)
   - No native Linux desktop app support for all use cases

2. **User Experience Friction**:
   - Need to remember `room-cli computer-use` commands
   - Separate setup for virtual screen vs real desktop
   - No persistent context between sessions

3. **Integration Gaps**:
   - MCP tools require separate setup
   - No unified interface for local vs remote desktop control
   - Limited feedback loop for complex interactions

## Vision for linux_computer_use

A **production-grade, unified desktop control layer** for Linux that:
- Works on **real desktop** (X11, Wayland, Wayland XWayland)
- Works on **virtual environments** (Xvfb, VMs, containers)
- Works **locally** and **remotely** (via agent/CLI/MCP)
- Provides **consistent API** across all platforms
- Has **proper error handling** and **graceful degradation**

## Target User Personas

### 1. AI Agent Developer
- Need: Test agents against real GUI applications
- Pain: Agents fail unpredictably on desktop interactions
- Goal: Programmatic desktop control that "just works"

### 2. QA Automation Engineer  
- Need: Visual regression testing for desktop apps
- Pain: Headless testing misses real-world UI issues
- Goal: Screenshot + element verification without browser limitations

### 3. Accessibility Researcher
- Need: Test screen readers and AT-SPI accessibility
- Pain: Hard to access accessibility tree programmatically  
- Goal: Full AT-SPI tree traversal with element actions

### 4. Container/Desktop App Developer
- Need: Test Electron/GTK/Qt apps in isolation
- Pain: No way to interact with apps launched in containers
- Goal: Launch apps + interact via standardized protocol

## Technical Architecture Options

### Option A: Native Linux MCP Server
```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Claude/Pi     │────▶│  MCP Client     │────▶│  MCP Server     │
│   (Agent)       │     │  (stdio bridge) │     │  (python/node)  │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                       │
              ┌────────────────────────────────────────┴────────────────────────────────┐
              │                    Linux Desktop Abstraction Layer                         │
              │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
              │  │   X11       │  │  Wayland    │  │  AT-SPI     │  │  Xvfb       │    │
              │  │   Driver    │  │  Driver     │  │  Bridge     │  │  Driver     │    │
              │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    │
              └────────────────────────────────────────────────────────────────────────┘
```

### Option B: Unified CLI + MCP Hybrid
```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Claude/Pi     │────▶│  MCP Client     │────▶│  linux-computer-│
│   (Agent)       │     │                 │     │  use MCP Server │
└─────────────────┘     └────────┬────────┘     └────────┬────────┘
                                │                         │
                                │              ┌─────────▼─────────┐
                                │              │   CLI Interface   │
                                │              │ (bash/python)     │
                                │              └─────────┬─────────┘
                                │                        │
                                │             ┌───────────▼───────────┐
                                │             │  Desktop Abstraction  │
                                │             │  (X11/Wayland/AT-SPI) │
                                │             └───────────────────────┘
                                │
                 ┌──────────────▼──────────────┐
                 │  Room/Terminal Integration  │
                 └─────────────────────────────┘
```

## Key Features to Prioritize

### Phase 1: Foundation (MVP)
1. **Unified Discovery API**
   - `list_apps()` - All discoverable applications
   - `list_windows()` - All open windows with metadata
   - `get_window_state()` - Element tree + screenshot
   - Works across X11, Wayland, AT-SPI

2. **Basic Interaction**
   - `click(element)` / `click(coordinate)`
   - `type(text, element)` 
   - `press_key(keys, element)`
   - `scroll(direction, amount, element)`

3. **Screenshot System**
   - `screenshot_window(window_id)` 
   - `screenshot_desktop(region?)`
   - `screenshot_element(element)` 

### Phase 2: Enhanced Capabilities
4. **Form Controls**
   - `set_value(element, value)` - For inputs, dropdowns, sliders
   - `select_option(element, value)` - For complex dropdowns

5. **Drag & Drop**
   - `drag(from, to, element?)`
   - `drop(element, target)`

6. **Context Awareness**
   - `get_app_info(app)` - Process info, version, capabilities
   - `detect_desktop_env()` - GNOME/KDE/XFCE detection

### Phase 3: Production Hardening
7. **Safety & Validation**
   - `preview_action(action)` - Dry-run simulation
   - `undo_last()` - Rollback capability
   - `is_safe_to_click(element)` - Risk assessment

8. **Performance**
   - `batch_capture()` - Multiple windows in one call
   - `cache_tree()` - Cache element trees with TTL
   - `diff_tree(old, new)` - Detect changes efficiently

9. **Remote Integration**
   - `ssh_tunnel(host)` - Remote desktop protocol
   - `session_id` - Persistent session tracking
   - `replay(session)` - Record + replay interactions

## Design Principles

### 1. "Observe First, Act Second"
Never click without a fresh capture. Every action must be preceded by observation.

### 2. Element Tokens > Coordinates
Prefer `element_token` over `x,y` coordinates. Tokens are session-scoped and verifiable.

### 3. Deterministic Verification
After every action, verify with a fresh capture. Return structured verdicts.

### 4. Graceful Degradation
If AT-SPI isn't available, fall back to image-based + pixel targeting.

### 5. Safety-First Design
Block on password dialogs, 2FA, payment screens. Never automate secrets.

## Integration Points

### With Existing Ecosystem

1. **Pi Framework**
   - Integrate as MCP server: `@pi/linux-computer-use`
   - Provide Pi tools that map to desktop actions
   - Support both `stdio` and WebSocket transports

2. **Agnes Agent**
   - Provide reference implementation for computer_use wrapper
   - Extend with Linux-specific capabilities
   - Enable background-first execution

3. **Room CLI**
   - Extend `computer-use` subcommand with Linux support
   - Add `linux-computer-use` command for direct access
   - Enable hybrid cloud+local workflows

4. **Manus Studio**
   - Add computer use as a testing/integration feature
   - Visual QA for AI-generated content
   - Debug panel for agent actions

## Technical Stack Recommendations

### Core
- **Language**: Python 3.12 (for AT-SPI/PyGObject) + Node.js addon
- **MCP SDK**: `@modelcontextprotocol/sdk` (TypeScript)
- **X11**: `python-xlib` or `xdotool` bindings
- **Wayland**: `wayland` Python bindings
- **AT-SPI**: `PyGObject` with `PyGObject` + `atspi` module
- **Image Processing**: `opencv-python` or `Pillow`

### Optional (if Node.js preferred)
- **EWS**: `node-ewmh` for EWMH hints
- **Wayland**: `node-wayland` (if available) or native addon
- **AT-SPI**: Native node addon or Python bridge

## Success Metrics

1. **Reliability**: 99% success rate on common desktop interactions
2. **Speed**: <500ms round-trip for action + verification
3. **Coverage**: Works with 90%+ of desktop apps (GTK, Qt, Electron, Java Swing)
4. **Integration**: Works seamlessly with Pi, Agnes, Room CLI

## Next Actions (Concrete Steps)

1. **Create repository structure**
   - `src/python/` - Python drivers (X11, Wayland, AT-SPI)
   - `src/mcp/` - MCP server implementation
   - `src/cli/` - CLI interface
   - `src/types/` - Shared TypeScript types
   - `tests/` - Integration tests

2. **Prototype Phase 1**
   - Build discovery API for X11
   - Implement basic click/type/screenshot
   - Create MCP wrapper

3. **Integration Testing**
   - Test with common apps: Firefox, GNOME apps, Qt apps
   - Verify with Pi agents
   - Document known limitations

## Questions to Resolve

1. **Wayland Support**: How critical is Wayland for target users?
2. **AT-SPI Depth**: How deep should we go into accessibility tree?
3. **Security Model**: What level of desktop access should agents have?
4. **Remote Desktop**: Should we support SSH/X2Go/VNC protocols?

---

## Appendix: Competitive Analysis

### Existing Solutions

| Tool | Platforms | Strengths | Weaknesses |
|------|-----------|-----------|------------|
| Cua Driver | Local, Cloud | Mature, safety-checked | Limited to controlled env |
| Room CLI | Linux (cloud) | Virtual desktop ready | No real desktop support |
| Sikuli | All | Image-based, flexible | Slow, unreliable |
| PyAutoGUI | All | Simple, cross-platform | Platform-specific issues |
| AutoIt | Windows | Mature | Windows-only |
| Robot Framework | All | Testing-focused | Complex setup |

### Our Advantage
- Unified X11/Wayland/AT-SPI abstraction
- MCP-native integration
- Designed for AI agents from day one
- Focus on deterministic verification

---

*Brainstorming complete. Ready for goal-writer to create formal GOAL.md*