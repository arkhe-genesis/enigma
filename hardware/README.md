# Enigma Hardware

PCB designs for the Enigma boards. Each board lives in its own directory.

> [!NOTE]
> All board implementations are designed around the ESP32S3-N8R8 found at https://www.amazon.com/dp/B0CGYXJB6Y. Not because they
> need anything to do with WiFi/Bluetooth, but because I have roughly one
> million of them. They're my Swiss army knife of microcontrollers.  These
> boards would doubtlessly be cheaper on a smaller microcontroller. In the
> case of the QD04, it constrains quadrature edge interrupts to one core
> and addressable LED serialization + USB interfacing to the other.

## License

Everything under `hardware/` is licensed under the **CERN Open Hardware Licence
Version 2 - Strongly Reciprocal (CERN-OHL-S-2.0)**. See [`LICENSE`](LICENSE) in this
directory (full text) and [`../LICENSES/CERN-OHL-S-2.0.txt`](../LICENSES/CERN-OHL-S-2.0.txt).

In brief: you may use, study, modify, manufacture, and distribute these designs,
but if you distribute a modified design (or a product made from one) you must
make your modified design Source available under the same licence.

## What "Source" means here

CERN-OHL-S requires the *preferred form for making modifications* to be
available, not just fabrication outputs. Each board directory ships:

```
<board>/
  <board>_easyeda.epro2    editable EasyEDA Pro project (the "Source")
  <board>_gerber.zip       fabrication output (Gerber + drill), ready to order (I used JLCPCB)
  <board>_bom.csv          bill of materials (grouped; MPN + LCSC part numbers)
  <board>_schematic*.png   rendered schematic (for quick viewing, not editing)
  <board>_pcb.png          rendered board layout (for viewing)
  <board>_3d.png           3D render (for viewing)
  README.md                board notes
```

The `.epro2` is the source: open it in [EasyEDA Pro](https://easyeda.com) (free)
to read or modify the schematic and PCB. The gerber zip is the compiled output
(like a binary): it lets you fabricate directly at JLCPCB or any board house
without opening the design. The PNGs are convenience renders only.

Some boards also ship mechanical source: `.stl` 3D-print models (the SW14 switch
mounts and brackets) and `.lbrn2` LightBurn laser-cut files (the QD04 dial).

## The Enigma board family

The Enigma protocol defines a family of addressable input and output boards. Each
board carries a config resistor that it reads on a dedicated ADC pin to
self-report its variant to the host, so the host knows what it's talking to
without any manual setup. Three input boards are built and ship in this repo as
PCB designs; the rest are planned.

### Input boards

| ID | Board | Name | Features | Status |
|----|-------|------|----------|--------|
| 01 | [SW14](sw14/) | Switch Bank | 14x SPST/DPST switch inputs, each with an RGB indicator | **Implemented** |
| 02 | UD08 | Up/Down Selector | 8x incremental up/down counters with a small LCD between them | Planned |
| 03 | [AN08](an08/) | Analog Input Bank | 8x analog inputs (10-bit) | **Implemented** |
| 04 | [QD04](qd04/) | Quadrature Input Bank | 4x quadrature inputs, each with an RGB indicator strip/ring | **Implemented** |
| 05 | - | (future expansion) | - | Reserved |

### Output boards

| ID | Board | Name | Features | Status |
|----|-------|------|----------|--------|
| 06 | SC16 | Servo Controller | 16x standard RC servo outputs (16-bit) | Planned |
| 07 | DC04 | Display Controller | 4x LCD displays (imagery via USB mass storage); linear / rotary / positional readout over 0-16 elements; 2x PWM DAC outputs, 0-500 mA | Planned |
| 08 | RL16 | Relay Output Controller | 16x relays; continuous or timed activation | Planned |
| 09 | LC04 | LED Controller | 4x WS2812 strings, up to 256 lamps each (3-channel) | Planned |
| 10 | AU04 | Audio Controller | 4x 2-channel audio outputs; any sample on any output simultaneously; per-channel volume; loop count | Planned |
| 11 | AC08 | Analog Controller | 8x analog outputs | Planned |
| 12 | MO04 | Motor Controller | 4x bidirectional PWM motor-bridge drivers | Planned |
| 13 | - | (future expansion) | - | Reserved |
| 14 | - | (future expansion) | - | Reserved |

### In this repository

The implemented family members ship here as complete designs:
[SW14](sw14/) &middot; [QD04](qd04/) &middot; [AN08](an08/)

Alongside the support boards used in the build:
- [LED Indicator](led_indicator/): standalone RGB LED indicator board for use in SW14 controls
- [QD04 Dial LED](qd04_dial_led_board/): LED hemicircle for a QD04 encoder dial 
- [Fused 5V Distro](power_fused_5v0_distro_board/) and [Panel Distro](power_panel_distro_board/): power distribution

## Third-party controls (not Enigma boards)

The Halcyon Dawn build also uses two off-the-shelf USB devices that are **not**
Enigma boards and have no design in this directory: a **Thrustmaster T16000M**
flight stick and a **Logitech G Pro** keyboard. They are supported by the library
only because the sim wanted to treat every input the same way: Enigma drives them
through the same control abstraction as its own boards, so game code reads a stick
axis or a key exactly the way it reads an SW14 switch. 

Their integration is documented alongside the Enigma boards, in
[THRUSTMASTER_CONFIG.md](../host/enigma/docs/THRUSTMASTER_CONFIG.md) and
[GPRO_CONFIG.md](../host/enigma/docs/GPRO_CONFIG.md). The same host-side handler
mechanism can wrap any commercial USB HID device (as it does the stick and
keyboard above), or drive an Enigma board you build yourself; see [Implementing a
new board handler](../host/enigma/docs/NEW_BOARD_HANDLER.md).
