# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
Board variant definitions and registry
"""

# Board variant registry - DEFINE THIS FIRST
_board_variants = {}

def register_board_variant(variant_id, type_str, handler_class):
    """Register a board variant handler"""
    _board_variants[(variant_id, type_str)] = handler_class

def get_board_handler(variant_id, type_str):
    """Get handler for a board variant"""
    return _board_variants.get((variant_id, type_str))

def list_board_variants():
    """List all registered board variants"""
    return list(_board_variants.keys())

# NOW import handlers (they will call register_board_variant)
from .sw14 import SW14Handler
from .qd04 import QD04Handler
from .an08 import AN08Handler
from .thrustmaster import ThrustmasterHandler
from .gpro import GProHandler, GProKeyboard

#print(f"boards/__init__.py loaded. Registry: {_board_variants}")

__all__ = [
    'register_board_variant',
    'get_board_handler',
    'list_board_variants',
    'SW14Handler',
    'QD04Handler',
    'AN08Handler',
    'ThrustmasterHandler',
    'GProHandler',
    'GProKeyboard'  # Alias
]
