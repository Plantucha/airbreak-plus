# resmed_image

## Name

`resmed_image.py` - inspect, extract, replace, and compose firmware blocks.

## Contents

- [Synopsis](#synopsis)
- [Description](#description)
- [Arguments](#arguments)
- [Commands](#commands)
  - [info](#info)
  - [extract](#extract)
  - [replace](#replace)
  - [compose](#compose)
- [Options](#options)
- [Validation](#validation)
- [Output](#output)
- [Exit Status](#exit-status)
- [Examples](#examples)
- [See Also](#see-also)

## Synopsis

```text
resmed_image.py info IMAGE
resmed_image.py extract IMAGE BLOCK_OPTIONS
resmed_image.py replace IMAGE OUTPUT BLOCK_OPTIONS
resmed_image.py compose OUTPUT BLOCK_OPTIONS
```

## Description

Identifies firmware images and blocks, checks their CRCs, extracts selected
blocks, replaces blocks in an existing image, and assembles complete images
from separate sources, entirely offline.

## Arguments

| Argument | Meaning |
|----------|---------|
| `IMAGE` | Input image or block for `info`; complete base image for `extract` and `replace` |
| `OUTPUT` | Complete output image |
| `BLOCK_OPTIONS` | One or more block-path options listed under each command |

Supported layouts:

| Platform | Full image | Blocks | Bootloader layout |
|----------|------------|--------|-------------------|
| Air 10 | 1 MiB | `BLX`, `CCX`, `CDX` | `SX577-0200`, `SX585-0200` |
| Air11 | 2 MiB | `FGBL`, `CONF`, `APPL` | `1.1.0.736edbdfd` |

## Commands

### info

```text
info IMAGE
```

Identify an image or standalone block and check its CRCs.

Complete-image output includes the bootloader ID and each block's offset,
size, and stored CRC. Standalone blocks are identified by size and content
and checked independently.

```sh
resmed_image.py info firmware.bin
```

### extract

```text
extract IMAGE BLOCK_OPTIONS
```

Extract selected blocks from complete `IMAGE`, checking each block's CRC
before writing.

| Option | Output paths |
|--------|----------------|
| `--blx PATH`, `--ccx PATH`, `--cdx PATH` | Air 10 blocks |
| `--fgbl PATH`, `--conf PATH`, `--appl PATH` | Air11 blocks |

At least one block must be selected.

```sh
resmed_image.py extract firmware.bin --blx bootloader.bin --cdx application.bin
resmed_image.py extract air11.bin --fgbl bootloader.bin \
    --conf configuration.bin --appl application.bin
```

### replace

```text
replace IMAGE OUTPUT BLOCK_OPTIONS
```

Copy complete `IMAGE` to `OUTPUT` with the selected blocks replaced.

| Option | Block sources |
|--------|----------------|
| `--blx PATH`, `--ccx PATH`, `--cdx PATH` | Air 10 blocks |
| `--fgbl PATH`, `--conf PATH`, `--appl PATH` | Air11 blocks |

Sources accept complete images or standalone blocks of the expected size.
All selected blocks must belong to the same platform.

```sh
resmed_image.py replace base.bin output.bin --ccx donor.bin --cdx donor.bin
resmed_image.py replace air11.bin output.bin --conf configuration.bin
```

### compose

```text
compose OUTPUT BLOCK_OPTIONS
```

Assemble all three blocks for one platform into `OUTPUT`.

| Option | Block sources |
|--------|----------------|
| `--blx PATH`, `--ccx PATH`, `--cdx PATH` | Air 10 blocks |
| `--fgbl PATH`, `--conf PATH`, `--appl PATH` | Air11 blocks |

BLX or FGBL selects the layout; Air 10 and Air11 options cannot be mixed.
Sources accept complete images or standalone blocks of the expected size.

```sh
resmed_image.py compose output.bin \
    --blx bootloader.bin --ccx config.bin --cdx application.bin
resmed_image.py compose air11.bin \
    --fgbl bootloader.bin --conf configuration.bin --appl application.bin
```

## Options

`-h`, `--help` shows global or command-specific help.

## Validation

Block operations require:

- supported bootloader IDs matching the selected layout
- block sizes matching that layout
- valid block CRCs
- a CDX for the selected platform family
- matching software versions when CCX and CDX come from full images

## Output

`info` prints image identity and block CRC results. Other commands write binary
files to the supplied paths and print operation summaries. Existing output files
are replaced automatically. Errors go to stderr.

## Exit Status

| Status | Meaning |
|--------|---------|
| `0` | Successful operation; all reported CRCs valid for `info` |
| `1` | Invalid image, CRC failure, or file error |
| `2` | Invalid command-line syntax |

## Examples

Extract a bootloader, replace it in another image, and inspect the result:

```sh
resmed_image.py extract reference.bin --blx bootloader.bin
resmed_image.py replace base.bin output.bin --blx bootloader.bin
resmed_image.py info output.bin
```

## See Also

[resmed_flash](resmed_flash.md), [as11_flash](as11_flash.md),
[Air 10 serial dump guide](../guide/serial_dump.md),
[Air11 service dump guide](../guide/as11/service_dump.md).
