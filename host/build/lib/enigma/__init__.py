# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""Enigma HID Device Library

Provides interface to Enigma custom HID devices (SW14, QD04) and
Thrustmaster joysticks.
"""

__version__ = '0.1.0'

# Module-level manager singleton
_manager_instance = None

# CLI config (populated by configure_from_args, consumed by EnigmaManager)
_cli_config = {}

def get_manager():
    """Get the global manager instance"""
    if _manager_instance is None:
        raise RuntimeError("Manager not initialized. Create EnigmaManager first.")
    return _manager_instance

# Public API exports
from .manager import EnigmaManager
from .config import ConfigManager
from .boards import get_board_handler, list_board_variants
from .hid_protocol import LogLevel, BlankingMode

# Control state classes (for type hints)
from .boards.sw14 import SW14ControlState
from .boards.qd04 import QD04ControlState
from .boards.thrustmaster import ThrustmasterControlState

__all__ = [
    'EnigmaManager',
    'get_manager',
    'ConfigManager',
    'SW14ControlState',
    'QD04ControlState',
    'ThrustmasterControlState',
    'get_board_handler',
    'list_board_variants',
    'LogLevel',
    'BlankingMode',
    'add_arguments',
    'configure_from_args',
]


def add_arguments(parser):
    """Add enigma-specific arguments to an argparse parser.

    Call this before parse_args() to include enigma's CLI options.
    After parsing, call configure_from_args(args) to apply them.
    """
    group = parser.add_argument_group('Enigma options')
    group.add_argument('--wire', action='store_true',
                       help='Show raw HID TX/RX packets for debugging')
    group.add_argument('--rx', action='store_true',
                       help='Show control state changes from hardware')
    group.add_argument('--tx', action='store_true',
                       help='Show control state changes to hardware')
    group.add_argument('--warn-spec-read', action='store_true',
                       help='Warn if a device writes a spec value then reads it in the same update()')


def configure_from_args(args):
    """Apply parsed arguments to enigma library configuration.

    Call this after parse_args(). EnigmaManager will automatically
    pick up these settings when instantiated.
    """
    global _cli_config
    _cli_config = {
        'debug_wire': getattr(args, 'wire', False),
        'debug_rx': getattr(args, 'rx', False),
        'debug_tx': getattr(args, 'tx', False),
    }

    if getattr(args, 'warn_spec_read', False):
        from .device import set_warn_spec_read
        set_warn_spec_read(True)


def get_cli_config():
    """Get CLI config dict (used internally by EnigmaManager)"""
    return _cli_config
