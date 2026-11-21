# TESTING.md — linux_computer_use Test Strategy

## Test Philosophy

### Test Pyramid
```
     ┌─────────────────────────────────────┐
     │         E2E Integration Tests       │
     │  (Real desktop apps, MCP clients)   │
     │            20%                        │
     ├─────────────────────────────────────┤
     │        Component Tests              │
     │  (Driver functions, MCP tools)      │
     │            30%                        │
     ├─────────────────────────────────────┤
     │         Unit Tests                  │
     │  (Pure functions, validation,      │
     │   error handling)                    │
     │            50%                        │
     └─────────────────────────────────────┘
```

### Testing Principles
1. **Real Desktop**: Tests use actual desktop applications
2. **Deterministic**: Tests produce same results given same state
3. **Isolated**: Each test starts from known state
4. **Fast**: Unit tests <1s, integration tests <30s
5. **Observable**: Tests log actions for debugging

---

## Test Environments

### Virtual Environment (CI)
```dockerfile
# tests/docker-compose.yml
version: "3.8"
services:
  linux-computer-use-test:
    build:
      context: .
      dockerfile: tests/Dockerfile.test
    environment:
      - DISPLAY=:99
      - WAYLAND_DISPLAY=wayland-0
    volumes:
      - ./tests:/app/tests
      - /tmp/.X11-unix:/tmp/.X11-unix
    command: |
      bash -c "Xvfb :99 -screen 0 1920x1080x24 &
               sleep 1 &&
               python -m pytest tests/ -v"
```

### Local Development Environment
```bash
# Install test dependencies
pnpm install
pip install pytest pytest-asyncio playwright

# Start virtual desktop
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99

# Launch test apps
firefox &
gnome-calculator &
```

---

## Unit Tests

### Location: `tests/unit/`

### Test Patterns

#### 1. Input Validation Tests
```python
def test_click_input_validation():
    """Test click input validation"""
    
    # Valid inputs
    valid_cases = [
        {"element": 0},
        {"element": 100, "button": "left"},
        {"element_token": "abc123"},
        {"coordinate": {"x": 100, "y": 200}},
    ]
    
    for case in valid_cases:
        result = validate_click_input(case)
        assert result.valid, f"Failed on {case}"
    
    # Invalid inputs
    invalid_cases = [
        {"element": -1},
        {"coordinate": {"x": -10, "y": 100}},
        {"coordinate": {"x": "invalid", "y": 100}},  # type: ignore
    ]
    
    for case in invalid_cases:
        result = validate_click_input(case)
        assert not result.valid, f"Should fail on {case}"
```

#### 2. Token Generation Tests
```python
def test_element_token_roundtrip():
    """Test element token generation and verification"""
    
    # Generate token
    token = create_element_token(
        window_id=1,
        index=5,
        snapshot_hash="abc123"
    )
    
    # Verify token
    result = verify_element_token(token, window_id=1)
    assert result.valid
    assert result.index == 5
    assert result.snapshot_hash == "abc123"
    
    # Verify wrong window fails
    result = verify_element_token(token, window_id=2)
    assert not result.valid
```

#### 3. Session Management Tests
```python
def test_session_cleanup():
    """Test session cleanup removes temp files"""
    
    session = Session()
    
    # Create temp files
    temp_dir = session.temp_dir
    for i in range(3):
        with open(f"{temp_dir}/screenshot_{i}.png", "wb") as f:
            f.write(b"fake image data")
    
    # Cleanup
    session.cleanup()
    
    # Verify temp dir gone
    assert not os.path.exists(temp_dir)
    assert not os.path.exists(session.token_secret)  # Should be garbage
```

---

## Integration Tests

### Location: `tests/integration/`

### Test Strategy

#### 1. X11 Tests (Primary)
```python
import pytest
import subprocess
import time

@pytest.fixture(scope="module")
def x11_environment():
    """Setup X11 test environment"""
    # Start Xvfb
    subprocess.Popen([
        "Xvfb", ":99", "-screen", "0", "1920x1080x24"
    ])
    time.sleep(2)
    
    # Set display
    os.environ["DISPLAY"] = ":99"
    
    yield
    
    # Cleanup
    subprocess.run(["pkill", "Xvfb"])

@pytest.mark.integration
def test_list_windows_x11(x11_environment):
    """Test listing windows on X11"""
    
    # Start calculator
    calc = subprocess.Popen(["gnome-calculator"])
    time.sleep(2)
    
    # Test
    windows = list_windows()
    
    # Verify
    assert len(windows) >= 1
    calc_window = next(w for w in windows if "Calculator" in w.title)
    assert calc_window.app_id == "org.gnome.Calculator"
    
    # Cleanup
    calc.terminate()

@pytest.mark.integration
def test_click_element_x11(x11_environment):
    """Test clicking an element"""
    
    # Start calculator and enter 5+5
    calc = subprocess.Popen(["gnome-calculator"])
    time.sleep(2)
    
    # Get window state
    state = get_window_state(list_windows()[0].window_id)
    
    # Find '5' button (roughly)
    five_button = next(
        e for e in state.elements 
        if "5" in (e.name or e.description or "")
    )
    
    # Click
    result = click(element=five_button.index)
    assert result.effect == "confirmed"
    
    # Cleanup
    calc.terminate()
```

#### 2. Wayland Tests (if available)
```python
@pytest.mark.skipif(
    not os.environ.get("WAYLAND_DISPLAY"),
    reason="Wayland not available"
)
def test_wayland_discovery():
    """Test Wayland window discovery"""
    
    windows = list_windows()
    assert isinstance(windows, list)
    
    # Wayland windows should have different metadata
    for window in windows:
        assert hasattr(window, 'window_id')
```

#### 3. AT-SPI Tests
```python
@pytest.mark.integration
def test_atspi_tree_structure():
    """Test AT-SPI tree structure"""
    
    # Start LibreOffice Writer
    writer = subprocess.Popen(["libreoffice", "--writer"])
    time.sleep(5)  # Let it load
    
    # Get window
    windows = list_windows()
    writer_window = next(
        (w for w in windows if "LibreOffice" in w.title),
        None
    )
    
    if writer_window:
        state = get_window_state(writer_window.window_id)
        
        # Verify tree structure
        assert len(state.tree_markdown) > 0
        assert "text input" in state.tree_markdown.lower()
        
        # Verify element roles
        has_role = False
        for elem in state.elements:
            if elem.role in ["push button", "text input", "menu bar"]:
                has_role = True
                break
        
        assert has_role, "No expected roles found in tree"
    
    writer.terminate()
```

---

## End-to-End Tests

### Location: `tests/e2e/`

#### 1. MCP Client Integration Test
```python
import asyncio
from mcp import Client

@pytest.mark.e2e
async def test_mcp_click_workflow():
    """Test full MCP click workflow"""
    
    client = Client("linux-computer-use")
    
    # Start test app
    subprocess.Popen(["gedit", "/tmp/test.txt"])
    await asyncio.sleep(2)
    
    try:
        # List windows
        result = await client.call_tool("list_windows")
        windows = result["windows"]
        assert len(windows) > 0
        
        # Get window state
        state = await client.call_tool(
            "get_window_state",
            {"window_id": windows[0]["window_id"]}
        )
        
        # Find file menu button
        file_button = next(
            (e for e in state["elements"] if "File" in e.get("name", "")),
            None
        )
        
        assert file_button is not None, "File button not found"
        
        # Click File menu
        result = await client.call_tool(
            "click",
            {
                "element": file_button["index"],
                "window_id": windows[0]["window_id"]
            }
        )
        
        assert result["effect"] == "confirmed"
        
    finally:
        subprocess.run(["pkill", "gedit"])
```

#### 2. Claude/PI Agent Integration
```python
@pytest.mark.e2e
@pytest.mark.requires_agent
def test_with_claude_agent():
    """Test with Claude agent via MCP"""
    
    # This test requires Claude Desktop or similar
    # It verifies the agent can successfully control desktop
    
    # Setup: Create MCP config for agent
    with open("/tmp/claude-mcp-config.json", "w") as f:
        json.dump({
            "mcpServers": {
                "linux-computer-use": {
                    "command": "python",
                    "args": ["-m", "linux_computer_use.mcp"]
                }
            }
        }, f)
    
    # Agent would then:
    # 1. Call list_windows
    # 2. Call get_window_state
    # 3. Call click/type on elements
    # 4. Verify results
    
    # For now, just verify MCP server starts
    process = subprocess.Popen([
        "python", "-m", "linux_computer_use.mcp"
    ])
    
    # Give it time to initialize
    time.sleep(3)
    
    # Check it's still running (healthy server)
    assert process.poll() is None, "MCP server crashed"
    
    process.terminate()
```

---

## Test Data

### Test Applications
```yaml
# tests/applications.yaml
applications:
  - name: gnome-calculator
    id: org.gnome.Calculator
    roles: [push button, text, label]
    actions: [click_button, type_number]
    
  - name: firefox
    id: firefox
    roles: [push button, text input, list, menu bar]
    actions: [navigate, click_link, fill_form]
    
  - name: gedit
    id: org.gnome.gedit
    roles: [push button, text input, menu bar]
    actions: [open_file, save_file]
    
  - name: libreoffice-writer
    id: org.libreoffice.Writer
    roles: [push button, text input, menu bar, table]
    actions: [type_text, format_text]
```

---

## Running Tests

### Local Development
```bash
# Unit tests only
pnpm test:unit
pytest tests/unit/ -v

# Integration tests (requires X11)
DISPLAY=:99 pytest tests/integration/ -v

# All tests
pnpm test
```

### CI Pipeline
```yaml
# .github/workflows/test.yml
name: Test
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Install Xvfb
        run: |
          sudo apt-get update
          sudo apt-get install -y xvfb x11-utils gnome-calculator gedit
      
      - name: Install Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      
      - name: Install Node
        uses: actions/setup-node@v4
        with:
          node-version: "24"
      
      - name: Install dependencies
        run: |
          pip install -e .[test]
          pnpm install
      
      - name: Run unit tests
        run: pytest tests/unit/ -v
      
      - name: Run integration tests
        run: |
          export DISPLAY=:99
          Xvfb :99 -screen 0 1920x1080x24 &
          sleep 2
          pytest tests/integration/ -v --timeout=60
```

---

## Test Coverage Requirements

| Module | Target Coverage | Current |
|--------|-----------------|---------|
| `src/python/drivers/x11.py` | 90% | - |
| `src/python/drivers/atspi.py` | 85% | - |
| `src/python/mcp/tools.py` | 95% | - |
| `src/python/session.py` | 90% | - |
| `src/python/validation.py` | 95% | - |
| `TOTAL` | **90%** | - |

### Coverage Command
```bash
# Python coverage
coverage run -m pytest tests/
coverage report --include="src/python/*" --fail-under=90

# TypeScript coverage
pnpm test:coverage
```

---

## Performance Benchmarks

### Target Benchmarks
| Operation | Target Time | Measurement |
|-----------|-------------|-------------|
| `list_windows()` | <50ms | Cold start |
| `get_window_state()` | <200ms | Fresh capture |
| `click()` | <300ms | Action + verification |
| `screenshot_window()` | <100ms | PNG capture |
| MCP tool call | <500ms | End-to-end |

### Benchmark Script
```python
# tests/benchmarks/test_performance.py
def benchmark_list_windows():
    """Benchmark list_windows performance"""
    
    start = time.time()
    windows = list_windows()
    elapsed = time.time() - start
    
    assert elapsed < 0.05  # 50ms
    return elapsed

def benchmark_get_window_state():
    """Benchmark get_window_state performance"""
    
    windows = list_windows()
    if not windows:
        pytest.skip("No windows available")
    
    start = time.time()
    state = get_window_state(windows[0].window_id)
    elapsed = time.time() - start
    
    assert elapsed < 0.2  # 200ms
    return elapsed
```

---

## Test Maintenance

### Test Review Schedule
- Unit tests: Review every release
- Integration tests: Review quarterly
- Test data: Review when apps change significantly

### Flaky Test Handling
```python
# Mark flaky tests
@pytest.mark.flaky(max_retries=3, delay=1)
def test_click_with_retry():
    """Test with automatic retry on failure"""
    # ... test code ...
```

### Test Deprecation
Tests that fail consistently due to external factors (app updates, OS changes) should be:
1. Marked with `@pytest.mark.xfail` with reason
2. Documented in `TESTING.md`
3. Reviewed by maintainer within 30 days

---

*This test strategy is versioned 0.1.0 (Initial).*
*Last updated: 2026-11-14*