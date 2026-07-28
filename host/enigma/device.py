# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
Device specification base classes and published value descriptors

These provide the runtime behavior for generated device specs,
including double-buffering for consistent reads across update cycles.
"""

from typing import Any, Optional, Type

from enigma.colors import print_warning


# --- Same-cycle write/read detection ---
# Helps catch bugs where a device sets a value then reads it in the same update(),
# which returns the OLD value due to double-buffering.
_warn_spec_read = False
_warn_spec_read_interval = 5.0  # seconds between warnings per unique violation
_warn_spec_read_last_times = {}  # (device_name, owner, attr) -> last_warn_time
_current_updating_device = None
_written_this_cycle = {}  # storage_key -> device_name


def set_warn_spec_read(enabled: bool):
    """Enable/disable warnings for same-cycle spec read after write."""
    global _warn_spec_read
    _warn_spec_read = enabled


def set_current_updating_device(name: str):
    """Set the currently updating device (call before device.update())."""
    global _current_updating_device
    _current_updating_device = name


def clear_current_updating_device():
    """Clear the current device context (call after device.update())."""
    global _current_updating_device
    _current_updating_device = None


def clear_write_tracking():
    """Clear write tracking at end of update cycle."""
    _written_this_cycle.clear()


def _should_warn_now(violation_key: tuple) -> bool:
    """Check if enough time has passed to show another warning for this violation."""
    import time
    now = time.time()
    last_time = _warn_spec_read_last_times.get(violation_key, 0.0)
    if now - last_time >= _warn_spec_read_interval:
        _warn_spec_read_last_times[violation_key] = now
        return True
    return False


class PublishedValue:
    """Base descriptor for published values with double-buffering

    Provides consistent reads across update cycles by maintaining separate
    current (readable) and pending (writable) buffers. After all Device.update()
    calls complete, commit_all() promotes pending values to current.

    Values are stored per-instance to support aliases (multiple DeviceSpec instances
    sharing the same class but with separate state).
    """

    # Class-level registry of all (descriptor, instance) pairs for commit_all()
    _all_bindings: list[tuple['PublishedValue', Any]] = []
    # Counter for unique storage keys
    _counter = 0

    def __init__(self, default: Any):
        self._default = default
        self._name = None  # Set by __set_name__
        # Unique key for per-instance storage
        self._storage_key = f'_pv_{PublishedValue._counter}'
        PublishedValue._counter += 1

    def __set_name__(self, owner: Type, name: str):
        self._name = name
        self._owner = owner

    def _get_storage(self, obj) -> dict:
        """Get or create per-instance storage for this descriptor"""
        if not hasattr(obj, self._storage_key):
            storage = {'current': self._default, 'pending': self._default}
            setattr(obj, self._storage_key, storage)
            # Register this binding for commit_all/reset_all
            PublishedValue._all_bindings.append((self, obj))
        return getattr(obj, self._storage_key)

    def __get__(self, obj, objtype=None):
        # Class-level access returns self (for accessing constants)
        if obj is None:
            return self

        # Check for same-cycle read-after-write (potential bug)
        if _warn_spec_read and _current_updating_device:
            key = (self._storage_key, id(obj))
            if key in _written_this_cycle and _written_this_cycle[key] == _current_updating_device:
                # Prefer NAME attribute (user-facing name) over class name
                owner_name = getattr(obj, 'NAME', None) or getattr(self, '_owner', type(obj)).__name__
                violation_key = (_current_updating_device, owner_name, self._name)
                if _should_warn_now(violation_key):
                    print_warning(f"WARNING: {_current_updating_device} wrote {owner_name}.{self._name} then read it.")
                    print(f"[enigma]          Reads return PREVIOUS cycle's value, not what you just wrote.")

        # Instance-level access returns current value from per-instance storage
        return self._get_storage(obj)['current']

    def __set__(self, obj, value):
        # If value is a control object, extract its .value
        if hasattr(value, 'value') and hasattr(value, '_device_class'):
            value = value.value

        # Track write for same-cycle detection
        if _warn_spec_read and _current_updating_device:
            key = (self._storage_key, id(obj))
            _written_this_cycle[key] = _current_updating_device

        # Write to pending buffer in per-instance storage
        self._get_storage(obj)['pending'] = value

    def commit(self, obj):
        """Promote pending to current for a specific instance"""
        storage = self._get_storage(obj)
        storage['current'] = storage['pending']

    def reset(self, obj):
        """Reset to default value for a specific instance"""
        storage = self._get_storage(obj)
        storage['current'] = self._default
        storage['pending'] = self._default

    @classmethod
    def commit_all(cls):
        """Commit all published values (call after all device updates)"""
        for descriptor, obj in cls._all_bindings:
            descriptor.commit(obj)

    @classmethod
    def reset_all(cls):
        """Reset all published values to defaults"""
        for descriptor, obj in cls._all_bindings:
            descriptor.reset(obj)


class PublishedNumber(PublishedValue):
    """Published numeric value with optional threshold constants

    Usage:
        class PowerCore(DeviceSpec):
            class _Temperature:
                NOMINAL = 350.0
                WARNING = 500.0
                CRITICAL = 650.0

            Temperature = PublishedNumber(default=0.0, thresholds=_Temperature)

        # Then in code:
        if PowerCore.Temperature > PowerCore.Temperature.CRITICAL:
            ...
    """

    def __init__(self, default: float = 0.0, thresholds: Optional[Type] = None):
        super().__init__(default)
        self._thresholds = thresholds
        # Store last accessed obj for operators (set in __get__)
        self._last_obj = None

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        # Remember obj for comparison operators
        self._last_obj = obj

        # Check for same-cycle read-after-write (potential bug)
        if _warn_spec_read and _current_updating_device:
            key = (self._storage_key, id(obj))
            if key in _written_this_cycle and _written_this_cycle[key] == _current_updating_device:
                owner_name = getattr(obj, 'NAME', None) or getattr(self, '_owner', type(obj)).__name__
                violation_key = (_current_updating_device, owner_name, self._name)
                if _should_warn_now(violation_key):
                    print_warning(f"WARNING: {_current_updating_device} wrote {owner_name}.{self._name} then read it.")
                    print(f"[enigma]          Reads return PREVIOUS cycle's value, not what you just wrote.")

        return self._get_storage(obj)['current']

    def __getattr__(self, name: str):
        # Proxy attribute access to thresholds class
        if name.startswith('_'):
            raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")
        if self._thresholds and hasattr(self._thresholds, name):
            return getattr(self._thresholds, name)
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")
    
    def _current_value(self):
        """Get current value from last accessed instance"""
        if self._last_obj is not None:
            return self._get_storage(self._last_obj)['current']
        return self._default

    # Comparison operators - compare current value
    def __lt__(self, other):
        return self._current_value() < other

    def __le__(self, other):
        return self._current_value() <= other

    def __gt__(self, other):
        return self._current_value() > other

    def __ge__(self, other):
        return self._current_value() >= other

    def __eq__(self, other):
        if isinstance(other, PublishedNumber):
            return self._current_value() == other._current_value()
        return self._current_value() == other

    def __ne__(self, other):
        return not self.__eq__(other)

    # Arithmetic operators - return value, not descriptor
    def __add__(self, other):
        return self._current_value() + other

    def __radd__(self, other):
        return other + self._current_value()

    def __sub__(self, other):
        return self._current_value() - other

    def __rsub__(self, other):
        return other - self._current_value()

    def __mul__(self, other):
        return self._current_value() * other

    def __rmul__(self, other):
        return other * self._current_value()

    def __truediv__(self, other):
        return self._current_value() / other

    def __rtruediv__(self, other):
        return other / self._current_value()

    def __floordiv__(self, other):
        return self._current_value() // other

    def __rfloordiv__(self, other):
        return other // self._current_value()

    def __mod__(self, other):
        return self._current_value() % other

    def __rmod__(self, other):
        return other % self._current_value()

    def __neg__(self):
        return -self._current_value()

    def __pos__(self):
        return +self._current_value()

    def __abs__(self):
        return abs(self._current_value())

    # Type conversions
    def __int__(self):
        return int(self._current_value())

    def __float__(self):
        return float(self._current_value())

    def __repr__(self):
        return f"PublishedNumber({self._current_value()})"

    def __str__(self):
        return str(self._current_value())


class PublishedBool(PublishedValue):
    """Published boolean value

    Usage:
        class PowerCore(DeviceSpec):
            ScramActive = PublishedBool(default=False)

        # Then in code:
        if PowerCore.ScramActive:
            ...
    """

    def __init__(self, default: bool = False, constants: Optional[Type] = None):
        super().__init__(default)
        self._constants = constants
        self._last_obj = None

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        self._last_obj = obj

        # Check for same-cycle read-after-write (potential bug)
        if _warn_spec_read and _current_updating_device:
            key = (self._storage_key, id(obj))
            if key in _written_this_cycle and _written_this_cycle[key] == _current_updating_device:
                owner_name = getattr(obj, 'NAME', None) or getattr(self, '_owner', type(obj)).__name__
                violation_key = (_current_updating_device, owner_name, self._name)
                if _should_warn_now(violation_key):
                    print_warning(f"WARNING: {_current_updating_device} wrote {owner_name}.{self._name} then read it.")
                    print(f"[enigma]          Reads return PREVIOUS cycle's value, not what you just wrote.")

        return self._get_storage(obj)['current']

    def __getattr__(self, name: str):
        if name.startswith('_'):
            raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")
        if self._constants and hasattr(self._constants, name):
            return getattr(self._constants, name)
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

    def _current_value(self):
        if self._last_obj is not None:
            return self._get_storage(self._last_obj)['current']
        return self._default

    def __bool__(self):
        return bool(self._current_value())

    def __eq__(self, other):
        if isinstance(other, PublishedBool):
            return self._current_value() == other._current_value()
        return self._current_value() == other

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return f"PublishedBool({self._current_value()})"

    def __str__(self):
        return str(self._current_value())


class EnumValueProxy:
    """Proxy that acts like a string but also provides .Values access"""
    def __init__(self, value, enum_class):
        self._value = value
        self._enum_class = enum_class
    
    @property
    def Values(self):
        """Access enum constants"""
        return self._enum_class.Values
    
    def __str__(self):
        return str(self._value)
    
    def __repr__(self):
        return repr(self._value)
    
    def __eq__(self, other):
        if isinstance(other, EnumValueProxy):
            return self._value == other._value
        return self._value == other
    
    def __ne__(self, other):
        return not self.__eq__(other)

class PublishedString(PublishedValue):
    """Published string value for free-form text

    Usage:
        class PowerCore(DeviceSpec):
            StatusMessage = PublishedString(default="")

        # Then in code:
        PowerCore.StatusMessage = "Reactor temperature critical!"
        PowerCore.StatusMessage = json.dumps({"state": "transitioning", "progress": 0.75})
    """

    def __init__(self, default: str = ""):
        super().__init__(default)
        self._last_obj = None

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        self._last_obj = obj

        # Check for same-cycle read-after-write (potential bug)
        if _warn_spec_read and _current_updating_device:
            key = (self._storage_key, id(obj))
            if key in _written_this_cycle and _written_this_cycle[key] == _current_updating_device:
                owner_name = getattr(obj, 'NAME', None) or getattr(self, '_owner', type(obj)).__name__
                violation_key = (_current_updating_device, owner_name, self._name)
                if _should_warn_now(violation_key):
                    print_warning(f"WARNING: {_current_updating_device} wrote {owner_name}.{self._name} then read it.")
                    print(f"[enigma]          Reads return PREVIOUS cycle's value, not what you just wrote.")

        return self._get_storage(obj)['current']

    def _current_value(self):
        if self._last_obj is not None:
            return self._get_storage(self._last_obj)['current']
        return self._default

    def __str__(self):
        return str(self._current_value())

    def __repr__(self):
        return f"PublishedString({self._current_value()!r})"

    def __eq__(self, other):
        if isinstance(other, PublishedString):
            return self._current_value() == other._current_value()
        return self._current_value() == other

    def __ne__(self, other):
        return not self.__eq__(other)

class PublishedEnum(PublishedValue):
    """Published enum value with named constants

    Usage:
        class PowerCore(DeviceSpec):
            class _ReactorState:
                class Values:
                    OFFLINE = "OFFLINE"
                    STARTING = "STARTING"
                    RUNNING = "RUNNING"
                    SCRAM = "SCRAM"
                OFFLINE = "OFFLINE"
                STARTING = "STARTING"
                RUNNING = "RUNNING"
                SCRAM = "SCRAM"

            ReactorState = PublishedEnum(_ReactorState, default=_ReactorState.OFFLINE)

        # Then in code:
        if PowerCore.ReactorState == PowerCore.ReactorState.Values.SCRAM:
            ...

        PowerCore.ReactorState = PowerCore.ReactorState.Values.OFFLINE
    """

    def __init__(self, enum_class: Type, default: str):
        super().__init__(default)
        self._enum_class = enum_class
        self._last_obj = None

    def __get__(self, obj, objtype=None):
        # Class-level access returns descriptor (for accessing constants)
        if obj is None:
            return self
        self._last_obj = obj

        # Check for same-cycle read-after-write (potential bug)
        if _warn_spec_read and _current_updating_device:
            key = (self._storage_key, id(obj))
            if key in _written_this_cycle and _written_this_cycle[key] == _current_updating_device:
                owner_name = getattr(obj, 'NAME', None) or getattr(self, '_owner', type(obj)).__name__
                violation_key = (_current_updating_device, owner_name, self._name)
                if _should_warn_now(violation_key):
                    print_warning(f"WARNING: {_current_updating_device} wrote {owner_name}.{self._name} then read it.")
                    print(f"[enigma]          Reads return PREVIOUS cycle's value, not what you just wrote.")

        # Instance-level access returns proxy with value AND .Values access
        return EnumValueProxy(self._get_storage(obj)['current'], self._enum_class)

    def __getattr__(self, name: str):
        # Proxy attribute access to enum class (for class-level access)
        if name.startswith('_'):
            raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")
        if hasattr(self._enum_class, name):
            return getattr(self._enum_class, name)
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

    def _current_value(self):
        if self._last_obj is not None:
            return self._get_storage(self._last_obj)['current']
        return self._default

    def __eq__(self, other):
        if isinstance(other, PublishedEnum):
            return self._current_value() == other._current_value()
        return self._current_value() == other

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return f"PublishedEnum({self._current_value()})"

    def __str__(self):
        return str(self._current_value())


class DeviceSpec:
    """Base class for generated device specifications
    
    Generated device specs inherit from this class. Each spec defines
    published values (using PublishedNumber, PublishedBool, PublishedEnum)
    that can be read/written by simulation devices.
    
    Example generated spec:
        class _PowerCore(DeviceSpec):
            NAME = "PowerCore"
            
            class _ReactorState:
                OFFLINE = "OFFLINE"
                RUNNING = "RUNNING"
            
            ReactorState = PublishedEnum(_ReactorState, default=_ReactorState.OFFLINE)
            Temperature = PublishedNumber(default=0.0)
        
        PowerCore = _PowerCore()  # Singleton instance
    """
    
    _registry: dict[str, 'DeviceSpec'] = {}
    
    def __init__(self):
        # Register instance by NAME if defined
        if hasattr(self, 'NAME'):
            DeviceSpec._registry[self.NAME] = self
    
    @classmethod
    def get(cls, name: str) -> Optional['DeviceSpec']:
        """Get a device spec instance by name"""
        return cls._registry.get(name)
    
    @classmethod
    def all(cls) -> list['DeviceSpec']:
        """Get all registered device spec instances"""
        return list(cls._registry.values())
    
    @classmethod
    def all_names(cls) -> list[str]:
        """Get all registered device spec names"""
        return list(cls._registry.keys())


class Device:
    """Base class for simulation device implementations
    
    Subclass this and instantiate to create a simulation subsystem.
    Devices auto-register on instantiation and their update() method
    is called each tick by the manager.
    
    Example:
        from enigma import Device
        from generated.devices import PowerCore, CoolingSystem
        from generated.controls import PowerPanel
        
        class PowerCoreDevice(Device):
            def update(self):
                if PowerPanel.MasterEnable == PowerPanel.MasterEnable.Values.ON:
                    temp = calculate_temp(CoolingSystem.CoolantFlow)
                    PowerCore.Temperature = temp
                    
                    if PowerCore.Temperature > PowerCore.Temperature.CRITICAL:
                        PowerCore.ReactorState = PowerCore.ReactorState.SCRAM
        
        # Just instantiate - it auto-registers
        _instance = PowerCoreDevice()
    """
    
    _instances: list['Device'] = []
    
    def __init__(self):
        Device._instances.append(self)
    
    @classmethod
    def all(cls) -> list['Device']:
        """Get all registered Device instances"""
        return cls._instances.copy()
    
    @classmethod
    def clear(cls):
        """Clear all registered instances (for testing/reset)"""
        cls._instances.clear()
    
    def update(self):
        """Called each tick to update simulation state
        
        Override this in your subclass to implement simulation logic.
        Read from controls and other device specs, write to your own spec.
        """
        pass
    
    def on_reset(self):
        """Called when simulation is reset (game restart)
        
        Override this to perform any device-specific reset logic
        beyond the automatic published value reset.
        """
        pass
