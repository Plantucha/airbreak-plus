# airmini_descriptors

## Name

`airmini_descriptors.py` - inspect and edit AirMini CONF descriptors offline.

## Contents

- [Synopsis](#synopsis)
- [Description](#description)
- [Arguments](#arguments)
- [Options](#options)
- [Commands](#commands)
  - [info](#info)
  - [var](#var)
  - [vars](#vars)
  - [var-options](#var-options)
  - [edit](#edit)
  - [mode](#mode)
  - [data-rules](#data-rules)
  - [globals / conf-layout](#globals--conf-layout)
  - [events / event-payload-types](#events--event-payload-types)
  - [collections](#collections)
  - [storage-sets](#storage-sets)
  - [dump-tsv](#dump-tsv)
- [Interactive Mode](#interactive-mode)
- [Output](#output)
- [Exit Status](#exit-status)
- [Examples](#examples)
- [See Also](#see-also)

## Synopsis

```text
airmini_descriptors.py FIRMWARE [OPTIONS] [COMMAND [ARGUMENTS] [OPTIONS]]
airmini_descriptors.py FIRMWARE [OPTIONS] -i
```

## Description

Decodes CONF structures, variable descriptors, enum options, event payloads,
periodic collections, EEPROM storage groups, PDL members, and RPC node schemas.
Resolves variable IDs, short tags, and long names, and connects descriptors to
APPL DataItem rules.

Edits defaults, numeric limits, steps, scaling, flags, and enum permissions.
Validates changes and updates the CONF checksum when writing the modified
firmware image.

Requires Python 3.10 or newer; uses only the standard library.

## Arguments

`FIRMWARE`: full 1 MiB raw firmware image to inspect or edit.

Supported layout: `Airmini-SW03900.01.4.0.3.50927.bin`. The tool checks the
platform, application version, globals getter, root addresses, and factory
signature. Other layouts are rejected.

Bare numeric arguments are decimal; `0x` denotes hexadecimal.

## Options

Global options precede the command. Command-specific options follow the command.

| Option | Meaning | Default |
|--------|---------|---------|
| `-i`, `--interactive` | Start the interactive shell | Off |
| `--ignore-input-crc` | Accept an invalid input CONF CRC | Off |
| `-h`, `--help` | Show global or command-specific help | -- |

The CRC override prints a warning. Layout and descriptor validation remain
active. The tool checks the CONF CRC, not other component checksums.

## Commands

The default command is `info`.

### info

```text
info [--raw]
```

Show firmware and component identifiers, enabled therapy modes, and the
default language configuration. Language names are unavailable in the firmware
enum table; the summary reports numeric language indices.

| Option | Meaning | Default |
|--------|---------|---------|
| `--raw` | Machine-readable identity, SHA-256, descriptor counts, and CONF CRC | Off |

```sh
airmini_descriptors.py firmware.bin info
airmini_descriptors.py firmware.bin info --raw
```

### var

```text
var VAR ... [--verbose] [--raw]
```

Show one or more variable descriptors. Each `VAR` is a numeric variable ID,
long name, short tag, or underscored short tag. Names are case-insensitive;
results follow the input order.

| Option | Meaning | Default |
|--------|---------|---------|
| `--verbose` | Multi-line details, raw bytes, editable fields, and enum options | Off |
| `--raw` | Append raw descriptor bytes to compact output | Off |

```sh
airmini_descriptors.py firmware.bin var 0x00ff _MOP CPAP-SetPressure
airmini_descriptors.py firmware.bin var TherapyMode --verbose
```

### vars

```text
vars [--array ARRAY] [--name REGEX] [--verbose] [--raw]
```

List descriptor records from the selected arrays. The supported image contains
332 DataItems, 327 short tags, and 332 long names.

| Option | Meaning | Default |
|--------|---------|---------|
| `--array ARRAY` | `g1`, `g2`, `g3`, `g5`, `g6`, `g7`, `g8`, `g9`, `g10`, or `all` | `all` |
| `--name REGEX` | Case-insensitive filter over combined short and long names | No filter |
| `--verbose` | Multi-line descriptor details | Off |
| `--raw` | Append raw descriptor bytes | Off |

```sh
airmini_descriptors.py firmware.bin vars --array g5
airmini_descriptors.py firmware.bin vars --name Ramp
```

### var-options

```text
var-options VAR [--verbose]
```

Show all option slots for an enum descriptor from `g5`. `VAR` accepts the
same identifiers as `var`. Output includes the option index, enabled/default
state, and firmware enum symbol; missing symbols appear as `n/a`.

`idx` identifies the g5 descriptor; `opt` is the option value. For `LAN`,
`enabled` checks both the descriptor option mask and the configured `LNC` mask.
The descriptor's `enabled_options` field lists only the option-mask bits.

| Option | Meaning | Default |
|--------|---------|---------|
| `--verbose` | Multi-line enum details | Off |

```sh
airmini_descriptors.py firmware.bin var-options MOP
airmini_descriptors.py firmware.bin var-options LAN --verbose
```

### edit

```text
edit VAR.FIELD=VALUE ... [OPTIONS]
```

Edit one or more CONF descriptor fields and write a new firmware image.

`VAR` accepts the same identifiers as `var`. The command validates the input
CONF CRC and assignments, updates the CRC, and reparses the result to verify
stored values before writing. The input image is never overwritten, including
through a link alias or with `--overwrite`.

| Option | Meaning | Default |
|--------|---------|---------|
| `-o`, `--output FILE` | Output image; required unless `--dry-run` | None |
| `--dry-run` | Validate and preview changes | Off |
| `--overwrite` | Replace an existing output file | Off |
| `--ignore-input-crc` | Accept an invalid input CONF CRC | Off |

Editable fields:

| Arrays | Fields |
|--------|--------|
| `g1`, `g2`, `g3`, `g5`, `g6`, `g8`, `g9` | `flags`, `data_rule`, `linked_counter`, `event_queue` |
| `g1` | `buffer_capacity` |
| `g2`, `g6` | `default`, `min`, `max`, `step`, their `_raw` forms, `scale`, `decimal_places` |
| `g3` | `default_mask`, `editable_mask` |
| `g5` | `default_option`, `option_mask` |

Numeric fields `default`, `min`, `max`, and `step` use display scaling;
fields with a `_raw` suffix use raw integers. For example, `IPC.default=10`
stores 500 at scale 50, as does `IPC.default_raw=500`.

If `scale` and a scaled field are changed in one command, the scaled field
uses the new scale. Values must be exactly representable. Scaled edits require
a positive scale; edited steps must be nonnegative. Numeric defaults must fit
the bounds, and enum defaults must fit the option count.

Flags accept a numeric mask or a quoted symbolic expression such as
`MOP.flags='ACT|VIS|MOD|RPC'`. `data_rule` accepts 0..9; `event_queue` accepts
0..14, where 14 means no queue. `linked_counter` is a g2 index; `0x7fff` means
no link. Field names are case-insensitive. Duplicate assignments to the same
storage field are rejected.

Accepted aliases:

| Field | Aliases |
|-------|---------|
| `data_rule` | `data_rule_id` |
| `linked_counter` | `linked_counter_index` |
| `event_queue` | `change_event_queue_index` |
| `buffer_capacity` | `max_len`, `max_length` |
| g3 `default_mask` | `default` |
| g3 `editable_mask` | `editable`, `option_mask` |
| `default_option` | `default_opt` |
| g5 `option_mask` | `mask` |

Group membership, table counts/pointers, string contents, numeric-array element
counts, profile policies, and APPL code are not editable.

```sh
airmini_descriptors.py firmware.bin edit RMT.default=15 --dry-run
airmini_descriptors.py firmware.bin edit RMT.default=15 -o edited.bin
```

### mode

```text
mode [MODE]
```

List known therapy modes by default. `MODE` selects a numeric index or
case-insensitive name and lists variables in that mode's long-name namespace.

`name_scoped_variables` and `total_variables` count those variables.
`baseline_variables=n/a` indicates that baseline visibility is unknown.

Known mode indices from the firmware enum-symbol table:

| Index | Mode |
|-------|------|
| `0` | CPAP |
| `1` | AutoSet |
| `11` | HerAuto |

```sh
airmini_descriptors.py firmware.bin mode CPAP
airmini_descriptors.py firmware.bin mode 0xb
```

### data-rules

```text
data-rules [RULE ...]
```

List the APPL DataItem callbacks and the CONF descriptors that use each rule.
Each `RULE` selects a numeric ID in 1..9; the default is all rules. ID 0 means
no callback and is not listed.

`callback` is the normalized Thumb code address. `registration=pointer_table`
identifies the static registry; `source_off` is the file offset of the pointer
entry. `use_count` and `vars` identify the rule's descriptor users.

```sh
airmini_descriptors.py firmware.bin data-rules 3 5
```

### globals / conf-layout

```text
globals [INDEX] [--verbose] [--raw]
conf-layout
```

`globals` lists the 17 CONF roots. `INDEX` selects one numeric globals entry
to decode. `conf-layout` lists root objects in file-offset order, with flash
addresses and decoded sizes. Root sizes exclude referenced objects; the g4
span includes two trailing alignment bytes.

| Option | Command | Meaning | Default |
|--------|---------|---------|---------|
| `--verbose` | `globals` | Detailed table fields; for index 16, include APPL object schemas | Off |
| `--raw` | `globals` | Raw record bytes, or short root previews when INDEX is omitted | Off |

Each index is decoded according to its CONF structure:

| Index | Decoder |
|-------|---------|
| `0` | CONF header |
| `1`, `2`, `3`, `5` | volatile-text, numeric, bitfield, and enum descriptors |
| `4` | bitfield selection-order lists |
| `6` | numeric-array descriptor |
| `7` | EEPROM SettingsGroup members |
| `8`, `9` | date and time descriptors |
| `10` | PDL snapshot members |
| `11` | 21 identity-related IDs; logical list count unknown |
| `12` | short-name bucket entries |
| `13` | event spool definitions |
| `14` | EventNotification payload overrides |
| `15` | periodic collections |
| `16` | RPC node availability |

`globals 16` reports one `enabled` byte per node. With `--verbose`, it also
shows `field_count`, `fields`, and `source_address` from the APPL object schema.

```sh
airmini_descriptors.py firmware.bin globals 5
airmini_descriptors.py firmware.bin globals 16 --verbose
airmini_descriptors.py firmware.bin conf-layout
```

### events / event-payload-types

```text
events [FILTER ...] [--verbose]
event-payload-types [FILTER ...]
```

`events` lists event spools from g13. `event-payload-types` lists the per-event
EventNotification JSON payload overrides from g14, joined to event codes and
names.

Each `FILTER` is a case-insensitive substring of a code or name; rows matching
any filter are included. The default is all rows.

| Option | Command | Meaning | Default |
|--------|---------|---------|---------|
| `--verbose` | `events` | Multi-line event details | Off |

```sh
airmini_descriptors.py firmware.bin events Respiratory
airmini_descriptors.py firmware.bin event-payload-types Bluetooth
```

### collections

```text
collections [TAG ...] [--verbose]
```

List periodic collections from g15: `NRF`, `CLI`, `PSD`, and `HRF`.
Each `TAG` selects a complete collection tag, case-insensitively; a leading
`&` is accepted. The default is all collections.

Each signal row includes the source DataItem and its logged-data `data_id`.

| Option | Meaning | Default |
|--------|---------|---------|
| `--verbose` | Add sampling interval, block duration, buffer size, retention hours, gate, and file-policy fields | Off |

```sh
airmini_descriptors.py firmware.bin collections NRF HRF
airmini_descriptors.py firmware.bin collections NRF --verbose
```

### storage-sets

```text
storage-sets [TAG ...] [--names-only] [--verbose]
```

List EEPROM SettingsGroup members and their g2 update counters from g7.
Each `TAG` selects a complete set tag, case-insensitively; a leading `&` is
accepted. The default is all sets.

| Option | Meaning | Default |
|--------|---------|---------|
| `--names-only` | One row per set: member names, count, and update counter | Off |
| `--verbose` | Add path, policy byte, and aggregate-counter flag to member rows | Off |

`--names-only` selects the summary view even when `--verbose` is supplied.
Storage layout is described in the
[SettingsGroup reference](../airmini/conf_block_format.md#g7----eeprom-settingsgroup-schemas).

```sh
airmini_descriptors.py firmware.bin storage-sets BGL DID --names-only
```

### dump-tsv

```text
dump-tsv FILE [--array ARRAY] [--name REGEX]
```

Export descriptors to `FILE` (`-` for stdout), including resolved names and
raw bytes. Array selection and name filtering work as in `vars`.

| Option | Meaning | Default |
|--------|---------|---------|
| `--array ARRAY` | Descriptor array or `all`; same choices as `vars` | `all` |
| `--name REGEX` | Case-insensitive filter over combined short and long names | No filter |

Existing output files are never replaced. Fields that do not apply to a record
are empty. An empty selection produces a header.

```sh
airmini_descriptors.py firmware.bin dump-tsv descriptors.tsv
airmini_descriptors.py firmware.bin dump-tsv - --array g5
```

## Interactive Mode

`-i` keeps the firmware image loaded across queries.

Shell commands use the syntax above without the firmware path. `help` lists
commands; `help COMMAND` shows command-specific help. `quit`, `exit`, or `q`
closes the shell. Errors return to the prompt.

`edit` writes a separate image; subsequent queries still use the originally
loaded image.

```sh
airmini_descriptors.py firmware.bin -i
```

## Output

Most listings emit one record per line with `key=value` fields separated by `|`.
`var`, `vars`, `var-options`, and `events` provide multi-line details with
`--verbose`; `collections --verbose` extends the signal rows.

```text
array=g5|idx=0|off=0x022208|addr=0x08022208|var=0x00FF|short=MOP|long=TherapyMode|flags=0x0207|flag_names=ACT,VIS,MOD,RPC|linked_counter=0x0079|event_queue=0x0E|data_rule=0x05|default_option=1|option_count=12|option_mask=0x00000803|enabled_options=0,1,11|reserved=0x0000
```

`off` is a firmware file offset; `addr` is a flash address. Booleans use `0`/`1`,
lists use commas, and missing values use `n/a`. String backslashes, pipes,
newlines, and carriage returns are escaped as `\\`, `\|`, `\n`, and `\r`.
Raw bytes are hexadecimal.

`flag_names` uses `ACT`, `VIS`, `MOD`, `SGN`, `INH`, `VAL`, `ULK`, `RAW`, `MON`,
`RPC`, and `RPW`; see the [CONF flags field](../airmini/conf_block_format.md#flags-field).
Numeric `default`, `min`, `max`, and `step` are display values; `_raw` fields
are stored integers. A zero scale displays raw values.

`edit` reports changed fields, the resulting CONF CRC, and the output path or
dry-run status. `dump-tsv` writes TSV to its output path or stdout (`-`).
Errors and CRC warnings go to stderr.

## Exit Status

| Status | Meaning |
|--------|---------|
| `0` | Successful command or interactive shell exit |
| `1` | Image, lookup, edit, or file error |
| `2` | Invalid command-line syntax |

## Examples

Inspect a default, edit it, and inspect the resulting image:

```sh
airmini_descriptors.py firmware.bin var RMT
airmini_descriptors.py firmware.bin edit RMT.default=15 -o edited.bin
airmini_descriptors.py edited.bin var RMT
```

Inspect an image with an invalid CONF CRC:

```sh
airmini_descriptors.py firmware.bin --ignore-input-crc info --raw
```

## See Also

[CONF block format](../airmini/conf_block_format.md),
[as11_descriptors](as11_descriptors.md), [resmed_image](resmed_image.md).
