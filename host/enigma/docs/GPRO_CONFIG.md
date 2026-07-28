# GPRO Keyboard Configuration

The GPRO handler manages Logitech G Pro keyboards with per-key RGB lighting, letting you define different color schemes for different game modes. This obviously isn't a device in the Enigma family, but I wanted my game code to be able to interact with it via the same coding conventions as my own boards.

> [!NOTE]
> On macOS Tahoe, interacting with the G Pro requires root privileges. The
> [`enigma/tools/`](../tools/) directory contains scripts that keep the custom
> keyboard daemon running; start it before your application.

> [!NOTE] 
> On my build, I physically removed a lot of keys that weren't pertinent to my game (removed the caps and snipped off the keyswitch stalks).  I *think* I included all the keys this keyboard supports in the code, but honestly I don't recall.

## File Structure

```json
{
  "name": "Keyboard",
  "background": "#0000FF",
  "meta": "#FFFFFF",
  "alpha": "#00FF00",
  "numeric": "#00FFFF",
  "punctuation": "#FFFF00",
  "custom": {
    "keys": " {BACKSPACE}{ESC}",
    "color": "#FF00FF"
  },
  "schemes": {
    "schemeName": { ... }
  }
}
```

## Top-Level Properties

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `name` | string | Required | Configuration identifier |
| `background` | string | `"#000000"` | Default color for all keys |
| `meta` | string | background | Color for modifier keys |
| `alpha` | string | background | Color for letter keys (A-Z) |
| `numeric` | string | background | Color for number keys and `-` `=` |
| `punctuation` | string | background | Color for punctuation keys |
| `custom` | object | none | Custom key-specific overrides |
| `schemes` | object | none | Named alternate color schemes |

## Key Groups

Keys are automatically categorized into groups. Colors are applied in priority order: background -> group -> custom.

| Group | Keys |
|-------|------|
| `alpha` | A-Z (26 letters) |
| `numeric` | 0-9, `-`, `=` |
| `punctuation` | `` ` `` `[` `]` `\` `;` `'` `,` `.` `/` |
| `meta` | ENTER, BACKSPACE, SPACE, ESC, UP, DOWN, LEFT, RIGHT, LSHIFT, RSHIFT |
| `background` | All other keys |

## Custom Key Overrides

The `custom` object allows overriding specific keys with a single color:

```json
"custom": {
  "keys": "wasd {SPACE}",
  "color": "#00FF00"
}
```

`custom` may also be a **list** of `{keys, color}` blocks, to apply several
distinct overrides in one scheme; on overlapping keys, later entries win:

```json
"custom": [
  { "keys": "wasd",    "color": "#00FF00" },
  { "keys": "{SPACE}", "color": "#0000FF" }
]
```

### Key Specification

Keys are specified as a concatenated string:
- Single characters: `wasd` = W, A, S, D keys
- Space character: ` ` (literal space in string)
- Special keys: `{NAME}` syntax
- Shifted symbols: a shifted glyph targets its base key, so `!@#` = the `1` `2` `3`
  keys, `?` = `/`, `:` = `;`, and so on
- Escape sequences: `\b` = Backspace, `\n` or `\r` = Enter, `\x1b` = Escape

### Available Keys

**Letters:** A-Z (use uppercase in `{NAME}` format or lowercase as single chars)

**Numbers:** 0-9

**Punctuation:** `` ` `` `-` `=` `[` `]` `\` `;` `'` `,` `.` `/`

**Special Keys:**
| Key Name | Description |
|----------|-------------|
| `{SPACE}` | Space bar |
| `{BACKSPACE}` | Backspace |
| `{ENTER}` | Enter/Return |
| `{ESC}` | Escape |
| `{UP}` | Up arrow |
| `{DOWN}` | Down arrow |
| `{LEFT}` | Left arrow |
| `{RIGHT}` | Right arrow |
| `{LSHIFT}` | Left Shift |
| `{RSHIFT}` | Right Shift |
| `{SHIFT}` | Both Shift keys (expands to `LSHIFT` + `RSHIFT`) |

**Note:** This keyboard configuration has a limited key set. Function keys, numpad, and other keys are not currently mapped.

## Color Schemes

Schemes define alternate color configurations, activated at runtime via `Keyboard.Scheme = Keyboard.Schemes.<NAME>`, where `<NAME>` is any scheme declared in the JSON below (the `disabled` scheme, for instance, is `Keyboard.Schemes.DISABLED`).

```json
"schemes": {
  "disabled": {
    "background": "#000000"
  },
  "gaming": {
    "background": "#100000",
    "custom": {
      "keys": "wasd {SPACE}",
      "color": "#FF0000"
    }
  }
}
```

Each scheme can override any top-level property. Unspecified properties inherit from the base configuration.

## Color Specification

Colors are hex strings in `#RRGGBB` format:

```json
"alpha": "#00FF00"
```

## Examples

### Basic Configuration

```json
{
  "name": "Keyboard",
  "background": "#000020",
  "meta": "#404040",
  "alpha": "#00FF00",
  "numeric": "#0080FF",
  "punctuation": "#FFFF00"
}
```

### Gaming Mode with WASD Highlight

```json
{
  "name": "Keyboard",
  "background": "#000010",
  "alpha": "#004000",
  "custom": {
    "keys": "wasd",
    "color": "#00FF00"
  },
  "schemes": {
    "gaming": {
      "background": "#100000",
      "custom": {
        "keys": "wasd {SPACE}{LSHIFT}",
        "color": "#FF0000"
      }
    }
  }
}
```

### Text Entry vs Numeric Mode

```json
{
  "name": "Keyboard",
  "background": "#001020",
  "schemes": {
    "text": {
      "alpha": "#00FF00",
      "punctuation": "#FFFF00"
    },
    "numeric": {
      "background": "#000000",
      "numeric": "#00FF00",
      "custom": {
        "keys": ".-",
        "color": "#FFFF00"
      }
    }
  }
}
```

## See Also

- `configs/Keyboard.json`: Default keyboard configuration
- `enigma/boards/gpro.py`: GPRO board handler implementation
