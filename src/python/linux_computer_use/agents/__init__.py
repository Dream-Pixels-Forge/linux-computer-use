"""AI Agent integrations for linux_computer_use."""

from linux_computer_use.agents.opencode import OpencodeIntegration
from linux_computer_use.agents.kimi import KimiIntegration
from linux_computer_use.agents.openclaude import OpenClaudeIntegration
from linux_computer_use.agents.antigravity import AntiGravityIntegration
from linux_computer_use.agents.hermes import HermesIntegration

__all__ = [
    "OpencodeIntegration",
    "KimiIntegration", 
    "OpenClaudeIntegration",
    "AntiGravityIntegration",
    "HermesIntegration",
]