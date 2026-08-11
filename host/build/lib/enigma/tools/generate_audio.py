#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

"""
generate_audio.py - Generate type-safe audio event API from config files

Generates clean API for audio events based on audio_library.json:
- Simple events -> functions
- Looping events -> start/stop functions
- Watched events -> singleton classes
- Class-based volume controls

Usage:
    python enigma/tools/generate_audio.py
"""

import argparse
import json
import signal
from pathlib import Path
import sys
from typing import Dict, List, Set

# Add project root to path
script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
sys.path.insert(0, str(project_root))

from enigma.colors import print_error


def to_pascal_case(snake_str: str) -> str:
    """Convert snake_case to PascalCase"""
    return ''.join(word.capitalize() for word in snake_str.split('_'))


def to_snake_case(name: str) -> str:
    """Ensure name is in snake_case"""
    return name.lower().replace(' ', '_').replace('-', '_')


def generate_simple_event(event_name: str) -> List[str]:
    """Generate a simple one-shot event function"""
    lines = []
    lines.append(f"def {event_name}():")
    lines.append(f'    """Play {event_name} sound"""')
    lines.append(f"    get_audio().play_event('{event_name}')")
    lines.append("")
    return lines


def generate_looping_event(event_name: str) -> List[str]:
    """Generate start/stop functions for looping event"""
    lines = []

    # Start function
    lines.append(f"def start_{event_name}():")
    lines.append(f'    """Start {event_name} loop"""')
    lines.append(f"    get_audio().start_loop('{event_name}')")
    lines.append("")

    # Stop function
    lines.append(f"def stop_{event_name}():")
    lines.append(f'    """Stop {event_name} loop"""')
    lines.append(f"    get_audio().stop_loop('{event_name}')")
    lines.append("")

    return lines


def generate_watched_event(event_name: str) -> List[str]:
    """Generate singleton class for watched audio event"""
    class_name = to_pascal_case(event_name)

    lines = []
    lines.append(f"class {class_name}:")
    lines.append(f'    """Watched audio: {event_name}"""')
    lines.append("    _instance = None")
    lines.append(f"    _event_name = '{event_name}'")
    lines.append("")

    # __init__
    lines.append("    def __init__(self, watched_value):")
    lines.append(f'        """Initialize {event_name} watched audio')
    lines.append("        ")
    lines.append("        Args:")
    lines.append("            watched_value: Value to watch (PublishedValue or plain value)")
    lines.append('        """')
    lines.append(f"        if {class_name}._instance is not None:")
    lines.append(f'            raise RuntimeError("{class_name} already instantiated")')
    lines.append(f"        {class_name}._instance = self")
    lines.append("        self._watched_value = watched_value")
    lines.append("        get_audio().register_watched_audio(self._event_name, self)")
    lines.append("        self.start()")
    lines.append("")

    # get_current_value
    lines.append("    def get_current_value(self):")
    lines.append('        """Get current value from watched object"""')
    lines.append("        if hasattr(self._watched_value, 'value'):")
    lines.append("            return self._watched_value.value")
    lines.append("        return self._watched_value")
    lines.append("")

    # Class methods
    lines.append("    @classmethod")
    lines.append("    def start(cls):")
    lines.append(f'        """Start {event_name} playback"""')
    lines.append("        get_audio().start_watched_audio(cls._event_name)")
    lines.append("")

    lines.append("    @classmethod")
    lines.append("    def pause(cls):")
    lines.append(f'        """Pause {event_name} playback"""')
    lines.append("        get_audio().pause_watched_audio(cls._event_name)")
    lines.append("")

    lines.append("    @classmethod")
    lines.append("    def stop(cls):")
    lines.append(f'        """Stop {event_name} playback"""')
    lines.append("        get_audio().stop_watched_audio(cls._event_name)")
    lines.append("")

    lines.append("    @classmethod")
    lines.append("    def reset(cls, now=False):")
    lines.append(f'        """Reset {event_name} to default state"""')
    lines.append("        get_audio().reset_watched_audio(cls._event_name, now=now)")
    lines.append("")

    lines.append("    @classmethod")
    lines.append("    def ready(cls):")
    lines.append(f'        """Check if {event_name} is ready"""')
    lines.append("        return get_audio().watched_audio_ready(cls._event_name)")
    lines.append("")

    return lines


def generate_class_volume_control(class_name: str) -> List[str]:
    """Generate volume control class for an audio class"""
    pascal_name = to_pascal_case(class_name)

    lines = []
    lines.append(f"class AudioClass{pascal_name}:")
    lines.append(f'    """Volume control for {class_name} audio class"""')
    lines.append("")
    lines.append("    @staticmethod")
    lines.append("    def volume(level):")
    lines.append(f'        """Set {class_name} class volume (0.0 to 1.0)"""')
    lines.append(f"        get_audio().set_class_volume('{class_name}', level)")
    lines.append("")
    lines.append("    @staticmethod")
    lines.append("    def reset(now=False):")
    lines.append(f'        """Reset all {class_name} sounds"""')
    lines.append(f"        get_audio().reset_class('{class_name}', now=now)")
    lines.append("")
    lines.append("    @staticmethod")
    lines.append("    def ready():")
    lines.append(f'        """Check if {class_name} class is ready"""')
    lines.append(f"        return get_audio().class_ready('{class_name}')")
    lines.append("")
    lines.append("    @staticmethod")
    lines.append("    def clear_pending():")
    lines.append(f'        """Drop queued (not-yet-playing) {class_name} requests.')
    lines.append("        Currently-playing item is untouched. Returns count removed.\"\"\"")
    lines.append(f"        return get_audio().clear_pending_class('{class_name}')")
    lines.append("")

    return lines


def generate_nested_class_structure(events_by_class: Dict[str, List]) -> List[str]:
    """Generate nested class structure (UI, Music, Ambient, etc.)"""
    lines = []

    for class_name in sorted(events_by_class.keys()):
        events = events_by_class[class_name]
        pascal_name = to_pascal_case(class_name)

        lines.append(f"class {pascal_name}:")
        lines.append(f'    """Audio events in {class_name} class"""')
        lines.append("")

        # Class-level volume control
        lines.append("    @staticmethod")
        lines.append("    def volume(level):")
        lines.append(f'        """Set {class_name} class volume (0.0 to 1.0)"""')
        lines.append(f"        get_audio().set_class_volume('{class_name}', level)")
        lines.append("")

        lines.append("    @staticmethod")
        lines.append("    def reset(now=False):")
        lines.append(f'        """Reset all {class_name} sounds"""')
        lines.append(f"        get_audio().reset_class('{class_name}', now=now)")
        lines.append("")

        lines.append("    @staticmethod")
        lines.append("    def ready():")
        lines.append(f'        """Check if {class_name} class is ready"""')
        lines.append(f"        return get_audio().class_ready('{class_name}')")
        lines.append("")

        lines.append("    @staticmethod")
        lines.append("    def clear_pending():")
        lines.append(f'        """Drop queued (not-yet-playing) {class_name} requests.')
        lines.append("        Currently-playing item is untouched. Returns count removed.\"\"\"")
        lines.append(f"        return get_audio().clear_pending_class('{class_name}')")
        lines.append("")

        # Add event methods/classes
        for event_name, event_config in events:
            has_watch_spec = 'watch_spec' in event_config
            is_looping = event_config.get('loops', False) or event_config.get('shuffle', False)

            if has_watch_spec:
                # Nested class for watched audio
                nested_class_name = to_pascal_case(event_name)
                lines.append(f"    class {nested_class_name}:")
                lines.append(f'        """Watched audio: {event_name}"""')
                lines.append("        _instance = None")
                lines.append(f"        _event_name = '{event_name}'")
                lines.append("")

                lines.append("        def __init__(self, watched_value):")
                lines.append(f'            """Initialize {event_name} watched audio"""')
                lines.append(f"            if {pascal_name}.{nested_class_name}._instance is not None:")
                lines.append(f'                raise RuntimeError("{nested_class_name} already instantiated")')
                lines.append(f"            {pascal_name}.{nested_class_name}._instance = self")
                lines.append("            self._watched_value = watched_value")
                lines.append("            get_audio().register_watched_audio(self._event_name, self)")
                lines.append("            self.start()")
                lines.append("")

                lines.append("        def get_current_value(self):")
                lines.append("            if hasattr(self._watched_value, 'value'):")
                lines.append("                return self._watched_value.value")
                lines.append("            return self._watched_value")
                lines.append("")

                lines.append("        @classmethod")
                lines.append("        def start(cls):")
                lines.append("            get_audio().start_watched_audio(cls._event_name)")
                lines.append("")

                lines.append("        @classmethod")
                lines.append("        def pause(cls):")
                lines.append("            get_audio().pause_watched_audio(cls._event_name)")
                lines.append("")

                lines.append("        @classmethod")
                lines.append("        def stop(cls):")
                lines.append("            get_audio().stop_watched_audio(cls._event_name)")
                lines.append("")

                lines.append("        @classmethod")
                lines.append("        def reset(cls, now=False):")
                lines.append("            get_audio().reset_watched_audio(cls._event_name, now=now)")
                lines.append("")

                lines.append("        @classmethod")
                lines.append("        def ready(cls):")
                lines.append("            return get_audio().watched_audio_ready(cls._event_name)")
                lines.append("")

            elif is_looping:
                # Static methods for looping
                lines.append("    @staticmethod")
                lines.append(f"    def {event_name}():")
                lines.append(f'        """Start {event_name} loop"""')
                lines.append(f"        get_audio().start_loop('{event_name}')")
                lines.append("")

                lines.append("    @staticmethod")
                lines.append(f"    def stop_{event_name}():")
                lines.append(f'        """Stop {event_name} loop"""')
                lines.append(f"        get_audio().stop_loop('{event_name}')")
                lines.append("")
            else:
                # Simple one-shot event
                lines.append("    @staticmethod")
                lines.append(f"    def {event_name}():")
                lines.append(f'        """Play {event_name} sound"""')
                lines.append(f"        get_audio().play_event('{event_name}')")
                lines.append("")

    return lines


def generate_audio_events(library_config: dict, classes_config: dict) -> str:
    """Generate the complete audio_events.py file"""

    lines = []

    # Header
    lines.append("# AUTO-GENERATED FILE - DO NOT EDIT")
    lines.append("# Generated by enigma/tools/generate_audio.py")
    lines.append('"""')
    lines.append("Type-safe audio event API")
    lines.append("")
    lines.append("Generated from audio_library.json and audio_classes.json")
    lines.append('"""')
    lines.append("")
    lines.append("from enigma.audio import AudioManager")
    lines.append("")
    lines.append("")
    lines.append("def get_audio():")
    lines.append('    """Get AudioManager singleton instance"""')
    lines.append("    return AudioManager.get_instance()")
    lines.append("")
    lines.append("")

    # Group events by class
    events_by_class: Dict[str, List] = {}
    events = library_config.get('events', {})

    for event_name, event_config in events.items():
        class_name = event_config.get('class', 'event')
        if class_name not in events_by_class:
            events_by_class[class_name] = []
        events_by_class[class_name].append((event_name, event_config))

    # Generate nested class structure
    lines.extend(generate_nested_class_structure(events_by_class))

    # Generate master volume controls
    lines.append("class Audio:")
    lines.append('    """Master audio controls"""')
    lines.append("")
    lines.append("    @staticmethod")
    lines.append("    def master_audio_volume(level):")
    lines.append('        """Set master audio output volume (0.0 to 1.0)"""')
    lines.append("        get_audio().set_master_audio_volume(level)")
    lines.append("")
    lines.append("    @staticmethod")
    lines.append("    def master_haptic_volume(level):")
    lines.append('        """Set master haptic output volume (0.0 to 1.0)"""')
    lines.append("        get_audio().set_master_haptic_volume(level)")
    lines.append("")
    lines.append("    @staticmethod")
    lines.append("    def reset(now=False):")
    lines.append('        """Reset all audio"""')
    lines.append("        get_audio().reset_all(now=now)")
    lines.append("")
    lines.append("    @staticmethod")
    lines.append("    def ready():")
    lines.append('        """Check if all audio is ready"""')
    lines.append("        return get_audio().all_ready()")
    lines.append("")

    return '\n'.join(lines)


def generate_documentation(library_config: dict, classes_config: dict, output_file: Path):
    """Generate human-readable documentation for audio events"""

    print(f"Generating documentation: {output_file}")

    lines = []
    lines.append("=" * 80)
    lines.append("HALCYON DAWN AUDIO EVENTS REFERENCE")
    lines.append("=" * 80)
    lines.append("")
    lines.append("This file contains all available audio events with copy-paste examples.")
    lines.append("")
    lines.append("Generated from: audio_library.json and audio_classes.json")
    lines.append("")

    # Group events by class
    events_by_class: Dict[str, List] = {}
    events = library_config.get('events', {})

    for event_name, event_config in events.items():
        class_name = event_config.get('class', 'event')
        if class_name not in events_by_class:
            events_by_class[class_name] = []
        events_by_class[class_name].append((event_name, event_config))

    # Document each class
    for class_name in sorted(events_by_class.keys()):
        class_pascal = to_pascal_case(class_name)
        events_list = events_by_class[class_name]

        lines.append("")
        lines.append("=" * 80)
        lines.append(f"CLASS: {class_name.upper()} ({class_pascal})")
        lines.append("=" * 80)
        lines.append("")

        # Class volume control
        lines.append(f"Volume Control:")
        lines.append(f"  {class_pascal}.volume(0.5)  # Set {class_name} volume to 50%")
        lines.append("")
        lines.append(f"Reset:")
        lines.append(f"  {class_pascal}.reset()       # Graceful 5-second fadeout")
        lines.append(f"  {class_pascal}.reset(now=True)  # Immediate stop")
        lines.append("")

        # Events in this class
        lines.append("Events:")
        lines.append("")

        for event_name, event_config in sorted(events_list):
            has_watch_spec = 'watch_spec' in event_config
            is_looping = event_config.get('loops', False) or event_config.get('shuffle', False)
            priority = event_config.get('priority')
            fade_in = event_config.get('fade_in')

            lines.append(f"  {event_name}")

            # Config details
            if event_config.get('audio'):
                lines.append(f"    Audio: {event_config['audio']}")
            if event_config.get('haptic'):
                lines.append(f"    Haptic: {event_config['haptic']}")
            if priority is not None:
                lines.append(f"    Priority: {priority}")
            if fade_in:
                lines.append(f"    Fade-in: {fade_in}s")

            # Usage examples
            if has_watch_spec:
                nested_class = to_pascal_case(event_name)
                lines.append(f"    Usage (Watched Audio):")
                lines.append(f"      {class_pascal}.{nested_class}(my_throttle_value)")
                lines.append(f"      {class_pascal}.{nested_class}.pause()")
                lines.append(f"      {class_pascal}.{nested_class}.stop()")
                if 'thresholds' in event_config:
                    lines.append(f"    Thresholds:")
                    for threshold in event_config['thresholds']:
                        range_str = f"{threshold['value_range'][0]:.1f}-{threshold['value_range'][1]:.1f}"
                        lines.append(f"      {range_str}: {threshold.get('audio', 'N/A')}")
            elif is_looping:
                lines.append(f"    Usage (Looping):")
                lines.append(f"      {class_pascal}.{event_name}()")
                lines.append(f"      {class_pascal}.stop_{event_name}()")
            else:
                lines.append(f"    Usage (One-shot):")
                lines.append(f"      {class_pascal}.{event_name}()")

            lines.append("")

    # Master controls
    lines.append("")
    lines.append("=" * 80)
    lines.append("MASTER CONTROLS (Audio)")
    lines.append("=" * 80)
    lines.append("")
    lines.append("Master Volumes:")
    lines.append("  Audio.master_audio_volume(0.8)   # Main speakers at 80%")
    lines.append("  Audio.master_haptic_volume(1.0)  # Haptic amp at 100%")
    lines.append("")
    lines.append("Global Reset:")
    lines.append("  Audio.reset()           # Graceful 5-second fadeout")
    lines.append("  Audio.reset(now=True)   # Immediate stop")
    lines.append("  Audio.ready()           # Check if reset complete")
    lines.append("")

    # Quick reference
    lines.append("")
    lines.append("=" * 80)
    lines.append("QUICK REFERENCE")
    lines.append("=" * 80)
    lines.append("")
    lines.append("Import:")
    lines.append("  from generated.audio_events import Ui, Music, Ambient, Event, Voice, Audio")
    lines.append("")
    lines.append("Examples:")
    lines.append("  Ui.button_click()                    # Play UI click")
    lines.append("  Music.combat_music()                 # Start combat music")
    lines.append("  Event.missile_impact()               # Play impact with haptic")
    lines.append("  Voice.voice_antimatter_critical()    # Priority voice callout")
    lines.append("  Ambient.PortEngine(throttle_value)   # Start engine audio")
    lines.append("  Music.volume(0.5)                    # Lower music volume")
    lines.append("  Audio.master_audio_volume(0.8)       # Master volume to 80%")
    lines.append("")

    # Write to file
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        f.write('\n'.join(lines))

    print(f"Documentation generated: {output_file}")


def main():
    # Route Ctrl-\ through KeyboardInterrupt instead of SIGQUIT's default core
    # dump, which triggers macOS's crash dialog (see hd.py).
    signal.signal(signal.SIGQUIT, signal.default_int_handler)

    parser = argparse.ArgumentParser(description='Generate audio events from config')
    parser.add_argument('--config-dir', type=Path, default=Path('configs'),
                       help='Directory containing audio config files (default: configs)')
    parser.add_argument('--output', type=Path, default=Path('generated/audio_events.py'),
                       help='Output file path (default: generated/audio_events.py)')
    parser.add_argument('--docs', type=Path, default=None,
                       help='Optional documentation output file (e.g., docs/audio_reference.txt)')

    # Show help if no arguments provided
    if len(sys.argv) == 1:
        parser.print_help()
        return 0

    args = parser.parse_args()

    config_dir = args.config_dir
    output_path = args.output

    # Load configs
    library_path = config_dir / 'audio_library.json'
    classes_path = config_dir / 'audio_classes.json'

    if not library_path.exists():
        print_error(f"ERROR: {library_path} not found")
        return 1

    if not classes_path.exists():
        print_error(f"ERROR: {classes_path} not found")
        return 1

    with open(library_path, 'r') as f:
        library_config = json.load(f)

    with open(classes_path, 'r') as f:
        classes_config = json.load(f)

    # Generate code
    code = generate_audio_events(library_config, classes_config)

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(code)

    print(f"Generated {output_path}")

    # Generate documentation if requested
    if args.docs:
        generate_documentation(library_config, classes_config, args.docs)

    return 0


if __name__ == '__main__':
    exit(main())
