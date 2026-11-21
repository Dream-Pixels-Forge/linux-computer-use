# GOAL.md — linux_computer_use

**Written with goal-writer (2026-11-14)**

## Goal: Build a unified, production-grade desktop control layer for Linux

### Objective

Deliver **linux_computer_use**: a Python/TypeScript hybrid MCP server that provides consistent, deterministic desktop interaction across X11, Wayland, and AT-SPI accessibility layers. The server enables AI agents, QA tools, and automation scripts to discover, interact with, and verify desktop applications on Linux — whether on local real desktop, virtual environments (Xvfb), or containerized apps.

### Context

Current solutions (`computer-use-linux` MCP server, Room CLI computer-use, Agnes wrapper) have gaps:
- X11-only or limited Wayland support
- No unified interface for local vs virtual desktops  
- Inconsistent error handling across platforms
- Missing deterministic verification loop

This creates unpredictable agent behavior and unreliable test automation. The next project to build, as logged in memorius: **"linux_computer_use, the better version of computer-use-linux extension which working well without issues, we meet"**.

### Who It's For

- **AI Agent Developers**: Test agents against real GUI applications
- **QA Automation Engineers**: Visual regression testing for desktop apps
- **Accessibility Researchers**: Test screen readers and AT-SPI
- **Container/Desktop Developers**: Test apps in isolated environments

---

## Phase 1: Foundation (MVP)

### 1.1 Repository Structure

**Goal**: Create clean, extensible project structure

```
linux-computer-use/
├── src/
│   ├── python/           # Python drivers (X11, Wayland, AT-SPI)
│   ├── mcp/              # MCP server implementation
│   ├── cli/              # CLI interface
│   └── types/            # Shared TypeScript types
├── tests/
│   ├── integration/      # macOS, Firefox, GNOME apps
│   └── unit/             # Unit tests for drivers
├── dev-notes/
│   ├── GOAL.md           # This file
│   ├── SPEC.md           # Architecture, APIs, data models
│   ├── SECURITY.md       # Threat model, security requirements
│   └── TESTING.md        # Test strategy, environments
├── pyproject.toml        # Python dependencies
├── package.json          # Node.js/MCP dependencies
├── README.md
└── dev.Dockerfile        # Test environment
```

**Verification**: 
- [ ] Repository created with above structure
- [ ] `pyproject.toml` with Python 3.12, AT-SPI, X11 deps
- [ ] `package.json` with MCP SDK, TypeScript
- [ ] CI workflow configured

### 1.2 Discovery API - X11 Support

**Goal**: Discover and describe windows/applications on X11

**Features**:
- `list_apps()` - All discoverable applications with metadata
- `list_windows()` - All open windows with title, pid, geometry
- `get_window_state(window_id)` - Element tree + screenshot
- Works with GTK, Qt, Electron apps

**Verification**:
- [ ] Test with Firefox: `list_windows` returns at least 1 entry
- [ ] Test with GNOME Calculator: `get_window_state` returns AT-SPI tree
- [ ] Screenshot saved as PNG, verifyable via CLI
- [ ] TypeScript types exported correctly

### 1.3 Basic Interaction - X11

**Goal**: Click, type, scroll on X11 applications

**Features**:
- `click(element=N)` - Click by element token or coordinate
- `type(text, element=N)` - Type into inputs
- `press_key(keys, element=N)` - Keyboard shortcuts
- `scroll(direction, amount, element=N)` - Scroll containers

**Verification**:
- [ ] Click GNOME Calculator button: result changes
- [ ] Type in Firefox address bar: text appears
- [ ] Scroll GTK TextView: content moves
- [ ] Return structured verdict: `{ effect: "confirmed" | "unverifiable" }`

### 1.4 Screenshot System

**Goal**: Capture screenshots at various scopes

**Features**:
- `screenshot_desktop(region?)` - Full desktop or region
- `screenshot_window(window_id)` - Specific window
- `screenshot_element(element)` - Specific UI element
- Return: file path + base64 encoding

**Verification**:
- [ ] Desktop screenshot: 1920x1080 PNG created
- [ ] Window screenshot: matches window geometry
- [ ] Element screenshot: crops to element bounds
- [ ] MCP tool returns valid file path

### 1.5 MCP Server Wrapper

**Goal**: Expose desktop API via MCP protocol

**Features**:
- All Phase 1 tools exposed as MCP tools
- `call_tool(name, arguments)` interface
- Tool listing and introspection
- stdio transport (language-agnostic)

**Verification**:
- [ ] MCP server starts without errors
- [ ] `tools/list` returns all Phase 1 tools
- [ ] `tools/call` executes action successfully
- [ ] Integration test with Claude/ Pi agent

---

## Phase 2: Enhanced Capabilities

### 2.1 AT-SPI Deep Integration

**Goal**: Full accessibility tree traversal

**Features**:
- Complete AT-SPI tree with roles, states, relations
- Role-based targeting (`role="button"`, `role="text input"`)
- State verification before interaction
- Text content extraction from accessible elements

**Verification**:
- [ ] GNOME Calculator: extract button labels from AT-SPI
- [ ] Firefox: get address bar text content
- [ ] Qt app: verify button states (enabled/disabled)

### 2.2 Wayland Support (Basic)

**Goal**: Read-only Wayland support

**Features**:
- `list_windows()` for Wayland apps
- `screenshot_window()` for Wayland apps
- Fallback to root window for unsupported elements

**Verification**:
- [ ] GNOME Terminal: list windows
- [ ] Screenshot GNOME Files window
- [ ] Graceful degradation when AT-SPI unavailable

### 2.3 Form Controls

**Goal**: Interact with complex form elements

**Features**:
- `set_value(element, value)` - For inputs, text areas
- `select_option(element, value)` - For select/combobox
- `check_checkbox(element)` - For checkboxes
- `toggle_radio(element)` - For radio groups

**Verification**:
- [ ] Fill HTML form in Firefox: fields populated
- [ ] Select option in GTK dropdown: selection changes
- [ ] Check LibreOffice checkbox: state toggles

### 2.4 Drag & Drop

**Goal**: Drag-and-drop interactions

**Features**:
- `drag(from_element, to_element)` - Element-based drag
- `drag(from_coordinate, to_coordinate)` - Pixel drag
- Visual feedback during drag

**Verification**:
- [ ] Drag file to GNOME Trash: file deleted
- [ ] Drag text between apps: clipboard updated

---

## Phase 3: Production Hardening

### 3.1 Safety & Validation

**Goal**: Prevent unsafe interactions

**Features**:
- `preview_action(action)` - Dry-run simulation
- `is_safe_to_click(element)` - Risk assessment
- Block lists for password, payment, 2FA screens
- User confirmation for sensitive actions

**Verification**:
- [ ] Password dialog detected and blocked
- [ ] Preview returns expected coordinates
- [ ] Safety check on system dialogs

### 3.2 Performance Optimization

**Goal**: Fast, reliable operations

**Features**:
- `batch_capture()` - Multiple windows in one call
- `cache_tree()` - Cache element trees with TTL (default: 2s)
- `diff_tree(old, new)` - Detect changes efficiently
- Connection pooling for MCP client

**Verification**:
- [ ] 10 window captures in <100ms total
- [ ] Cached tree returns instantly
- [ ] MCP round-trip <500ms

### 3.3 Remote Integration

**Goal**: Enable remote desktop scenarios

**Features**:
- `ssh_tunnel(host)` - Remote SSH connection
- `session_id` - Persistent session tracking
- `replay(session)` - Record + replay interactions
- Environment variables for DISPLAY, WAYLAND_DISPLAY

**Verification**:
- [ ] SSH tunnel established to remote host
- [ ] Session record captures full interaction
- [ ] Replay reproduces actions on remote desktop

---

## Quality Gates

### Code Quality
```bash
# Python
python -m pytest tests/ -v           # All tests passing
ruff check src/python/              # Zero lint errors
mypy src/python/                    # Zero type errors

# TypeScript
pnpm install
pnpm tsc --noEmit                   # Zero type errors
pnpm lint                           # Zero warnings
pnpm build                          # Build succeeds
```

### Integration Testing
```bash
# Test environment with Xvfb
docker compose -f tests/docker-compose.yml up -d
python -m pytest tests/integration/ -v

# Test with MCP client
node tests/mcp-client-test.js
```

### Documentation
- [ ] README with setup and usage
- [ ] API reference (OpenAPI/Swagger compatible)
- [ ] Troubleshooting guide
- [ ] Platform compatibility matrix

---

## Definition of Done (Phase 1)

Package is production-ready when these gates pass:

| Gate | Command | Success Criteria |
|------|---------|------------------|
| Type Check (Python) | `mypy src/python/` | 0 errors |
| Lint (Python) | `ruff check .` | 0 errors |
| Test (Python) | `pytest tests/ -q` | 0 failed |
| Type Check (TS) | `pnpm tsc --noEmit` | 0 errors |
| Lint (TS) | `pnpm lint` | 0 warnings |
| Build | `pnpm build` | Exit 0 |
| MCP Server | `python -m linux_computer_use.mcp start` | Starts, lists tools |
| X11 Discovery | Test: Firefox, Calculator | Elements detected |
| Basic Interaction | Test: Click, Type | Actions verified |
| Screenshot | Test: Desktop, Window | PNG files created |
| MCP Integration | Test: Cline/Pi | Tools callable |

---

## Non-Goals (Phase 1)

- Wayland write operations (only read)
- Remote desktop (SSH tunneling)
- Recording/replay (session logging)
- Mobile/desktop app detection
- Browser automation (use browser-harness instead)
- File system operations (use file tools instead)

---

## Verification Steps

1. **Setup**: Clone, install deps, start Xvfb
2. **Discovery**: Run `list_apps`, `list_windows`
3. **Interaction**: Run `click`, `type_text` on test apps
4. **Verification**: Check action results
5. **MCP**: Connect MCP client, call tools
6. **Integration**: Run with Claude/ Pi agent

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| AT-SPI not available | Medium | High | Fallback to X11/pixel targeting |
| Wayland changes | High | Medium | Monitor protocol, abstract layer |
| Security concerns | Medium | High | Safety-first design, validation |
| Performance issues | Medium | Medium | Caching, batching, profiling |

---

*Next: Use spec-driven-development to create detailed specification, then implement with subagent-driven-development approach.*