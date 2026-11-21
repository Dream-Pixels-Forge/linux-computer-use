"""linux_computer_use - Unified Linux desktop control layer."""

__version__ = "0.1.0"
__author__ = "Dream Pixels Forge"

from linux_computer_use.session import Session
from linux_computer_use.drivers.x11 import X11Driver
from linux_computer_use.drivers.atspi import ATSPIDriver
from linux_computer_use.agents.opencode import OpencodeIntegration
from linux_computer_use.agents.kimi import KimiIntegration
from linux_computer_use.agents.openclaude import OpenClaudeIntegration
from linux_computer_use.agents.antigravity import AntiGravityIntegration
from linux_computer_use.agents.hermes import HermesIntegration

__all__ = [
    "Session",
    "X11Driver", 
    "ATSPIDriver",
    "OpencodeIntegration",
    "KimiIntegration",
    "OpenClaudeIntegration",
    "AntiGravityIntegration",
    "HermesIntegration",
]