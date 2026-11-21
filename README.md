# linux_computer_use

A production-grade, unified desktop control layer for Linux that enables AI agents, QA tools, and automation scripts to discover, interact with, and verify desktop applications across X11, Wayland, and AT-SPI accessibility layers.

## Overview

linux_computer_use provides a consistent MCP (Model Context Protocol) interface for:

- ✅ **Desktop Discovery**: List apps and windows across platforms
- ✅ **UI Interaction**: Click, type, scroll, drag-and-drop
- ✅ **Visual Verification**: Screenshots at window/element level
- ✅ **Safety-First**: Automatic blocking of sensitive dialogs
- ✅ **Deterministic**: Action + verification pattern

## Quick Start

### Prerequisites

```bash
# Linux desktop with X11 or Wayland
# Python 3.12+
# Node.js 24+ (for MCP client tools)

# Install dependencies
pip install -e .
```

### Starting the MCP Server

```bash
# Via Python
python -m linux_computer_use.mcp

# Or with npx
npx linux-computer-use
```

### Using with an AI Agent

1. Configure the MCP server in your agent's config:

```json
{
  "mcpServers": {
    "linux-computer-use": {
      "command": "python",
      "args": ["-m", "linux_computer_use.mcp"]
    }
  }
}
```

2. In your agent prompt:

```yaml
Tools available:
- list_apps() - List desktop applications
- list_windows() - List open windows  
- get_window_state(window_id) - Get UI tree + screenshot
- click(element, window_id) - Click an element
- type_text(text, element, window_id) - Type text
- screenshot_window(window_id) - Capture window
```

### Example Workflow

```yaml
# Agent thinking...
I need to fill a form in LibreOffice Writer.

Step 1: Discover LibreOffice window
> list_windows()

Step 2: Get UI state
> get_window_state(window_id=123)
Returns element tree with buttons, inputs, menu bar

Step 3: Click "Edit" menu
> click(element=5, window_id=123)

Step 4: Type text into document
> type_text("Hello, World!", element=25, window_id=123)

Step 5: Verify result
> screenshot_window(window_id=123) → Verify text appears
```

## Available Tools

### Discovery Tools

| Tool | Description | Returns |
|------|-------------|---------|
| `list_apps()` | List discoverable applications | App list with metadata |
| `list_windows()` | List open windows | Window list with state |
| `get_app_info(app_id)` | Get app details | Process info, version |

### Interaction Tools

| Tool | Description | Returns |
|------|-------------|---------|
| `click(element, window_id)` | Click element by index/token | `{ effect: "confirmed" \| "failed" }` |
| `click(coordinate, window_id)` | Click at coordinates | `{ effect: "..." }` |
| `type_text(text, element, window_id)` | Type into input field | Verification result |
| `press_key(keys, window_id)` | Keyboard shortcuts | Action result |
| `scroll(direction, amount, element, window_id)` | Scroll container | Scroll result |

### Screenshot Tools

| Tool | Description | Returns |
|------|-------------|---------|
| `screenshot_desktop(region?)` | Full or region screenshot | PNG path + base64 |
| `screenshot_window(window_id)` | Window screenshot | PNG path + base64 |
| `screenshot_element(element, window_id)` | Element screenshot | PNG path + base64 |

## AI Agent Integrations

### Supported Agents

| Agent | Integration | Use Case |
|-------|-------------|----------|
| **Opencode** | `OpencodeIntegration` | CLI-based code agent, good for automated workflows |
| **Kimi K2** | `KimiIntegration` | Multimodal analysis via API, vision+text |
| **OpenClaude** | `OpenClaudeIntegration` | Open-source Claude-style agent |
| **Anti-Gravity** | `AntiGravityIntegration` | Orientation-flexible agentic workflows |
| **Hermes** | `HermesIntegration` | Multi-agent messaging and broker |

### Quick Start with AI Agents

```python
from linux_computer_use import OpencodeIntegration, get_tool_proxy

# Initialize integration
agent = OpencodeIntegration()

# Start session
session = await agent.start_session()

# List windows
result = await agent.call_tool(session, "list_windows", {})

# Click an element
result = await agent.call_tool(session, "click", {"element": 5, "window_id": 1})

# Type text
result = await agent.call_tool(session, "type_text", {"text": "Hello!", "element": 10, "window_id": 1})

# End session
await agent.end_session(session)
```

### Direct Tool Access

```python
from linux_computer_use import get_tool_proxy

proxy = get_tool_proxy()

# Direct tool access without agent session
windows = await proxy.list_windows()
state = await proxy.get_window_state(windows[0].window_id)
screenshot = await proxy.screenshot_window(windows[0].window_id)
```

## Architecture

```
┌─────────────────┐
│  AI Agent       │
│  (Claude, Pi,   │
│   Cline, etc.)  │
└────────┬────────┘
         │ stdio/WebSocket
         ▼
┌──────────────────────────────────┐
│  MCP Server                      │
│  - Tool routing                  │
│  - Session management            │
│  - Security validation           │
└────────┬─────────────────────────┘
         │
         ├──────────────┐
         │              │
         ▼              ▼
┌──────────────┐ ┌──────────────┐
│  X11 Driver  │ │  Wayland     │
│  (Primary)   │ │  Driver      │
└──────────────┘ ├──────────────┤
                 │  AT-SPI      │
                 │  Bridge      │
                 └──────────────┘
```

## Supported Platforms

| Platform | Read | Write | Notes |
|----------|------|-------|-------|
| X11 (most Linux) | ✅ | ✅ | Full support |
| Wayland (GNOME/KDE) | ⚠️ | ⚠️ | Read-only (compositor restrictions) |
| Xvfb (Virtual) | ✅ | ✅ | Testing environments |
| AT-SPI (Accessibility) | ✅ | ✅ | Integrated with X11/Wayland |

## Development

### Project Structure

```
linux-computer-use/
├── src/
│   ├── python/           # Python drivers
│   │   ├── drivers/      # X11, Wayland, AT-SPI
│   │   ├── mcp/          # MCP server
│   │   └── session.py    # Session management
│   ├── cli/              # CLI tool
│   └── types/            # Shared types
├── tests/
│   ├── unit/             # Unit tests
│   ├── integration/      # Integration tests
│   └── e2e/              # End-to-end tests
├── dev-notes/
│   ├── GOAL.md           # Project goals
│   ├── SPEC.md           # Technical spec
│   ├── SECURITY.md       # Security requirements
│   └── TESTING.md        # Test strategy
└── package.json
```

### Development Setup

```bash
# Clone and install
git clone <repo>
cd linux-computer-use

# Python setup
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]

# Node.js setup
pnpm install

# Install test apps (Ubuntu/Debian)
sudo apt-get install -y gnome-calculator firefox gedit libreoffice
```

### Running Tests

```bash
# Unit tests
pytest tests/unit/ -v

# Integration tests (requires DISPLAY)
export DISPLAY=:99
Xvfb :99 -screen 0 1920x1080x24 &
pytest tests/integration/ -v

# All tests
pnpm test
```

### Code Quality

```bash
# Python
mypy src/python/
ruff check src/python/
pytest tests/

# TypeScript
pnpm tsc --noEmit
pnpm lint
pnpm build
```

## Security

This project follows security-first principles:

- 🔒 **No password/PII handling** - Automatically blocks sensitive dialogs
- 🔒 **Session isolation** - Temp files securely cleaned
- 🔒 **Input validation** - All inputs validated at trust boundary
- 🔒 **Audit logging** - All actions logged for audit

See [SECURITY.md](SECURITY.md) for full security requirements.

## Testing

See [TESTING.md](TESTING.md) for comprehensive test strategy.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Run quality gates: `mypy`, `ruff`, `pytest`
5. Submit PR with description

## License

MIT — See LICENSE file for details.

---

**Status**: Phase 1 (MVP) in progress  
**Documentation**: [README.md](README.md) • [GOAL.md](dev-notes/GOAL.md) • [SPEC.md](dev-notes/SPEC.md) • [SECURITY.md](dev-notes/SECURITY.md) • [TESTING.md](dev-notes/TESTING.md)