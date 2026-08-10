#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
generate_devices.py - Generate type-safe device specifications from config files

Generates singleton device specs with PublishedEnum, PublishedNumber, PublishedBool, PublishedString
descriptors for clean syntax like:

    if PowerCore.Temperature > PowerCore.Thresholds.Temperature.CRITICAL:
        PowerCore.ReactorState = PowerCore.ReactorState.SCRAM

Usage:
    python tools/generate_devices.py --config-dir configs/ --output generated/devices.py
    python tools/generate_devices.py --config-dir configs/ --output generated/devices.py --docs devices_reference.txt
"""

import argparse
import json
import signal
from pathlib import Path
from typing import Dict, Set, List, Any, Optional
import sys

# Add project root to path
script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent  # tools/ -> enigma/ -> project_root/
sys.path.insert(0, str(project_root))

from enigma.colors import print_error, print_warning


def sanitize_class_name(name: str) -> str:
    """Convert a name to a valid Python class name preserving case"""
    sanitized = ''.join(c if c.isalnum() else '' for c in name)
    if sanitized and sanitized[0].isdigit():
        sanitized = '_' + sanitized
    return sanitized


def sanitize_identifier(name: str) -> str:
    """Convert a name to a valid Python identifier (uppercase)"""
    sanitized = ''.join(c if c.isalnum() else '_' for c in name)
    if sanitized[0].isdigit():
        sanitized = '_' + sanitized
    return sanitized.upper()


# Valid keys for each type
VALID_ATTRIBUTE_KEYS = {'type', 'default', 'constants', 'desc'}
VALID_ENUM_KEYS = {'type', 'values', 'default', 'desc'}
VALID_TYPES = {'number', 'bool', 'enum', 'string'}


def parse_device_spec(device_name: str, spec_data: dict, filepath: Path) -> dict:
    """Parse and validate a device spec JSON

    Returns dict of {attr_name -> attr_config} with validated/defaulted values
    """
    attributes = {}
    seen_names = set()

    for attr_name, attr_data in spec_data.items():
        # Check for duplicate names
        if attr_name in seen_names:
            print_error(f"ERROR: {filepath}: Duplicate attribute name '{attr_name}'")
            continue
        seen_names.add(attr_name)

        # Validate attribute name
        if not attr_name or not attr_name[0].isalpha():
            print_error(f"ERROR: {filepath}: Invalid attribute name '{attr_name}' - must start with letter")
            continue

        # Get type
        attr_type = attr_data.get('type')
        if not attr_type:
            print_error(f"ERROR: {filepath}.{attr_name}: Missing 'type' field")
            continue

        if attr_type not in VALID_TYPES:
            print_error(f"ERROR: {filepath}.{attr_name}: Invalid type '{attr_type}'. Valid types: {VALID_TYPES}")
            continue

        # Validate keys based on type
        if attr_type == 'enum':
            valid_keys = VALID_ENUM_KEYS
        else:
            valid_keys = VALID_ATTRIBUTE_KEYS

        unknown_keys = set(attr_data.keys()) - valid_keys
        if unknown_keys:
            print_warning(f"WARNING: {filepath}.{attr_name}: Unknown keys: {unknown_keys}")

        # Parse based on type
        if attr_type == 'enum':
            parsed = parse_enum_attribute(device_name, attr_name, attr_data, filepath)
        elif attr_type == 'string':
            parsed = parse_string_attribute(device_name, attr_name, attr_data, filepath)
        elif attr_type == 'number':
            parsed = parse_number_attribute(device_name, attr_name, attr_data, filepath)
        elif attr_type == 'bool':
            parsed = parse_bool_attribute(device_name, attr_name, attr_data, filepath)
        else:
            continue

        if parsed:
            attributes[attr_name] = parsed

    return attributes


def parse_string_attribute(device_name: str, attr_name: str, attr_data: dict, filepath: Path) -> Optional[dict]:
    """Parse a string attribute"""
    default = attr_data.get('default', '')

    if not isinstance(default, str):
        print_error(f"ERROR: {filepath}.{attr_name}: Default must be a string")
        return None

    desc = attr_data.get('desc', '')

    return {
        'type': 'string',
        'default': default,
        'desc': desc
    }


def parse_enum_attribute(device_name: str, attr_name: str, attr_data: dict, filepath: Path) -> Optional[dict]:
    """Parse an enum attribute"""
    values = attr_data.get('values')
    if not values:
        print_error(f"ERROR: {filepath}.{attr_name}: Enum must have 'values' list")
        return None

    if not isinstance(values, list) or len(values) == 0:
        print_error(f"ERROR: {filepath}.{attr_name}: 'values' must be non-empty list")
        return None

    # Validate all values are strings
    for v in values:
        if not isinstance(v, str):
            print_error(f"ERROR: {filepath}.{attr_name}: Enum values must be strings, got {type(v).__name__}")
            return None

    # Check for duplicate values
    if len(values) != len(set(values)):
        print_error(f"ERROR: {filepath}.{attr_name}: Duplicate enum values")
        return None

    # Default to first value if not specified
    default = attr_data.get('default', values[0])
    if default not in values:
        print_error(f"ERROR: {filepath}.{attr_name}: Default '{default}' not in values list")
        return None

    desc = attr_data.get('desc', '')

    return {
        'type': 'enum',
        'values': values,
        'default': default,
        'desc': desc
    }


def parse_number_attribute(device_name: str, attr_name: str, attr_data: dict, filepath: Path) -> Optional[dict]:
    """Parse a number attribute"""
    default = attr_data.get('default', 0)

    if not isinstance(default, (int, float)):
        print_error(f"ERROR: {filepath}.{attr_name}: Default must be a number, got {type(default).__name__}")
        return None

    constants = attr_data.get('constants', {})
    if not isinstance(constants, dict):
        print_error(f"ERROR: {filepath}.{attr_name}: 'constants' must be a dict")
        return None

    # Validate all constants are numbers
    for const_name, const_val in constants.items():
        if not isinstance(const_val, (int, float)):
            print_error(f"ERROR: {filepath}.{attr_name}: Constant '{const_name}' must be a number, got {type(const_val).__name__}")
            return None

    desc = attr_data.get('desc', '')

    return {
        'type': 'number',
        'default': default,
        'constants': constants,
        'desc': desc
    }


def parse_bool_attribute(device_name: str, attr_name: str, attr_data: dict, filepath: Path) -> Optional[dict]:
    """Parse a bool attribute"""
    default = attr_data.get('default', False)

    if not isinstance(default, bool):
        print_error(f"ERROR: {filepath}.{attr_name}: Default must be a bool, got {type(default).__name__}")
        return None

    # Bools can have constants too (rare, but supported)
    constants = attr_data.get('constants', {})
    if not isinstance(constants, dict):
        print_error(f"ERROR: {filepath}.{attr_name}: 'constants' must be a dict")
        return None

    desc = attr_data.get('desc', '')

    return {
        'type': 'bool',
        'default': default,
        'constants': constants,
        'desc': desc
    }



def generate_string_code(attr_name: str, attr_config: dict) -> List[str]:
    """Generate code for a string attribute"""
    lines = []
    default = attr_config['default']

    if attr_config['desc']:
        lines.append(f'    # {attr_config["desc"]}')
    lines.append(f'    {attr_name} = PublishedString(default={default!r})')
    lines.append("")
    return lines

def generate_enum_code(attr_name: str, attr_config: dict) -> List[str]:
    """Generate code for an enum attribute with .Values nested class"""
    lines = []
    class_name = f"_{attr_name}"

    # Inner class with enum values AND a Values nested class
    lines.append(f"    class {class_name}:")
    if attr_config['desc']:
        lines.append(f'        """{attr_config["desc"]}"""')

    # Add Values nested class for consistent API with controls
    lines.append(f"        class Values:")
    for value in attr_config['values']:
        const_name = sanitize_identifier(value)
        lines.append(f'            {const_name} = "{value}"')
    lines.append("")

    # Also add constants at class level for backward compatibility
    for value in attr_config['values']:
        const_name = sanitize_identifier(value)
        lines.append(f'        {const_name} = "{value}"')
    lines.append("")

    # Descriptor assignment
    default_const = sanitize_identifier(attr_config['default'])
    lines.append(f"    {attr_name} = PublishedEnum({class_name}, default={class_name}.{default_const})")
    lines.append("")

    return lines


def generate_number_code(attr_name: str, attr_config: dict) -> List[str]:
    """Generate code for a number attribute"""
    lines = []

    constants = attr_config.get('constants', {})
    default = attr_config['default']

    if constants:
        class_name = f"_{attr_name}"

        # Inner class with constants
        lines.append(f"    class {class_name}:")
        if attr_config['desc']:
            lines.append(f'        """{attr_config["desc"]}"""')
        for const_name, const_val in sorted(constants.items()):
            const_id = sanitize_identifier(const_name)
            lines.append(f"        {const_id} = {const_val}")
        lines.append("")

        # Descriptor assignment with thresholds
        lines.append(f"    {attr_name} = PublishedNumber(default={default}, thresholds={class_name})")
    else:
        # Simple number, no constants
        if attr_config['desc']:
            lines.append(f'    # {attr_config["desc"]}')
        lines.append(f"    {attr_name} = PublishedNumber(default={default})")

    lines.append("")
    return lines


def generate_bool_code(attr_name: str, attr_config: dict) -> List[str]:
    """Generate code for a bool attribute"""
    lines = []

    default = attr_config['default']
    default_str = "True" if default else "False"

    constants = attr_config.get('constants', {})

    if constants:
        class_name = f"_{attr_name}"

        # Inner class with constants
        lines.append(f"    class {class_name}:")
        if attr_config['desc']:
            lines.append(f'        """{attr_config["desc"]}"""')
        for const_name, const_val in sorted(constants.items()):
            const_id = sanitize_identifier(const_name)
            const_val_str = "True" if const_val else "False"
            lines.append(f"        {const_id} = {const_val_str}")
        lines.append("")

        lines.append(f"    {attr_name} = PublishedBool(default={default_str}, constants={class_name})")
    else:
        if attr_config['desc']:
            lines.append(f'    # {attr_config["desc"]}')
        lines.append(f"    {attr_name} = PublishedBool(default={default_str})")

    lines.append("")
    return lines


def generate_device_class(device_name: str, attributes: dict) -> str:
    """Generate a complete device spec class"""
    class_name = sanitize_class_name(device_name)

    lines = []
    lines.append(f"class _{class_name}(DeviceSpec):")
    lines.append(f'    """Auto-generated device spec: {device_name}"""')
    lines.append(f'    NAME = "{device_name}"')
    lines.append("")

    # Generate each attribute
    for attr_name, attr_config in sorted(attributes.items()):
        if attr_config['type'] == 'enum':
            lines.extend(generate_enum_code(attr_name, attr_config))
        elif attr_config['type'] == 'string':
            lines.extend(generate_string_code(attr_name, attr_config))
        elif attr_config['type'] == 'number':
            lines.extend(generate_number_code(attr_name, attr_config))
        elif attr_config['type'] == 'bool':
            lines.extend(generate_bool_code(attr_name, attr_config))

    # Additive public accessor for JSON-declared number/bool constants. Reading
    # Spec.<Field> returns the value (not the descriptor), so those constants are
    # otherwise unreachable from the public singleton. Enum values stay on
    # <Field>.Values. This block re-declares the constants so it is self-contained
    # and purely additive: the existing descriptors and their inner classes are
    # untouched.
    const_fields = [
        (name, cfg) for name, cfg in sorted(attributes.items())
        if cfg['type'] in ('number', 'bool') and cfg.get('constants')
    ]
    if const_fields:
        lines.append("    class Thresholds:")
        lines.append('        """Named constants for this spec\'s number/bool fields (from the JSON)."""')
        for name, cfg in const_fields:
            lines.append(f"        class {name}:")
            for const_name, const_val in sorted(cfg['constants'].items()):
                const_id = sanitize_identifier(const_name)
                if cfg['type'] == 'bool':
                    const_val = "True" if const_val else "False"
                lines.append(f"            {const_id} = {const_val}")
        lines.append("")

    return '\n'.join(lines)


def generate_devices_file(config_dir: Path, output_file: Path):
    """Generate the complete devices file"""

    # Load device mappings
    mappings_file = config_dir / "device_mappings.json"
    if not mappings_file.exists():
        print_error(f"ERROR: Device mappings file not found: {mappings_file}")
        sys.exit(1)

    with open(mappings_file, 'r') as f:
        mappings = json.load(f)

    print(f"Reading device specs from {config_dir}")
    print(f"Found {len(mappings)} device mappings")

    lines = []
    lines.append('"""')
    lines.append('Auto-generated device specifications from Enigma device configurations')
    lines.append('')
    lines.append('DO NOT EDIT THIS FILE MANUALLY')
    lines.append('Generated by: enigma/tools/generate_devices.py')
    lines.append('')
    lines.append('Usage:')
    lines.append('    from generated.devices import PowerCore, CoolingSystem')
    lines.append('    ')
    lines.append('    # Read value')
    lines.append('    if PowerCore.Temperature > PowerCore.Thresholds.Temperature.CRITICAL:')
    lines.append('        ...')
    lines.append('    ')
    lines.append('    # Write value')
    lines.append('    PowerCore.ReactorState = PowerCore.ReactorState.SCRAM')
    lines.append('    ')
    lines.append('    # Compare enum')
    lines.append('    if PowerCore.ReactorState == PowerCore.ReactorState.OFFLINE:')
    lines.append('        ...')
    lines.append('    ')
    lines.append('    # Reset all to defaults')
    lines.append('    from enigma.device import PublishedValue')
    lines.append('    PublishedValue.reset_all()')
    lines.append('"""')
    lines.append('')
    lines.append('from enigma.device import DeviceSpec, PublishedEnum, PublishedNumber, PublishedBool, PublishedString')
    lines.append('')
    lines.append('')

    # Track generated classes for singleton instantiation
    device_classes = []
    # Track spec files we've already processed (for shared specs like engine.json)
    processed_specs = {}  # spec_file -> (class_name, attributes)
    # Track aliases (device_name -> original_class_name)
    aliases = {}

    for device_name, spec_file in sorted(mappings.items()):
        spec_path = config_dir / spec_file

        if not spec_path.exists():
            print_error(f"ERROR: Spec file not found: {spec_path}")
            continue

        # Check if we've already processed this spec file
        if spec_file in processed_specs:
            # This is an alias to an existing spec
            aliases[device_name] = processed_specs[spec_file]
            print(f"  {device_name} -> {spec_file} (alias of {processed_specs[spec_file]})")
            continue

        print(f"  {device_name} -> {spec_file}")

        with open(spec_path, 'r') as f:
            try:
                spec_data = json.load(f)
            except json.JSONDecodeError as e:
                print_error(f"ERROR: Invalid JSON in {spec_path}: {e}")
                continue

        attributes = parse_device_spec(device_name, spec_data, spec_path)

        if not attributes:
            print_warning(f"WARNING: No valid attributes in {spec_path}")
            continue

        device_code = generate_device_class(device_name, attributes)
        lines.append(device_code)
        lines.append("")

        class_name = sanitize_class_name(device_name)
        device_classes.append(class_name)
        processed_specs[spec_file] = class_name

    # Create singleton instances
    lines.append("# Singleton instances")
    for class_name in device_classes:
        lines.append(f"{class_name} = _{class_name}()")
    lines.append("")

    # Create aliases (separate instances for devices sharing same spec)
    if aliases:
        lines.append("# Aliases (devices sharing the same spec, but with separate state)")
        for alias_name, original_class in sorted(aliases.items()):
            alias_class = sanitize_class_name(alias_name)
            # Create a new instance for the alias (separate state)
            lines.append(f"{alias_class} = _{original_class}()")
        lines.append("")

    # Helper to get all device instances
    all_devices = device_classes + [sanitize_class_name(a) for a in aliases.keys()]
    lines.append("# All device instances")
    lines.append(f"ALL_DEVICES = [{', '.join(all_devices)}]")
    lines.append("")

    # Ensure output directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Write file
    output_file.write_text('\n'.join(lines))
    print(f"\nGenerated {output_file}")
    print(f"  {len(device_classes)} device specs")
    print(f"  {len(aliases)} aliases")


def generate_documentation(config_dir: Path, output_file: Path):
    """Generate human-readable documentation"""

    mappings_file = config_dir / "device_mappings.json"
    if not mappings_file.exists():
        print_error(f"ERROR: Device mappings file not found: {mappings_file}")
        return

    with open(mappings_file, 'r') as f:
        mappings = json.load(f)

    lines = []
    lines.append("=" * 80)
    lines.append("ENIGMA DEVICE SPECIFICATION REFERENCE")
    lines.append("=" * 80)
    lines.append("")
    lines.append("This file contains all device specs, their attributes, and usage examples.")
    lines.append("")

    # Track processed specs for alias detection
    processed_specs = {}

    for device_name, spec_file in sorted(mappings.items()):
        spec_path = config_dir / spec_file

        if not spec_path.exists():
            continue

        with open(spec_path, 'r') as f:
            try:
                spec_data = json.load(f)
            except json.JSONDecodeError:
                continue

        attributes = parse_device_spec(device_name, spec_data, spec_path)
        if not attributes:
            continue

        class_name = sanitize_class_name(device_name)

        # Check if this is an alias
        is_alias = spec_file in processed_specs
        if not is_alias:
            processed_specs[spec_file] = class_name

        lines.append("=" * 80)
        lines.append(f"DEVICE: {device_name}")
        lines.append("=" * 80)
        lines.append(f"Spec file: {spec_file}")
        lines.append(f"Instance: {class_name}")
        if is_alias:
            lines.append(f"Note: Shares spec with {processed_specs[spec_file]}, but has separate state")
        lines.append("")

        lines.append("Attributes:")
        lines.append("")

        for attr_name, attr_config in sorted(attributes.items()):
            lines.append(f"  {attr_name}:")
            lines.append(f"    Type: {attr_config['type']}")

            if attr_config.get('desc'):
                lines.append(f"    Description: {attr_config['desc']}")

            if attr_config['type'] == 'enum':
                default_const = sanitize_identifier(attr_config['default'])
                lines.append(f"    Default: {class_name}.{attr_name}.Values.{default_const}")
                lines.append("")
                lines.append("    Values:")
                for value in attr_config['values']:
                    const_name = sanitize_identifier(value)
                    lines.append(f"      {class_name}.{attr_name}.Values.{const_name}")
                lines.append("")
                lines.append("    Usage:")
                first_val = sanitize_identifier(attr_config['values'][0])
                lines.append(f"      # Read/compare")
                lines.append(f"      if {class_name}.{attr_name} == {class_name}.{attr_name}.Values.{first_val}:")
                lines.append(f"          ...")
                lines.append(f"      ")
                lines.append(f"      # Write")
                lines.append(f"      {class_name}.{attr_name} = {class_name}.{attr_name}.Values.{first_val}")


            elif attr_config['type'] == 'number':
                lines.append(f"    Default: {attr_config['default']}")

                constants = attr_config.get('constants', {})
                if constants:
                    lines.append("")
                    lines.append("    Constants:")
                    for const_name, const_val in sorted(constants.items()):
                        const_id = sanitize_identifier(const_name)
                        lines.append(f"      {class_name}.{attr_name}.{const_id} = {const_val}")
                    lines.append("")
                    lines.append("    Usage:")
                    first_const = sanitize_identifier(list(constants.keys())[0])
                    lines.append(f"      # Compare against threshold")
                    lines.append(f"      if {class_name}.{attr_name} > {class_name}.{attr_name}.{first_const}:")
                    lines.append(f"          ...")
                    lines.append(f"      ")
                    lines.append(f"      # Write")
                    lines.append(f"      {class_name}.{attr_name} = 123.45")
                else:
                    lines.append("")
                    lines.append("    Usage:")
                    lines.append(f"      # Read")
                    lines.append(f"      value = {class_name}.{attr_name}")
                    lines.append(f"      ")
                    lines.append(f"      # Write")
                    lines.append(f"      {class_name}.{attr_name} = 123.45")

            elif attr_config['type'] == 'bool':
                default_str = "True" if attr_config['default'] else "False"
                lines.append(f"    Default: {default_str}")
                lines.append("")
                lines.append("    Usage:")
                lines.append(f"      # Read")
                lines.append(f"      if {class_name}.{attr_name}:")
                lines.append(f"          ...")
                lines.append(f"      ")
                lines.append(f"      # Write")
                lines.append(f"      {class_name}.{attr_name} = True")

            lines.append("")

    # Global operations
    lines.append("=" * 80)
    lines.append("GLOBAL OPERATIONS")
    lines.append("=" * 80)
    lines.append("")
    lines.append("Reset all devices to defaults:")
    lines.append("    from enigma.device import PublishedValue")
    lines.append("    PublishedValue.reset_all()")
    lines.append("")
    lines.append("Or via manager:")
    lines.append("    manager.reset_simulation()")
    lines.append("")

    output_file.write_text('\n'.join(lines))
    print(f"\nDocumentation written to {output_file}")


def main():
    # Route Ctrl-\ through KeyboardInterrupt instead of SIGQUIT's default core
    # dump, which triggers macOS's crash dialog (see hd.py).
    signal.signal(signal.SIGQUIT, signal.default_int_handler)

    parser = argparse.ArgumentParser(description='Generate device specs from config files')
    parser.add_argument('--config-dir', type=Path, default=Path('configs'),
                       help='Directory containing config files (default: configs)')
    parser.add_argument('--output', type=Path, default=Path('generated/devices.py'),
                       help='Output file (default: generated/devices.py)')
    parser.add_argument('--docs', type=Path, default=None,
                       help='Optional documentation output file')

    args = parser.parse_args()

    if not args.config_dir.exists():
        print_error(f"ERROR: Config directory not found: {args.config_dir}")
        sys.exit(1)

    generate_devices_file(args.config_dir, args.output)

    if args.docs:
        generate_documentation(args.config_dir, args.docs)


if __name__ == '__main__':
    main()
