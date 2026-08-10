# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
Watch Condition - Alert triggers based on threshold crossings

Handles event triggering based on value conditions:
- Monitors watched values (e.g., pressure, shield level)
- Triggers events once when crossing thresholds
- Supports multiple thresholds per event
- Edge detection (rising, falling, both)
"""

from typing import Optional, List
from dataclasses import dataclass

from enigma.colors import print_warning


@dataclass
class Condition:
    """Represents a single threshold condition"""
    edge: str  # "rising", "falling", or "both"
    operator: str  # ">", "<", ">=", "<=", "=="
    threshold: float
    is_active: bool = False  # Current state of this condition


class WatchCondition:
    """
    Monitors a value and triggers an event when conditions are met.

    Supports CSV format for multiple conditions:
    "rising > 10%, rising > 20%, falling < 20%, falling < 10%"

    Edge types:
    - rising: triggers when condition becomes true while value is increasing
    - falling: triggers when condition becomes true while value is decreasing
    - both: triggers on either edge

    Operators:
    - > : greater than (rising: was <=, now >)
    - >= : greater or equal (rising: was <, now >=)
    - == : equals (alias for >= on rising, <= on falling)
    - < : less than (falling: was >=, now <)
    - <= : less or equal (falling: was >, now <=)
    - != : not equal

    Notes:
    - "=" is treated as alias for "=="
    - "%" is purely syntactic sugar (no conversion) - "10%" and "10" are identical
    """

    def __init__(self, event_name: str, watch_spec: str, condition_string: str):
        """
        Initialize watch condition

        Args:
            event_name: Name of the event to trigger
            watch_spec: Published value spec to watch (e.g., "FtlSpec.PortFeedPressure")
            condition_string: CSV string of conditions (e.g., "rising > 95%, falling < 10")
        """
        self.event_name = event_name
        self.watch_spec = watch_spec
        self.conditions: List[Condition] = []
        self._previous_value: Optional[float] = None

        # Parse condition string
        self._parse_conditions(condition_string)

    def _parse_conditions(self, condition_string: str):
        """Parse CSV condition string into Condition objects"""
        parts = [p.strip() for p in condition_string.split(',')]

        for part in parts:
            # Parse: "<edge> <operator> <value>[%]"
            tokens = part.split()
            if len(tokens) < 3:
                print_warning(f"[Audio] WARNING: Invalid condition format: '{part}'")
                continue

            edge = tokens[0].lower()
            operator = tokens[1]
            value_str = tokens[2]

            # Validate edge
            if edge not in ('rising', 'falling', 'both'):
                print_warning(f"[Audio] WARNING: Invalid edge type: '{edge}'")
                continue

            # Normalize operator (= -> ==)
            if operator == '=':
                operator = '=='

            # Handle == as >= for rising, <= for falling
            if operator == '==':
                if edge == 'rising':
                    operator = '>='
                elif edge == 'falling':
                    operator = '<='

            # Validate operator
            if operator not in ('>', '<', '>=', '<=', '==', '!='):
                print_warning(f"[Audio] WARNING: Invalid operator: '{operator}'")
                continue

            # Parse value (% is just syntactic sugar, no conversion)
            try:
                if value_str.endswith('%'):
                    threshold = float(value_str[:-1])
                else:
                    threshold = float(value_str)
            except ValueError:
                print_warning(f"[Audio] WARNING: Invalid threshold value: '{value_str}'")
                continue

            self.conditions.append(Condition(
                edge=edge,
                operator=operator,
                threshold=threshold,
                is_active=False
            ))

    def update(self, current_value: float) -> bool:
        """
        Update condition states and check for triggers

        Args:
            current_value: Current value of the watched spec

        Returns:
            True if any condition was triggered this update
        """
        triggered = False

        for condition in self.conditions:
            # Evaluate current condition state
            new_active = self._evaluate_condition(condition, current_value)

            # Check for edge detection
            if condition.edge == 'rising':
                # Trigger if condition just became true and value is rising
                if not condition.is_active and new_active:
                    if self._previous_value is not None and current_value > self._previous_value:
                        triggered = True
            elif condition.edge == 'falling':
                # Trigger if condition just became true and value is falling
                if not condition.is_active and new_active:
                    if self._previous_value is not None and current_value < self._previous_value:
                        triggered = True
            elif condition.edge == 'both':
                # Trigger on any transition to active
                if not condition.is_active and new_active:
                    triggered = True

            # Update state for next frame
            condition.is_active = new_active

        self._previous_value = current_value
        return triggered

    def _evaluate_condition(self, condition: Condition, value: float) -> bool:
        """Evaluate if a condition is currently true"""
        if condition.operator == '>':
            return value > condition.threshold
        elif condition.operator == '>=':
            return value >= condition.threshold
        elif condition.operator == '<':
            return value < condition.threshold
        elif condition.operator == '<=':
            return value <= condition.threshold
        elif condition.operator == '==':
            # For exact equality, use small epsilon
            return abs(value - condition.threshold) < 0.0001
        elif condition.operator == '!=':
            return abs(value - condition.threshold) >= 0.0001
        return False

    def reset(self):
        """Reset all condition states"""
        for condition in self.conditions:
            condition.is_active = False
        self._previous_value = None
