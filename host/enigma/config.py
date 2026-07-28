# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
enigma_config.py - Configuration file management
"""

import json
from pathlib import Path
from typing import Dict, Optional

from .colors import print_error_blink

class ConfigManager:
    """Manages board mappings (board_id -> config_name)"""
    
    def __init__(self, config_dir: Path):
        self.config_dir = Path(config_dir)
        self.board_mappings: Dict[str, str] = {}  # board_id -> config_name
        
        self._load_mappings()
    
    def _load_mappings(self):
        """Load board mappings from mappings.json"""
        mappings_file = self.config_dir / 'control_mappings.json'
        if mappings_file.exists():
            with open(mappings_file, 'r') as f:
                self.board_mappings = json.load(f)
            print(f"[enigma] Loaded {len(self.board_mappings)} board mappings")
    
    def get_config_file(self, board_id: str) -> Optional[Path]:
        """Get configuration file path for a board by its ID
        
        Args:
            board_id: Board identifier (e.g., 'SW14-00')
        
        Returns:
            Path to config file, or None if not found
        """
        # Look up mapping
        config_name = self.board_mappings.get(board_id)
        if not config_name:
            print_error_blink(f"!!! {board_id}: NO CONFIG MAPPING FOUND !!!")
            return None

        # Return config file path
        config_file = self.config_dir / f'{config_name}.json'
        if not config_file.exists():
            print_error_blink(f"!!! {board_id}: CONFIG FILE NOT FOUND ({config_file}) !!!")
            return None

        return config_file
