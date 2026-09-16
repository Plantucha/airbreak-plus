# s9_descriptors

## Name

`s9_descriptors.py` - inspect and edit S9 CCX descriptors offline.

## Contents

- [Synopsis](#synopsis)
- [Description](#description)
- [Arguments](#arguments)
- [Options](#options)
- [Commands](#commands)
  - [info](#info)
  - [var](#var)
  - [vars](#vars)
  - [search](#search)
  - [table](#table)
  - [layout / globals](#layout--globals)
  - [var-options](#var-options)
  - [mode](#mode)
  - [chain](#chain)
  - [refs](#refs)
  - [callbacks](#callbacks)
  - [channels](#channels)
  - [collections](#collections)
  - [storage-sets](#storage-sets)
  - [logs](#logs)
  - [events](#events)
  - [edf-streams](#edf-streams)
  - [edf-str](#edf-str)
  - [namespaces](#namespaces)
  - [name](#name)
  - [names](#names)
  - [text / strid](#text--strid)
  - [strinfo](#strinfo)
  - [raw-strid](#raw-strid)
  - [texts](#texts)
  - [text-search](#text-search)
  - [edit](#edit)
  - [dump-tsv](#dump-tsv)
  - [scan-dir](#scan-dir)
  - [compare](#compare)
  - [compare-names](#compare-names)
- [Interactive Mode](#interactive-mode)
- [Output](#output)
- [Exit Status](#exit-status)
- [Examples](#examples)
- [See Also](#see-also)

## Synopsis

```text
s9_descriptors.py FIRMWARE [OPTIONS] [COMMAND [ARGUMENTS]]
s9_descriptors.py FIRMWARE [OPTIONS] -i
s9_descriptors.py scan-dir PATH [PATH ...]
```

## Description

Decodes variable descriptors, dependencies, UART streams, recording and storage
layouts, STR fields, names, and localized text. Edits scalar descriptor metadata
and writes a separate firmware image with an updated CCX checksum.

Supports raw 1 MiB images with CDX versions SX474-0907, SX474-0912,
SX474-1201, SX474-1203, and SX474-1301. The navigator shares its firmware
parser and output writer with the S9 patcher.

The tool reads an image offline. It does not read current RAM values or execute
dependency callbacks. Use [s9_languages](s9_languages.md) to export translations
or rebuild a language set.

## Arguments

`FIRMWARE`: raw firmware image to inspect or edit.

`VAR`: case-insensitive UART tag, such as `MOP`, or numeric UART variable ID.
`var` and `edit` also accept the `_TAG` spelling. Numeric values are decimal
unless prefixed with `0x`.

Table row indexes, dependency selectors, UART IDs, localized text IDs, and raw
string IDs are separate namespaces. Use the argument type required by the
command; IDs can differ between firmware versions.

`LAN_ID`: numeric value of a `LAN` option, not a translation's position in the
image. Use `var-options LAN` to list values. An unavailable translation is an
error.

Examples assume the scripts in the repository's `python/` directory are on
`PATH`. The workspace launcher `s9/s9_descriptors.py` accepts the same arguments.

## Options

Global options precede the command. Every command also accepts `-v` and `-h`.

| Option | Meaning | Default |
|--------|---------|---------|
| `-i`, `--interactive` | Start the interactive shell; cannot be combined with a command | Off |
| `-v`, `--verbose` | Add descriptor details where available | Off |
| `-h`, `--help` | Show help; use `COMMAND --help` for command options | -- |

## Commands

The default command is `info`. Limits supplied with `--limit` must be
non-negative. Record listings with an optional `NAME` filter use a
case-insensitive substring of the UART name.

### info

```text
info
```

Show firmware identity, therapy modes, available languages, and variable count.
Use `layout` for table addresses and counts.

```sh
s9_descriptors.py firmware.bin info
```

### var

```text
var VAR [VAR ...] [--index | --selector] [--raw] [--text-base BASE]
```

Show descriptors in argument order, including defaults, bounds or option masks,
flags, labels, and dependency links. Supports scalar and record descriptors.

| Option | Meaning |
|--------|---------|
| `--index` | Interpret each argument as a setting-table row index |
| `--selector` | Find settings whose dependency-chain start index matches each argument |
| `--raw` | Append descriptor bytes |
| `--text-base BASE` | With `--index` or `--selector`, append raw text references resolved through a pointer table at file offset `BASE`; otherwise has no effect |

```sh
s9_descriptors.py firmware.bin var MOP LAN
s9_descriptors.py firmware.bin var IPC --verbose
s9_descriptors.py firmware.bin var 0 --index
```

### vars

```text
vars [TABLE] [QUERY ...] [--name QUERY] [--array TABLE] [--active] [--limit N]
```

List scalar descriptors. `TABLE` is `all` (default), `setting`, `numeric`,
`enum`, `bitfield`, `string`, `date`, or `time`. Positional words and `--name`
form a case-insensitive substring query over UART names and labels.

| Option | Meaning |
|--------|---------|
| `--array TABLE` | Select a scalar table instead of supplying positional `TABLE` |
| `--name QUERY` | Filter by UART name or label |
| `--active` | Include only descriptors with ACT set |
| `--limit N` | Maximum matching rows to print |

Do not combine positional `TABLE` with `--array`.

```sh
s9_descriptors.py firmware.bin vars setting --name Leak
```

### search

```text
search [QUERY ...] [--name QUERY] [--array TABLE] [--active] [--limit N]
```

Search scalar UART names, labels, option texts, and units. Query words are
joined into one case-insensitive substring; quote a query if it contains shell
metacharacters.

| Option | Meaning |
|--------|---------|
| `--name QUERY` | Append text to the query |
| `--array TABLE` | Restrict to `setting`, `numeric`, `enum`, `bitfield`, `string`, `date`, or `time` |
| `--active` | Include only descriptors with ACT set |
| `--limit N` | Maximum matching rows to print |

```sh
s9_descriptors.py firmware.bin search pressure --limit 10
```

### table

```text
table [TABLE] [--active] [--known] [--selector N] [--limit N] [--tsv]
```

List one named descriptor table; the default is `setting`. Use `layout` to
find table names in the input image.

| Option | Meaning |
|--------|---------|
| `--active` | Include only descriptors with ACT set |
| `--known` | Include only named setting rows |
| `--selector N`, `--var N` | Filter settings by dependency-chain start index |
| `--limit N` | Limit rows |
| `--tsv` | Write a table-specific TSV listing to stdout |

For non-setting tables, `--known` has no effect and `--selector` is rejected.
Their text listings apply `--limit` before `--active`; their TSV listings do
not apply these two filters. Setting TSV has a different schema from other
scalar tables. Use `dump-tsv` for a uniform, filtered scalar export; non-scalar
record tables do not support that export schema.

```sh
s9_descriptors.py firmware.bin table enum --limit 10
```

### layout / globals

```text
layout [TABLE[:INDEX[,END]] ...]
globals [TABLE[:INDEX[,END]] ...]
```

Show structural roots, addresses, strides, and counts without arguments.
`globals` is an alias. S9 selectors use named descriptor tables, such as
`setting`, `numeric`, `enum`, or `stream`.

| Selector | Meaning |
|----------|---------|
| `TABLE` | Decode all entries of a descriptor table |
| `TABLE:INDEX` | Decode one row by its table index |
| `TABLE:INDEX,END` | Decode rows from `INDEX` inclusive to `END` exclusive |

Auxiliary roots in the overview, such as the name resolver and text roots,
are inspected through their dedicated commands, not table selectors.

```sh
s9_descriptors.py firmware.bin layout
s9_descriptors.py firmware.bin globals numeric:0,10 enum:0,5
```

### var-options

```text
var-options VAR [--language LAN_ID]
```

List option values, their permission-mask status (`Y` or `N`), and labels.
`--language` selects the label language; the default is English (`0`).

```sh
s9_descriptors.py firmware.bin var-options LAN
```

### mode

```text
mode [MODE ...] [--rules]
```

Without `MODE`, list MOP values, labels, and permission-mask status. With a
numeric value or case-insensitive mode label, show settings referenced by
conditions for that mode. Multiword labels are accepted.

`--rules` prints the dependency conditions instead of the setting listing.
Without `MODE`, it prints all decoded mode conditions. Other conditions can
still apply; this command does not determine actual runtime menu visibility.

```sh
s9_descriptors.py firmware.bin mode
s9_descriptors.py firmware.bin mode CPAP --rules
```

### chain

```text
chain VAR
```

Walk outgoing setting dependencies. Each row includes its index, operation,
operand, target, and optional condition. Conditions are displayed as OR groups
of AND clauses with inclusive value intervals. Recognized callbacks include
their operation and code address; unknown operations retain numeric values.

The optional `when` expression is only one part of a dependency rule. A printed
`when true` does not remove source-value gating or imply that the operation
always runs. Callbacks are not executed.

```sh
s9_descriptors.py firmware.bin chain IPC
```

### refs

```text
refs VAR
```

Show incoming references from parsed dependencies, streams, storage, and STR
records, including the referring name, index, and address. This is a data
reference listing, not an executable-code cross-reference search.

```sh
s9_descriptors.py firmware.bin refs MOP
```

### callbacks

```text
callbacks
```

List unique dependency callback selectors and their code addresses, including
the Thumb pointer. Use `chain VAR` to inspect a setting's use of callbacks.

```sh
s9_descriptors.py firmware.bin callbacks
```

### channels

```text
channels [NAME]
```

List live UART stream descriptors and their fields. `NAME` filters stream names.

```sh
s9_descriptors.py firmware.bin channels
```

### collections

```text
collections [NAME]
```

List named field collections. `NAME` filters collection names.

```sh
s9_descriptors.py firmware.bin collections
```

### storage-sets

```text
storage-sets [NAME]
```

List persistent storage groups and their fields. `NAME` filters group names.

```sh
s9_descriptors.py firmware.bin storage-sets PDL
```

### logs

```text
logs [NAME]
```

List log, recorded-series, and recorded-event descriptors. `NAME` filters
record names.

```sh
s9_descriptors.py firmware.bin logs
```

### events

```text
events [NAME]
```

List EDF event records. `NAME` filters event-record names.

```sh
s9_descriptors.py firmware.bin events
```

### edf-streams

```text
edf-streams [NAME]
```

List periodic EDF streams and EDF event records. `NAME` filters record names.

```sh
s9_descriptors.py firmware.bin edf-streams
```

### edf-str

```text
edf-str [NAME]
```

List STR output fields with sample counts, calculation operations, source
variables, arguments, and flags. `NAME` filters output-variable names.

```sh
s9_descriptors.py firmware.bin edf-str
```

### namespaces

```text
namespaces
```

Count UART IDs by descriptor kind. Unresolved IDs are always listed;
`--verbose` lists every ID with its aliases. An unresolved entry means its
representation is not decoded, not that the firmware lacks the variable.

```sh
s9_descriptors.py firmware.bin namespaces --verbose
```

### name

```text
name IDENT [IDENT ...]
```

Resolve UART tags to IDs or IDs to tags, including aliases. A missing name or
ID is printed as `-` and does not make the command fail.

```sh
s9_descriptors.py firmware.bin name MOP LAN
```

### names

```text
names [--prefix PREFIX] [--contains TEXT] [--value UART_ID] [--limit N] [--tsv]
```

List entries in the UART name resolver, including entries without a decoded
descriptor.

| Option | Meaning |
|--------|---------|
| `--prefix PREFIX` | Match the beginning of a name |
| `--contains TEXT` | Match text within a name |
| `--value UART_ID` | Match an exact numeric UART ID |
| `--limit N` | Maximum matching entries to print |
| `--tsv` | Emit `name`, `value`, `entry_off`, and `descriptor` columns |

Name filters are case-insensitive and can be combined.

```sh
s9_descriptors.py firmware.bin names --prefix A --limit 10
```

### text / strid

```text
text TEXT_ID [TEXT_ID ...] [--language LAN_ID]
strid TEXT_ID [LAN_ID]
strid TEXT_ID [--language LAN_ID]
```

Resolve localized text IDs. Omit the language to show every available
translation. `strid` accepts one text ID and an optional positional language;
use `text` for multiple IDs.

```sh
s9_descriptors.py firmware.bin text 0 1 --language 0
s9_descriptors.py firmware.bin strid 0
```

### strinfo

```text
strinfo [TEXT_ID ...] [--language LAN_ID]
```

Show text-record metadata, the variant-array address, raw string IDs, pointers,
and translations. The default text ID is `0`. Omit `--language` to show all
available translations.

```sh
s9_descriptors.py firmware.bin strinfo 0
```

### raw-strid

```text
raw-strid STRING_ID [STRING_ID ...]
```

Read strings directly by raw string-table index. These are not localized text
IDs. The shared parser accepts `--language` here, but it has no effect.

```sh
s9_descriptors.py firmware.bin raw-strid 0
```

### texts

```text
texts [TEXT_ID ...] [--language LAN_ID] [--limit N]
texts [STRING_ID ...] --base BASE [--field FIELD]
```

List localized texts, or the supplied text IDs. The default language is
English (`0`); `--limit` caps the number of rows.

`--base` selects a raw string-pointer table by file offset and changes the arguments
to raw string IDs. Without IDs, it lists references collected from setting
fields. `--field` selects `all` (default), `text0`, `text1`, `text2`, or `extra`
for that collection. `--field` has no effect without `--base`; `--language` and
`--limit` have no effect with `--base`. Normal lookup needs no override.

```sh
s9_descriptors.py firmware.bin texts --language 0 --limit 10
```

### text-search

```text
text-search QUERY [--language LAN_ID]
```

Search localized text using a case-insensitive substring. Quote queries with
spaces. The default language is English (`0`).

```sh
s9_descriptors.py firmware.bin text-search "Leak Alert"
```

### edit

```text
edit VAR.FIELD=VALUE [VAR.FIELD=VALUE ...] [-o FILE] [--dry-run]
     [--overwrite] [--ignore-input-crc]
edit --fields VAR
```

Edit scalar descriptor fields. `--fields VAR` lists accepted field names,
storage types, and offsets for the selected variable; it cannot be combined
with assignments or an output file.

| Option | Meaning | Default |
|--------|---------|---------|
| `-o`, `--output FILE` | Write a separate firmware image | Required unless `--dry-run` |
| `--dry-run` | Validate the complete edit without writing an image | Off |
| `--overwrite` | Replace an existing output file | Off |
| `--ignore-input-crc` | Allow invalid input region CRCs | Off |

| Descriptor type | Editable fields |
|-----------------|-----------------|
| Numeric, including numeric settings | `default`, `min`, `max`, `flags`, `label`, `scale`, `unit` |
| Enum, bitfield, including option settings | `default`, `flags`, `label`, `mask`, `options_text` |
| String, date, time | `flags`, `label` |

`default`, `min`, and `max` use the descriptor's divisor. Append `_raw` to use
stored integers. Values must be finite and exactly representable. When editing
`scale` and values in one transaction, use `_raw` for those values. Flags accept
a numeric byte or names joined with `|`: `ACT`, `VIS`, `EDT`, `SGN`.

Assignments are checked for overlapping writes, storage width, text references,
option masks, and consistent final bounds/defaults. The command does not
allocate field lists, replace callbacks, or perform arbitrary byte writes.
`LAN.mask` is editable, but changing it does not rebuild translations; use
[s9_languages](s9_languages.md) when replacing a language set.

Input BLX, CCX, and CDX CRCs are checked. Output updates the CCX CRC; BLX and
CDX remain unchanged. `--ignore-input-crc` does not repair unchanged regions.
The output cannot alias the input, including through a hardlink. Writing is
atomic after validation.

```sh
s9_descriptors.py firmware.bin edit --fields IPC
s9_descriptors.py firmware.bin edit IPC.default=8.2 --dry-run
s9_descriptors.py firmware.bin edit 'IPC.flags=ACT|VIS|EDT' --dry-run
```

### dump-tsv

```text
dump-tsv [FILE] [--tables TABLES] [--name QUERY] [--array TABLE]
         [--active] [--limit N] [--overwrite]
```

Export scalar descriptors as a rectangular UTF-8 TSV with one header.
`FILE` defaults to `-` (stdout). A file output cannot alias the input image.

| Option | Meaning |
|--------|---------|
| `--tables TABLES` | Comma-separated table names, such as `setting,enum` |
| `--array TABLE` | Restrict to one scalar kind: `setting`, `numeric`, `enum`, `bitfield`, `string`, `date`, or `time` |
| `--name QUERY` | Case-insensitive substring of UART names and labels |
| `--active` | Include only descriptors with ACT set |
| `--limit N` | Maximum matching rows to export |
| `--overwrite` | Replace an existing output file |

Without table selection, export all scalar descriptors. The export schema
supports scalar kinds only, even though `--tables` accepts other names from
`layout`.

Columns include table/index, UART ID and aliases, addresses and offsets,
flags, label IDs/text, raw and formatted defaults/bounds, divisor, units,
option count/mask/text, dependency head/count, and string capacity. Inapplicable
cells are empty. Text cells use TSV quoting for tabs, quotes, and newlines.

```sh
s9_descriptors.py firmware.bin dump-tsv descriptors.tsv --tables setting,enum
```

### scan-dir

```text
s9_descriptors.py scan-dir PATH [PATH ...]
```

Print a TSV summary of images: filename, BID, SID, variable count, modes, and
languages. A directory contributes its immediate `*.bin` files; traversal is
not recursive. This command does not require a preceding firmware argument.

```sh
s9_descriptors.py scan-dir firmware.bin other.bin
```

### compare

```text
compare PATH [PATH ...] [--changed-only]
```

Compare named descriptors from the input image and additional files or
directories. Directories contribute immediate `*.bin` files. Rows align by
UART name and show descriptor summaries for each image.

`--changed-only` omits rows with equal compared data. For scalars, comparison
covers kind, default, bounds, flags, and mask. For records, it covers named
fields and their formats or enabled state; UART streams also compare trigger
and format. ID, address, or label differences alone do not select a row.

```sh
s9_descriptors.py firmware.bin compare other.bin --changed-only
```

### compare-names

```text
compare-names OTHER [--mode MODE] [--limit N] [--list-only]
```

Compare the input image with one other image by UART resolver name. Print a
summary followed by TSV rows for common names.

| Option | Meaning | Default |
|--------|---------|---------|
| `--mode active` | Show changes in ACT state | Selected |
| `--mode table-presence` | Show names decoded on only one side | -- |
| `--mode id` | Show changed UART IDs | -- |
| `--mode changed` | Show any compared descriptor or ID change | -- |
| `--mode all` | Show all common names | -- |
| `--limit N` | Maximum common-name rows to print | No limit |
| `--list-only` | Also list names present in only one resolver | Off |

Despite its name, `--list-only` adds the unique-name lists; it does not suppress
the common-name table.

```sh
s9_descriptors.py firmware.bin compare-names other.bin --mode changed --limit 10
```

## Interactive Mode

Start the `s9>` shell with `-i`. Enter commands without the script or firmware
path. `help` lists commands; `help COMMAND` shows command help. `quit`, `exit`,
`q`, or end-of-input closes the shell. Quoted arguments use shell-style parsing.

A failed command reports an error and leaves the shell available. Edits and
exports are available in the shell. Writing an edited image does not reload it;
subsequent commands continue inspecting the original input.

```sh
s9_descriptors.py firmware.bin -i
```

## Output

Descriptor listings show a table index, `var=UART_ID:NAME`, flash address,
table-relative offset, flags, default, bounds or options, dependency link,
and text labels. Verbose mode adds decoded fields and metadata.

| Flag | Meaning |
|------|---------|
| `ACT` (`0x01`) | DataItem enabled |
| `VIS` (`0x02`) | Menu visibility permission; also requires ACT |
| `EDT` (`0x04`) | UI editing permission; also requires ACT |
| `SGN` (`0x08`) | Signed numeric serialization metadata |

These are descriptor defaults. Dependencies may change runtime flags and
values. A permission mask or ACT flag alone does not establish runtime
availability. EDT does not restrict low-level edits by this tool.

`def=` is a stored default, not the current device value. String/date/time
values reside in RAM and are not available from the image. Unresolved names
remain visible in `name`, `names`, and `namespaces`. Unknown operation and
metadata fields retain raw values. Firmware font bytes are printed as escapes
when they cannot be decoded as UTF-8; they are not rendered as device glyphs.

Listings and reports go to stdout; errors go to stderr. `dump-tsv` writes to
its output file or stdout. TSV IDs, addresses, flags, and masks are hexadecimal;
raw numeric values are separate from formatted values. `offset` is relative
to the table, while `file_offset` is relative to the image.

## Exit Status

| Status | Meaning |
|--------|---------|
| `0` | Successful command, interactive shell exit, or closed output pipe |
| `1` | Image, lookup, edit, or file error |
| `2` | Invalid command-line syntax |

An empty search is successful. Interactive command errors do not terminate
the shell.

## Examples

Inspect a default, write a modified image, and compare the result:

```sh
s9_descriptors.py firmware.bin var IPC
s9_descriptors.py firmware.bin edit IPC.default=8.2 -o edited.bin
s9_descriptors.py edited.bin var IPC
s9_descriptors.py firmware.bin compare edited.bin --changed-only
```

Find a setting and inspect its dependencies:

```sh
s9_descriptors.py firmware.bin search Leak
s9_descriptors.py firmware.bin chain ALR
s9_descriptors.py firmware.bin refs ALR
```

## See Also

[s9_languages](s9_languages.md), [as10_descriptors](as10_descriptors.md),
[as11_descriptors](as11_descriptors.md), [resmed_image](resmed_image.md).
