# Team Workflow — linux_computer_use

## Team Roles & Responsibilities

### Core Team

| Role | Person | Responsibilities |
|------|--------|------------------|
| **Lead Developer** | You | Architecture, PR reviews, integration |
| **Desktop Specialist** | Team | X11/Wayland/AT-SPI drivers |
| **MCP Integration** | Team | MCP server, tool definitions |
| **Security Lead** | Team | SECURITY.md implementation review |
| **QA Engineer** | Team | Test coverage, integration testing |
| **DevOps** | Team | CI/CD, Docker environments |

---

## Work Distribution Matrix

### Phase 1: Foundation (MVP)

| Task | Owner | ETA | Verification |
|------|-------|-----|--------------|
| Repository setup | Lead | Done | Files created |
| Python package skeleton | Desktop Specialist | Day 1 | `pyproject.toml`, `__init__.py` |
| Session management | Desktop Specialist | Day 1 | Unit tests pass |
| X11 driver stub | Desktop Specialist | Day 2 | Basic window list |
| AT-SPI driver stub | Desktop Specialist | Day 2 | Tree traversal |
| Wayland driver stub | Desktop Specialist | Day 2 | Read-only support |
| MCP server core | MCP Integration | Day 3 | Tools list works |
| CI/CD workflow | DevOps | Day 1 | GitHub Actions green |
| Security review | Security Lead | Day 3 | SECURITY.md aligned |
| Unit tests | QA Engineer | Day 2 | 50% coverage |

---

## Development Workflow

### 1. Issue Creation
```bash
# Create issue from template
gh issue create --template .github/ISSUE_TEMPLATE.md
```

### 2. Branch Naming
```
feat/discover-windows-x11
feat/mcp-click-tool
fix/screenshot-path-bug
test/integration-with-firefox
docs/security-review
```

### 3. PR Process
```bash
# 1. Create branch
git checkout -b feat/discover-windows-x11

# 2. Implement with tests
# ...

# 3. Run quality checks
poetry run pytest tests/
poetry run mypy src/python/
poetry run ruff check src/python/

# 4. Commit and push
git add .
git commit -m "feat: add window discovery for X11

- Implement list_windows() using python-xlib
- Filter desktop and dock windows
- Return Window objects with EWMH properties
- Add unit tests
- Fixes issue #42"

git push origin feat/discover-windows-x11

# 5. Create PR
gh pr create --title "feat: add window discovery for X11" --body "See changes"
```

### 4. Review Checklist
- [ ] Code follows PEP 8 and Google style
- [ ] Type hints added for all functions
- [ ] Unit tests added/modified
- [ ] Integration test if needed
- [ ] Documentation updated
- [ ] Security implications reviewed
- [ ] No hardcoded secrets
- [ ] CI passes (type-check, lint, test, build)

---

## Communication Channels

### Daily Standup
- **Time**: 10:00 AM UTC
- **Channel**: #linux-computer-use (Discord/Slack)
- **Format**: What did you do? What's blocking? What's next?

### Design Review
- **When**: Before PR merge for significant changes
- **Attendees**: Lead, relevant specialists
- **Tool**: GitHub PR review

### Security Review
- **When**: Before any release, any auth/crypto changes
- **Attendees**: Security Lead
- **Checklist**: SECURITY.md compliance

---

## Testing Strategy

### Unit Tests (50%)
```bash
poetry run pytest tests/unit/ -v
```

### Integration Tests (30%)
```bash
# With virtual display
export DISPLAY=:99
Xvfb :99 -screen 0 1920x1080x24 &
poetry run pytest tests/integration/ -v
```

### End-to-End Tests (20%)
```bash
# With actual MCP client
node tests/e2e/mcp-client-test.js
```

### Test Coverage Goals
| Module | Target |
|--------|--------|
| session.py | 95% |
| drivers/base.py | 90% |
| drivers/x11.py | 85% |
| mcp/server.py | 90% |
| **Total** | **90%** |

---

## Deployment Pipeline

### Preview Deployment
- Automatic on PR open
- Deploys to preview environment
- URL posted in PR comment

### Production Deployment
- Automatic on merge to `main`
- CI/CD pipeline runs
- Release created via `gh release create`

### Rollback Procedure
```bash
# If production issue
git revert HEAD
gh release delete v0.1.0 --yes
git push origin main
```

---

## Feature Ownership Matrix

| Feature | Owner | Backup |
|---------|-------|--------|
| X11 Driver | Desktop Specialist | Lead |
| AT-SPI Driver | Desktop Specialist | - |
| Wayland Driver | Desktop Specialist | - |
| MCP Server | MCP Integration | Lead |
| Session | Desktop Specialist | QA |
| Screenshots | Desktop Specialist | QA |
| Tools (list, click, type) | MCP Integration | Desktop Specialist |
| Security | Security Lead | Lead |
| CI/CD | DevOps | Lead |
| Tests | QA Engineer | All |

---

## Escalation Process

1. **Peer Resolution**: 24h within team channel
2. **Lead Decision**: 24h response from lead
3. **Tech Lead Review**: If no consensus
4. **CTO Escalation**: Blockers > 48h

---

## Success Metrics

### Phase 1 Completion
- [ ] All CI checks passing
- [ ] 90% test coverage
- [ ] MCP server starts and lists tools
- [ ] X11 discovery works with Firefox
- [ ] Basic click/type works
- [ ] Screenshots captured
- [ ] Security review complete

### Phase 2 Readiness
- [ ] AT-SPI integration working
- [ ] Wayland read support
- [ ] Form controls implemented
- [ ] Performance benchmarks met
- [ ] Remote debugging works

---

## Next Sprint Items

1. **Sprint 1 (Week 1)**: Core infrastructure
   - Complete driver skeletons
   - Implement MCP tool routing
   - Add comprehensive tests

2. **Sprint 2 (Week 2)**: X11 integration
   - Real X11 window discovery
   - Element tree from AT-SPI
   - Click and type implementation

3. **Sprint 3 (Week 3)**: Testing & Harden
   - Integration tests with real apps
   - Security audit
   - Performance optimization

4. **Sprint 4 (Week 4)**: Release preparation
   - Documentation finalization
   - Release notes
   - Version bump to 0.2.0

---

*This workflow is versioned 0.1.0 and reviewed bi-weekly.*