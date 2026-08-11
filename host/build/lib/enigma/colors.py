# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""ANSI color utilities for console output."""

# ANSI escape codes
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
BLINK = "\033[5m"
RESET = "\033[0m"


def print_error(message: str) -> None:
    """Print an error message in red."""
    print(f"{RED}{message}{RESET}")


def print_error_blink(message: str) -> None:
    """Print an error message in blinking bold red (for unmissable failures)."""
    print(f"{BLINK}{BOLD}{RED}{message}{RESET}")


def print_warning(message: str) -> None:
    """Print a warning message in yellow."""
    print(f"{YELLOW}{message}{RESET}")
