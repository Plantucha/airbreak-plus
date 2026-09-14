# eeprom_tool / eeprom_stub

## Name

`eeprom_tool.py` - read and write the Air 10 SPI EEPROM through `eeprom_stub`.

## Contents

- [Synopsis](#synopsis)
- [Description](#description)
- [Options](#options)
- [Connection](#connection)
- [Commands](#commands)
  - [ping](#ping)
  - [read](#read)
  - [write](#write)
  - [patch](#patch)
  - [erase](#erase)
  - [fixcrc](#fixcrc)
  - [reset](#reset)
  - [FAT filesystem](#fat-filesystem)
- [EEPROM layout](#eeprom-layout)
- [Binary protocol](#binary-protocol)
- [Files](#files)
- [Output](#output)
- [Exit Status](#exit-status)
- [Examples](#examples)
- [See Also](#see-also)

## Synopsis

```text
eeprom_tool.py -p PORT [--baud BAUD] COMMAND [ARGUMENTS]
eeprom_tool.py FAT_COMMAND --file DUMP [ARGUMENTS]
```

## Description

Reads complete EEPROM images or byte ranges, writes and patches stored data,
erases the EEPROM, and repairs its header CRC. Lists, extracts, and replaces
files in the embedded FAT filesystem, both on the device and in saved dumps.

## Options

| Option | Meaning | Default |
|--------|---------|---------|
| `-p`, `--port PORT` | Serial port; required for live commands | None |
| `--baud BAUD` | Transfer baud rate | Auto-negotiate |
| `-h`, `--help` | Show help | -- |

`BAUD` is a decimal baud rate. Automatic negotiation tries `2000000`,
`1000000`, `460800`, `115200`, and `57600`. The stub also accepts explicit
`9600`, `19200`, `38400`, `230400`, and `921600`.

## Connection

Live access uses `eeprom_stub`, a bare-metal replacement for the CDX region
with a USART3 interface. It implements `BID`, `BLS`, `SID`, `RES`, and `BLL`
so [resmed_flash](resmed_flash.md) can replace it with normal firmware.

## Commands

### ping

```text
ping
```

Report the stub version.

```sh
eeprom_tool.py -p /dev/ttyACM0 ping
```

### read

```text
read FILE [ADDRESS LENGTH]
```

Write raw EEPROM bytes to the host path `FILE`; `-` selects stdout.
`ADDRESS` is the zero-based byte offset and `LENGTH` is the byte count. Supply
both to select a range; the default is all `0x40000` bytes from address `0`.
Numeric arguments accept `0x` prefixes.

```sh
eeprom_tool.py -p /dev/ttyACM0 read dump.bin
eeprom_tool.py -p /dev/ttyACM0 read part.bin 0x10 0x100
```

### write

```text
write FILE
```

Write the full 256 KiB EEPROM image from host file `FILE`.

```sh
eeprom_tool.py -p /dev/ttyACM0 write image.bin
```

### patch

```text
patch ADDRESS HEX
```

Write the hexadecimal byte string `HEX` at the zero-based EEPROM byte
`ADDRESS`.

```sh
eeprom_tool.py -p /dev/ttyACM0 patch 0x120 01ABFF
```

### erase

```text
erase
```

Erase the entire EEPROM, filling it with `0xFF`.

```sh
eeprom_tool.py -p /dev/ttyACM0 erase
```

### fixcrc

```text
fixcrc
```

Recalculate and write the EEPROM header CRC.

```sh
eeprom_tool.py -p /dev/ttyACM0 fixcrc
```

### reset

```text
reset
```

Reset the MCU through the stub.

```sh
eeprom_tool.py -p /dev/ttyACM0 reset
```

### FAT filesystem

```text
fat-ls [PATH] [--file DUMP]
fat-get FAT_PATH FILE [--file DUMP]
fat-getdir FAT_PATH DIRECTORY [--file DUMP]
fat-put FILE FAT_PATH [--file DUMP] [--fixsum]
```

List, extract, or replace files in the EEPROM FAT12 filesystem; requires
`pyfatfs`.

| Option | Commands | Meaning | Default |
|--------|----------|---------|---------|
| `--file DUMP` | All `fat-*` | Operate on a raw EEPROM dump | Live device |
| `--fixsum` | `fat-put` | Repair the input settings-file checksum | Off |

`PATH` and `FAT_PATH` are filesystem paths; `FILE` and `DIRECTORY` are host
paths. `fat-put --file` modifies the dump in place.

| Command | Operation |
|---------|-----------|
| `fat-ls` | List a directory; default path `/` |
| `fat-get` | Extract a file; `FILE=-` writes to stdout |
| `fat-getdir` | Extract a directory tree |
| `fat-put` | Write one file; `FILE=-` reads from stdin |

```sh
eeprom_tool.py fat-get /SETTINGS/BGL.set out.bin --file dump.bin
eeprom_tool.py -p /dev/ttyACM0 fat-put in.bin /SETTINGS/BGL.set --fixsum
```

## EEPROM layout

M95M02 SPI EEPROM, 256 KiB.

| Region | Offset | Content |
|--------|--------|---------|
| Header | 0x00-0x51 | EEPROM header |
| FAT12 | 0x200+ | Filesystem with DATALOG, ERRORLOG, SESSION, SETTINGS |

## Binary protocol

Frame format:

```text
[0x55] [CMD] [LEN:2 BE] [payload] [CRC16:2 BE]
```

CRC-16/CCITT-FALSE over CMD+LEN+payload. Payload integers are big-endian;
the sizes below are byte counts. Responses use the same frame layout, with
`ACK=0x41`, `NACK=0x4E`, or `DATA=0x44` in place of `CMD`.

| CMD | Name | Payload | Response |
|-----|------|---------|----------|
| 0x01 | Ping | -- | DATA: version string |
| 0x02 | Read | addr:3, len:3 | ACK + streaming data + CRC |
| 0x03 | Write | addr:3, data:N | ACK or NACK |
| 0x04 | Erase | -- | ACK |
| 0x05 | Fix CRC | -- | DATA: old_crc:2, new_crc:2 |
| 0x06 | Set baud | baud:4 | ACK at the previous baud rate |
| 0x07 | Reset | -- | ACK, then system reset |
| 0x08 | Bulk write | addr:3, count:2 | ACK, then per-page streaming |

`Read` acknowledges the requested length as a three-byte integer, then sends
the raw data followed by its CRC16. `Write` accepts up to 256 bytes within
one EEPROM page. `Bulk write` takes a page-aligned address and a page count;
each streamed page contains 256 bytes plus CRC16, followed by a single-byte
`0x06` acknowledgement. Bulk errors use `0x10` (CRC) or `0x11` (write verify).

## Files

| File | Use |
|------|-----|
| `eeprom_stub_nocrc.bin` | Stub for a patched bootloader with CRC bypass |
| `eeprom_stub_full.bin` | 768 KiB stub image, padded with CRC for a stock bootloader |
| `--file DUMP` | Raw EEPROM image; `fat-put` modifies it in place |

## Output

`ping` and `fat-ls` print text to stdout. Reads and extracts write binary files.
Transfer progress and CRC reports go to stderr.

## Exit Status

`0` on normal completion; `2` for invalid command-line syntax. Unhandled
connection, protocol, and file errors terminate with a nonzero status.

## Examples

Install the stock-bootloader stub, dump EEPROM, then restore normal firmware:

```sh
resmed_flash.py -p /dev/ttyACM0 -f eeprom_stub_full.bin --block cdx
eeprom_tool.py -p /dev/ttyACM0 read dump.bin
resmed_flash.py -p /dev/ttyACM0 -f stm32.bin
```

Extract the settings directory from the captured dump:

```sh
eeprom_tool.py fat-ls / --file dump.bin
eeprom_tool.py fat-getdir /SETTINGS ./backup/ --file dump.bin
```

## See Also

[resmed_flash](resmed_flash.md), [resmed_config](resmed_config.md).
