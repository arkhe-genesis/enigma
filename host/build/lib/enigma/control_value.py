# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
ControlValue - shared operator base for generated control classes.

The control code generator emits one class per control (e.g.
`EngineControl.IgnitionEnable`). Every one exposes its live value as `self.value`
and supports comparison, arithmetic, and conversion by delegating to that value.
Those operators are identical across all controls, so they live here once instead
of being copied into every generated class.

Generated control classes inherit this and supply `value`, `NAME`, and
`_device_class`. `__str__` / `__repr__` stay in the generated class because they
vary by board type.
"""


class ControlValue:
    """Operator mixin for generated control classes.

    Subclasses provide a `value` property (the current control value, or `None`
    when the device is disconnected), a `NAME` class attribute, and a
    `_device_class` reference. Arithmetic treats a `None` value as 0.
    """

    # -- comparison ------------------------------------------------------
    def __eq__(self, other):
        return self.value == other

    def __ne__(self, other):
        return self.value != other

    def __lt__(self, other):
        return self.value < other

    def __le__(self, other):
        return self.value <= other

    def __gt__(self, other):
        return self.value > other

    def __ge__(self, other):
        return self.value >= other

    # -- arithmetic (treat None as 0) ------------------------------------
    def __add__(self, other):
        return (self.value or 0) + other

    def __radd__(self, other):
        return other + (self.value or 0)

    def __sub__(self, other):
        return (self.value or 0) - other

    def __rsub__(self, other):
        return other - (self.value or 0)

    def __mul__(self, other):
        return (self.value or 0) * other

    def __rmul__(self, other):
        return other * (self.value or 0)

    def __truediv__(self, other):
        return (self.value or 0) / other

    def __rtruediv__(self, other):
        return other / (self.value or 1)  # Avoid divide by zero

    def __floordiv__(self, other):
        return (self.value or 0) // other

    def __rfloordiv__(self, other):
        return other // (self.value or 1)  # Avoid divide by zero

    def __mod__(self, other):
        return (self.value or 0) % other

    def __rmod__(self, other):
        return other % (self.value or 1)  # Avoid divide by zero

    def __pow__(self, other):
        return (self.value or 0) ** other

    def __rpow__(self, other):
        return other ** (self.value or 0)

    # -- unary -----------------------------------------------------------
    def __neg__(self):
        return -(self.value or 0)

    def __pos__(self):
        return +(self.value or 0)

    def __abs__(self):
        return abs(self.value or 0)

    # -- conversion ------------------------------------------------------
    def __int__(self):
        return int(self.value or 0)

    def __float__(self):
        return float(self.value or 0)

    def __bool__(self):
        return self.value is not None and self.value != 0

    def __format__(self, format_spec):
        return format(self.value or 0, format_spec)

    # -- hashable (for use as dict keys) ---------------------------------
    def __hash__(self):
        return hash((self._device_class.NAME, self.NAME))
