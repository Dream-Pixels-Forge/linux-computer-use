# SECURITY.md — linux_computer_use Security Requirements

## Threat Model

### Assets
- Desktop application windows and their contents
- User input (passwords, API keys, sensitive data)
- Screen capture data (potentially confidential)
- MCP session tokens
- File system (via temporary screenshot storage)

### Threat Actors
1. **Malicious MCP Client** - Attempting unauthorized desktop control
2. **Compromised Agent** - Gaining excessive permissions
3. **Network Attacker** - Intercepting session tokens or data
4. **Local Privilege Escalation** - Exploiting driver vulnerabilities

### Attack Surfaces
- MCP stdio/protocol
- X11/Wayland protocol access
- AT-SPI accessibility bridge
- Temporary file storage (screenshots)
- Process memory (for element tokens)

---

## Zero-Trust Security Principles

### 1. Explicit Permission Model

**Rule**: No action without explicit permission

All MCP tool calls require:
- Valid session token
- Verified element target
- Safety screening (no password/payment dialogs)
- User confirmation for sensitive operations

```python
def check_permissions(action: Action, state: WindowState) -> bool:
    """Check if action is permitted"""
    
    # Block password/payment dialogs
    if state.is_sensitive_dialog():
        log_block("Sensitive dialog blocked", state.window_title)
        return False
    
    # Requires user confirmation for system dialogs
    if state.is_system_dialog():
        if not pending_user_confirmation():
            return False
    
    # Check against allowlist (if configured)
    if config.allowed_apps and state.app_id not in config.allowed_apps:
        return False
    
    return True
```

### 2. Input Validation

**Rule**: All inputs validated at trust boundary

```python
# MCP tool input validation
def validate_click_input(data: ClickInput) -> ValidationResult:
    if "element" in data:
        if not isinstance(data["element"], int) or data["element"] < 0:
            return ValidationResult.invalid("element must be positive integer")
    
    if "coordinate" in data:
        coord = data["coordinate"]
        if not (isinstance(coord["x"], (int, float)) and 
                isinstance(coord["y"], (int, float))):
            return ValidationResult.invalid("coordinate must be numbers")
        if coord["x"] < 0 or coord["y"] < 0:
            return ValidationResult.invalid("coordinate cannot be negative")
    
    return ValidationResult.valid()
```

### 3. Session Isolation

**Rule**: Each MCP session is isolated

- Element tokens valid only for current session
- Screenshot temp files isolated per session
- Desktop state changes only visible to session

```python
class SessionManager:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.temp_dir = f"/tmp/linux-computer-use-{session_id}"
        self.token_secret = generate_session_secret()
        
    def cleanup(self):
        """Securely clean up session resources"""
        # Delete temp files securely
        for filepath in glob(f"{self.temp_dir}/*"):
            securely_delete(filepath)
        os.rmdir(self.temp_dir)
```

---

## Sensitive Data Handling

### Password & Credential Protection

**Block automatically detected sensitive inputs:**

```python
SENSITIVE_PATTERNS = [
    r"password", r"passwd", r"pwd",
    r"secret", r"token", r"key",
    r"credential", r"auth"
]

def is_password_dialog(tree: ATSPINode) -> bool:
    """Check if dialog is password-related"""
    title = tree.name.lower()
    for pattern in SENSITIVE_PATTERNS:
        if re.search(pattern, title):
            return True
    
    # Check for password input roles
    for node in tree.traverse():
        if node.role == "password text":
            return True
    
    return False
```

### Screenshot Data

All screenshots:
- Stored in temp directory `/tmp/linux-computer-use-{session}/`
- File permissions: `0600` (owner read/write only)
- Deleted on session end
- Base64 encoded for transport (never write sensitive screenshots to disk)

```python
def secure_screenshot() -> ScreenshotResult:
    filepath = f"{temp_dir}/screenshot_{uuid.uuid4()}.png"
    # ... capture screenshot ...
    
    # Secure file permissions
    os.chmod(filepath, 0o600)
    
    # Base64 encode for transport
    with open(filepath, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    
    return ScreenshotResult(
        path=filepath,
        base64=b64,
        secure=True  # Flag for client handling
    )
```

---

## Authentication & Authorization

### Session Management

While MCP provides transport security via stdio, we implement additional session controls:

```python
class Session:
    def __init__(self):
        self.id = str(uuid.uuid4())
        self.created_at = time.time()
        self.last_activity = time.time()
        self.actions_logged = []  # Audit trail
        self.element_tokens = {}  # Token validation
        
    def audit_action(self, tool: str, args: dict, result: dict):
        """Log action for security audit"""
        self.actions_logged.append({
            "timestamp": time.time(),
            "tool": tool,
            "args": sanitize_args(args),
            "result": result.get("effect"),
            "session_age": time.time() - self.created_at
        })
```

### Tool Authorization

Each tool validates:
1. Session validity
2. Input sanitization
3. Target safety (no sensitive dialogs)
4. Action appropriateness

```python
@tool("click")
def click_handler(input: ClickInput) -> ClickResult:
    # 1. Validate input
    validation = validate_click_input(input)
    if not validation.valid:
        raise ToolError(validation.error)
    
    # 2. Check session
    if not session_active():
        raise ToolError("Session expired")
    
    # 3. Verify target safety
    state = get_window_state(input.window_id)
    if is_sensitive_dialog(state.tree):
        raise ToolError("Cannot interact with sensitive dialog")
    
    # 4. Execute with verification
    result = execute_click_safely(input, state)
    
    # 5. Audit action
    session.audit_action("click", input.dict(), result.dict())
    
    return result
```

---

## Network Security

### MCP Transport

The default stdio transport is secure by design:
- No network exposure by default
- Process-isolated communication
- No credential leakage over network

For WebSocket transport (future):
- Must use `wss://` (TLS)
- Certificate pinning required
- Mutual TLS authentication (optional)

### Data in Transit

All data between agent and MCP server:
- Never contains raw passwords
- Contains only element tokens and actions
- Screenshots base64-encoded and transient

---

## File System Security

### Temporary Files

```python
def secure_temp_dir(session_id: str) -> str:
    """Create secure temp directory"""
    temp_dir = f"/tmp/linux-computer-use-{session_id}"
    
    # Create with restrictive permissions
    os.makedirs(temp_dir, mode=0o700, exist_ok=True)
    
    # Verify permissions
    assert os.stat(temp_dir).st_mode & 0o777 == 0o700
    
    return temp_dir
```

### Screenshot Cleanup

```python
import atexit

def cleanup_screenshots(session_dir: str):
    """Securely delete all screenshots"""
    for filepath in glob(f"{session_dir}/*"):
        # Overwrite with random data before delete
        size = os.path.getsize(filepath)
        with open(filepath, "wb") as f:
            f.write(os.urandom(size))
        os.unlink(filepath)
    
    os.rmdir(session_dir)

# Register cleanup on exit
atexit.register(cleanup_screenshots, session.temp_dir)
```

---

## Dependency Security

### Python Dependencies

Use `pip-audit` to check for vulnerabilities:

```bash
pip-audit --requirement pyproject.toml
```

Dependencies must be:
- Pinned with versions
- From trusted sources (PyPI, official repos)
- Periodically audited

### Node.js Dependencies

```bash
pnpm audit --json
# Review and fix vulnerabilities
pnpm audit fix
```

All npm packages:
- Must use `--save-prod` or `--save-dev` correctly
- Pin versions in `package.json`
- Use `npm audit` in CI pipeline

---

## CI/CD Security

### GitHub Actions Security

Workflow file requirements:
```yaml
# .github/workflows/security.yml
name: Security Audit
on: [push, pull_request]

jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      # Dependency audit
      - name: Python security audit
        run: |
          pip install pip-audit
          pip-audit --requirement pyproject.toml
      
      - name: Node.js security audit
        run: pnpm audit
      
      # Secret scanning
      - name: Detect secrets
        uses: gitleaks/gitleaks-action@v2
      
      # Security headers check
      - name: Check MCP server security
        run: python scripts/security_check.py
```

### Release Security

Before release:
- [ ] All dependencies audited with `pip-audit` and `pnpm audit`
- [ ] No hardcoded secrets in codebase
- [ ] Security.md reviewed and updated
- [ ] CVE scan passed

---

## Incident Response

### Security Incident Procedure

1. **Detection**
   - Monitor MCP logs for suspicious activity
   - Alert on excessive actions or privilege escalation

2. **Containment**
   - Immediately revoke session tokens
   - Kill associated MCP processes
   - Isolate affected systems

3. **Eradication**
   - Clean up any persistence mechanisms
   - Reset compromised credentials
   - Apply security patches

4. **Recovery**
   - Verify system integrity
   - Restore from clean backups if needed
   - Update security controls

5. **Lessons Learned**
   - Document incident
   - Update security procedures
   - File security review issue

### Contact

For security issues:
- Email: security@linux-computer-use.dpf
- PGP Key: Available via keybase.io/dpf-security
- Response SLA: 24 hours for critical vulnerabilities

---

## Compliance Considerations

### GDPR (if applicable)

- Screenshots may contain personal data
- Implement data minimization
- Provide right to erasure (session cleanup)
- Document processing purposes

### Accessibility Regulations

- AT-SPI integration supports accessibility
- Document privacy implications of accessibility data
- Provide opt-out mechanisms for accessibility features

---

## Security Checklist

Before merging or releasing:

- [ ] No hardcoded credentials or API keys
- [ ] All user inputs validated at trust boundary
- [ ] Sensitive dialogs blocked automatically
- [ ] Temporary files securely deleted
- [ ] Session tokens cryptographically signed
- [ ] Dependencies audited for vulnerabilities
- [ ] Security tests pass
- [ ] No secrets in git history
- [ ] File permissions restrictive (0600 for files, 0700 for dirs)

---

## Security Headers & Configuration

### MCP Server Security Options

```python
SECURITY_CONFIG = {
    "max_session_duration": 3600,  # 1 hour
    "max_actions_per_session": 100,
    "require_confirmation_threshold": 5,  # After 5 actions
    "blocked_dialog_patterns": [
        "password", "login", "authenticat",
        "payment", "card", "billing"
    ],
    "screenshot_ttl": 60,  # Delete after 60 seconds
    "audit_retention": 90  # Keep audit logs for 90 days
}
```

---

*This security specification is versioned 0.1.0 (Initial).*
*Last reviewed: 2026-11-14*
*Next review: 2027-05-14 (6 months)*