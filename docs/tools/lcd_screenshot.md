# lcd_screenshot

## Name

`lcd_screenshot.py` - capture the LCD through OpenOCD and save a PNG.

## Contents

- [Synopsis](#synopsis)
- [Description](#description)
- [Arguments](#arguments)
- [Options](#options)
- [Examples](#examples)
- [See Also](#see-also)

## Synopsis

```
lcd_screenshot.py [OUTPUT] [OPTIONS]
```

## Description

Reads LCD display memory through an existing OpenOCD Tcl RPC connection.
Selects the Air 10 or Air11 backend automatically from the MCU identification.
Requires an initialized display and ImageMagick `convert`. The client and
OpenOCD server must have access to the same absolute file paths.

Capture halts the processor and resumes it after a successful readout; use it
with therapy stopped. A capture error leaves the processor halted. Capture
replaces the LCD address window and can interrupt an in-progress drawing
operation, so the display may need a redraw after resuming.

Air 10 applies the existing panel color correction. Air11 converts the native
RGB565 values to RGB888 without that correction and produces a 320 x 240 image.
Air11 capture updates one progress line in a terminal; redirected output omits
progress updates. Each batch restores the LCD command/data pin before
returning to the client.

On a capture timeout, OpenOCD may still be processing the current batch. The
client retains the partial PPM and prints its path. Wait for OpenOCD to finish
before issuing another capture or `reset run`.

## Arguments

| Argument | Meaning |
|----------|---------|
| `OUTPUT` | PNG output path; default `lcd.png`. Parent directory must exist. |

## Options

| Option | Meaning |
|--------|---------|
| `--host HOST` | OpenOCD Tcl RPC host; default `127.0.0.1` |
| `--port PORT` | OpenOCD Tcl RPC port; default `6666` |
| `--timeout SECONDS` | Wait for an OpenOCD reply; default `30`. For Air11, applies separately to each eight-row batch. |
| `--controller {auto,ili9341,ili932x}` | Air 10 controller selection; default `auto` |
| `--tcl PATH` | Override the platform's Tcl backend |

## Examples

Start OpenOCD for Air11:

```
./run-ocd.sh as11
```

In another terminal:

```
lcd_screenshot.py lcd.png
```

## See Also

- [Air11 OpenOCD](../guide/as11/openocd.md)
- [Air 10 OpenOCD](../guide/openocd.md)
