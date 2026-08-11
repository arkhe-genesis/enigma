# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
enigma.panelmanager - Base class for panel business logic

Provides a base class for managing indicator schemes for logical panels.
Each panel typically corresponds to one or two Enigma boards.

Subclasses automatically register on instantiation and are called by
EnigmaManager.update() after HID events are processed.
"""

import traceback

from enigma.colors import print_error


class PanelManager:
    """Base class for panel business logic

    Subclass this to manage indicator schemes for a logical panel
    (typically one or two Enigma boards).

    Example:
        class PowerCorePanel(PanelManager):
            def update(self):
                if PowerCore.Auto == PowerCore.Auto.Values.AUTO:
                    PowerCore.scheme = PowerCore.Schemes.DISABLED
                else:
                    PowerCore.scheme = PowerCore.Schemes.DEFAULT

    Instantiation auto-registers with the manager:
        PowerCorePanel()  # Now called every manager.update()
    """

    _registry: list['PanelManager'] = []

    def __init__(self):
        """Register this panel for automatic updates"""
        PanelManager._registry.append(self)

    def update(self):
        """Override this to implement panel logic

        Called once per manager.update() cycle, after HID events are processed
        and changed flags are cleared. Check control.changed() and set schemes here.
        """
        pass

    @classmethod
    def update_all(cls):
        """Called by EnigmaManager.update() after processing events"""
        # Import tracking functions (only used if --warnspecread enabled)
        try:
            from .device import set_current_updating_device, clear_current_updating_device
        except ImportError:
            set_current_updating_device = lambda x: None
            clear_current_updating_device = lambda: None

        for panel in cls._registry:
            try:
                set_current_updating_device(panel.__class__.__name__)
                panel.update()
                clear_current_updating_device()
            except Exception as e:
                clear_current_updating_device()
                print_error(f"[enigma] ERROR in {panel.__class__.__name__}.update():")
                traceback.print_exc()

    def reset(self):
        """Override this to handle system-wide reset (called by EnigmaManager.reset_all)"""
        pass

    @classmethod
    def reset_all(cls):
        """Called by EnigmaManager.reset_all() to reset all panels"""
        for panel in cls._registry:
            try:
                panel.reset()
            except Exception as e:
                print_error(f"[enigma] ERROR in {panel.__class__.__name__}.reset():")
                traceback.print_exc()

    @classmethod
    def clear_registry(cls):
        """Clear all registered panels (useful for testing)"""
        cls._registry.clear()