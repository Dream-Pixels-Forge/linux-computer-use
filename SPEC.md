# SPEC.md — linux_computer_use Technical Specification

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLIENT LAYER                                  │
├─────────────────────────────────────────────────────────────────────┤
│  Pi Agent  │  Claude  │  Cline  │  Custom Scripts  │  MCP Clients   │
└────────────────────────┬────────────────────────────────────────────┘
                         │ stdio / WebSocket
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      MCP SERVER LAYER                                │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  linux_computer_use MCP Server                                │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │  Tool Router     │  Discovery  │  Interaction │  Utils │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
└────────────────────────┬────────────────────────────────────────────┘
                         │ Python
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   DRIVER LAYER (Python)                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │   X11       │  │  Wayland    │  │  AT-SPI     │  │  Xvfb       │  │
│  │   Driver    │  │  Driver     │  │  Bridge     │  │  Driver     │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## API Specification

### Tools (MCP)

#### `list_apps`
**Description**: List all discoverable desktop applications

**Input Schema**:
```typescript
{
  type: "object",
  properties: {},
  required: []
}
```

**Output Schema**:
```typescript
{
  type: "object",
  properties: {
    apps: {
      type: "array",
      items: {
        type: "object",
        properties: {
          id: { type: "string" },           // Unique app identifier
          name: { type: "string" },         // Display name
          executable: { type: "string" },   // Executable path
          pid: { type: "number" },          // Process ID (if running)
          desktop_file: { type: "string" }, // .desktop file path
          categories: { 
            type: "array", 
            items: { type: "string" } 
          },
          running: { type: "boolean" }
        }
      }
    }
  }
}
```

---

#### `list_windows`
**Description**: List all open windows

**Input Schema**:
```typescript
{
  type: "object",
  properties: {
    app: { type: "string" }  // Optional: filter by app
  },
  required: []
}
```

**Output Schema**:
```typescript
{
  type: "object",
  properties: {
    windows: {
      type: "array",
      items: {
        type: "object",
        properties: {
          window_id: { type: "integer" },
          pid: { type: "number" },
          app_id: { type: "string" },
          title: { type: "string" },
          geometry: {
            type: "object",
            properties: {
              x: { type: "number" },
              y: { type: "number" },
              width: { type: "number" },
              height: { type: "number" }
            }
          },
          workspace: { type: "number" },
          visible: { type: "boolean" },
          app: { type: "string" }  // Human-readable app name
        }
      }
    }
  }
}
```

---

#### `get_window_state`
**Description**: Get detailed state of a window

**Input Schema**:
```typescript
{
  type: "object",
  properties: {
    window_id: { type: "integer" },
    pid: { type: "number" }  // Optional: for unambiguous targeting
  },
  required: ["window_id"]
}
```

**Output Schema**:
```typescript
{
  type: "object",
  properties: {
    window_id: { type: "integer" },
    pid: { type: "number" },
    screenshot_path: { type: "string" },  // Path to screenshot PNG
    tree_markdown: { type: "string" },  // AT-SPI tree as markdown
    elements: {
      type: "array",
      items: {
        type: "object",
        properties: {
          index: { type: "number" },
          element_token: { type: "string" },  // Session-scoped token
          role: { type: "string" },  // e.g., "button", "text input"
          name: { type: "string" },  // Accessible name
          description: { type: "string" },  // ARIA description
          state: {
            type: "array",
            items: { type: "string" }  // e.g., "focusable", "pressed"
          },
          geometry: {
            type: "object",
            properties: {
              x: { type: "number" },
              y: { type: "number" },
              width: { type: "number" },
              height: { type: "number" }
            }
          },
          parent_index: { type: "number" },
          children: {
            type: "array",
            items: { type: "number" }  // Child indices
          }
        }
      }
    }
  }
}
```

---

#### `click`
**Description**: Click on an element or coordinate

**Input Schema**:
```typescript
{
  type: "object",
  properties: {
    element: { type: "integer" },  // Element index
    element_token: { type: "string" },  // Or token for verification
    coordinate: {
      type: "object",
      properties: {
        x: { type: "number" },
        y: { type: "number" }
      }
    },
    button: { 
      type: "string", 
      enum: ["left", "right", "middle"],
      default: "left"
    },
    window_id: { type: "integer" }
  },
  required: [],
  oneOf: [
    { "required": ["element"] },
    { "required": ["coordinate"] },
    { "required": ["element_token"] }
  ]
}
```

**Output Schema**:
```typescript
{
  type: "object",
  properties: {
    effect: {
      type: "string",
      "enum": ["confirmed", "unverifiable", "suspected_noop"]
    },
    recommendation: { type: "string" },
    window_id: { type: "integer" }
  }
}
```

---

#### `type_text`
**Description**: Type text into an element

**Input Schema**:
```typescript
{
  type: "object",
  "properties": {
    text: { type: "string" },
    element: { type: "integer" },
    element_token: { type: "string" },
    window_id: { type: "integer" }
  },
  "required": ["text"],
  "oneOf": [
    { "required": ["element"] },
    { "required": ["element_token"] }
  ]
}
```

---

#### `press_key`
**Description**: Press a keyboard key or key combination

**Input Schema**:
```typescript
{
  type: "object",
  "properties": {
    keys: { 
      "type": "string",
      "description": "Key combination (e.g., 'ctrl+c', 'Enter', 'Tab')"
    },
    element: { type: "integer" },
    element_token: { type: "string" },
    window_id: { type: "integer" }
  },
  "required": ["keys"]
}
```

---

#### `scroll`
**Description**: Scroll within an element

**Input Schema**:
```typescript
{
  type: "object",
  "properties": {
    direction: {
      type: "string",
      "enum": ["up", "down", "left", "right"]
    },
    amount: {
      type: "integer",
      "minimum": 1,
      "maximum": 100,
      "default": 10
    },
    element: { type: "integer" },
    element_token: { type: "string" },
    window_id: { type: "integer" }
  },
  "required": ["direction"]
}
```

---

#### `screenshot_desktop`
**Description**: Take a screenshot of the entire desktop

**Input Schema**:
```typescript
{
  type: "object",
  "properties": {
    region: {
      "type": "object",
      "properties": {
        x: { type: "number" },
        y: { type": "number"},
        width: { type: "number" },
        height: { type: "number" }
      }
    }
  }
}
```

**Output Schema**:
```typescript
{
  type: "object",
  "properties": {
    path: { type: "string" },
    "base64": { type: "string" }
  }
}
```

---

#### `screenshot_window`
**Description**: Take a screenshot of a specific window

**Input Schema**:
```typescript
{
  type: "object",
  "properties": {
    window_id: { type: "integer" }
  },
  "required": ["window_id"]
}
```

---

#### `screenshot_element`
**Description**: Take a screenshot of a specific UI element

**Input Schema**:
```typescript
{
  type: "object",
  "properties": {
    element: { type: "integer" },
    element_token: { type: "string" },
    window_id: { type: "integer" }
  },
  "required": ["element", "window_id"]
}
```

---

## Data Flow Diagrams

### Discovery Flow
```
Client → list_apps() → Scan .desktop files + running processes → Return app list
Client → list_windows() → Query X11/Wayland → Return window metadata
Client → get_window_state(window_id) → Capture + AT-SPI tree → Return state
```

### Interaction Flow  
```
1. Client calls get_window_state → fresh capture with element tokens
2. Client calls click(element=12) or click(coordinate=[x,y])
3. Driver executes click, verifies by capturing new state
4. Driver returns structured verdict: effect + recommendation
5. Client verifies effect matches expectation
```

### Screenshot Flow
```
Client → screenshot_desktop()
  → Create temp PNG file
  → Capture X11 root window or Wayland output
  → Encode to base64
  → Return { path: "/tmp/screenshot_xxx.png", base64: "..." }
```

---

## Driver Implementation Details

### X11 Driver (`src/python/drivers/x11.py`)

**Dependencies**:
- `python-xlib` - X11 protocol access
- `python-ewmh` - EWMH window management hints
- `PIL` - Screenshot capture via XGetImage

**Key Functions**:
```python
def list_windows() -> List[WindowInfo]:
    """Query _NET_CLIENT_LIST and _NET_WM_NAME atoms"""

def get_window_tree(window_id: int) -> ATSPINode:
    """Query accessibility via AT-SPI bridge"""

def capture_window(window_id: int) -> bytes:
    """XGetImage + PIL conversion to PNG"""
```

### Wayland Driver (`src/python/drivers/wayland.py`)

**Dependencies**:
- `wayland` python bindings (or direct protocol)
- `xdg-foreign` for window identification

**Limitations**:
- Read-only access (Wayland security model)
- Requires compositor support (GNOME Shell, KDE Plasma)

### AT-SPI Bridge (`src/python/drivers/atspi.py`)

**Dependencies**:
- `PyGObject` with `gi.repository.Atspi`
- `gi.repository.GLib` for event loops

**Features**:
- Full accessibility tree traversal
- Event listening (accessible-state-change, etc.)
- Role/state mapping to semantic types

---

## Session Management

### Element Tokens
Element tokens are:
- **Session-scoped**: Valid only for current MCP session
- **Cryptographically signed**: Prevent token guessing
- **Time-limited**: 30 seconds by default
- **Verifiable**: Token includes window_id, element_index, snapshot_hash

```python
def create_element_token(window_id: int, index: int, snapshot_hash: str) -> str:
    payload = f"{window_id}:{index}:{snapshot_hash}:{timestamp}"
    signature = hmac.new(SECRET, payload.encode(), sha256).hexdigest()
    return base64.urlsafe_b64encode(payload.encode()).decode()
```

### Verification Loop
After every mutation:
1. Capture fresh window state
2. Verify requested element exists at expected location
3. Check effect matches expected outcome
4. Return structured verdict

---

## Error Handling

### Common Errors

| Error | Cause | Mitigation |
|-------|-------|------------|
| `element_not_found` | Stale token, window closed | Request fresh capture |
| `target_busy` | Window being modified | Retry with exponential backoff |
| `unsafe_dialog` | Password/payment screen | Block, require user review |
| `not_implemented` | Feature not yet implemented | Return guidance |
| `timeout` | Operation took too long | Report timeout, suggest smaller actions |

### Recovery Patterns

```python
def recover_from_stale(target: ActionTarget) -> Recovery:
    """Recovery pattern for stale targets"""
    fresh_state = get_window_state(target.window_id)
    element = find_element_in_tree(fresh_state.elements, target.spec)
    
    if element:
        return Recovery(
            action="retry",
            target=ElementTarget(element.index, element.token)
        )
    else:
        return Recovery(
            action="fail",
            reason="Element not found in fresh capture"
        )
```

---

## Configuration

### Environment Variables
```bash
# Display configuration
DISPLAY=:99                    # X11 display
WAYLAND_DISPLAY=wayland-0     # Wayland display

# MCP settings
LINUX_COMPUTER_USE_CACHE_TTL=2    # Seconds to cache element trees
LINUX_COMPUTER_USE_TIMEOUT=30     # Action timeout  

# Security
LINUX_COMPUTER_USE_ALLOW_PASSWORD=false  # Block password dialogs
LINUX_COMPUTER_USE_ALLOW_PAYMENT=false   # Block payment dialogs
```

### MCP Server Config (`linux-computer-use.json`)
```json
{
  "name": "linux-computer-use",
  "version": "0.1.0",
  "capabilities": ["desktop-control", "accessibility"],
  "transport": "stdio",
  "cache_ttl": 2,
  "timeout": 30,
  "security": {
    "allow_password_dialogs": false,
    "allow_payment_dialogs": false
  }
}
```

---

## Testing Strategy

### Unit Tests
- Driver-level tests for X11/Wayland/AT-SPI abstractions
- Token generation/verification logic
- Error handling edge cases

### Integration Tests
- Real desktop apps: Firefox, GNOME Calculator, LibreOffice
- Virtual environment: Xvfb with test apps
- MCP client integration: Claude, Cline, Pi

### Test Environment
```dockerfile
# dev.Dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    xvfb \
    x11-apps \
    libgtk-3-0 \
    libxtst6 \
    libatspi2.0-0 \
    python3-pygobject \
    python3-xlib \
    && rm -rf /var/lib/apt/lists/*

COPY . /app
WORKDIR /app
RUN pip install -e .
```

---

## Future Extensions (Post-MVP)

1. **Wayland Write Operations** - When compositor permissions allow
2. **SSH Tunneling** - Remote desktop via SSH
3. **Session Recording** - Record interactions for replay/debugging
4. **Performance Metrics** - Latency tracking, performance profiling
5. **Multi-Monitor Support** - Coordinate space management
6. **Input Device Emulation** - Simulate mouse/keyboard devices

---

*Specification versioned: 0.1.0 (Initial)*