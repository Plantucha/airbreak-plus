# s9_languages

## Name

`s9_languages.py` - export S9 translations and build a replacement language set.

## Contents

- [Synopsis](#synopsis)
- [Description](#description)
- [Arguments](#arguments)
- [Options](#options)
- [Commands](#commands)
  - [inspect](#inspect)
  - [export](#export)
  - [build](#build)
- [Source Format](#source-format)
- [Output](#output)
- [Exit Status](#exit-status)
- [Examples](#examples)
- [See Also](#see-also)

## Synopsis

```text
s9_languages.py IMAGE inspect
s9_languages.py IMAGE export LANGUAGE -o FILE [--overwrite]
s9_languages.py IMAGE build [SOURCE ...] [-o FILE] [--dry-run]
                [--overwrite] [--ignore-input-crc] [--allow-relocation]
```

## Description

Export a language from a firmware image to an editable TSV file, or replace the
image's language set using version-matched TSV sources. Runs independently of
the patcher and shares its S9 firmware parser.

Supports raw 1 MiB images with CDX versions SX474-0905, SX474-0907,
SX474-0912, SX474-1201, SX474-1203, and SX474-1301.

English (LAN ID `0`) always comes from the input image. Supply one source file
for each other desired language. Languages omitted from the source list are
removed. With no source files, the result contains English only.

The builder preserves text IDs and metadata, rebuilds translation resources,
and updates `LAN`. It does not translate text, remap IDs between firmware
versions, modify fonts, or check display glyph coverage and line wrapping.

## Arguments

`IMAGE`: raw firmware image to inspect, export from, or rebuild.

`LANGUAGE`: language alias or decimal LAN ID. Aliases are case-insensitive;
see [Source Format](#source-format). The language must exist in the image when
exporting.

`SOURCE`: UTF-8 TSV named `SX474-NNNN.LANGUAGE.tsv`. The CDX version in the
filename must match the input image. Repository sources are stored under
`locales/s9/<version>/`, for example
`locales/s9/SX474-1301/SX474-1301.PL.tsv`.

`FILE`: output path, distinct from the input image and all source files.
Existing outputs require `--overwrite`. Parent directories must exist.

Examples assume the script in the repository's `python/` directory is on
`PATH`. Examples using `SX474-1301` files require an image with that CDX version.

## Options

| Option | Meaning |
|--------|---------|
| `-h`, `--help` | Show help; use `COMMAND --help` for command options |

A command is required. Output and build options follow the command; there is
no interactive mode.

## Commands

### inspect

```text
inspect
```

Show the CDX version, localized text-ID range, LAN mask and default, available
language IDs and labels, and resource space used versus capacity.

```sh
s9_languages.py firmware.bin inspect
```

### export

```text
export LANGUAGE -o FILE [--overwrite]
```

Export every localized text ID for one language, including empty strings.
The result uses the [source format](#source-format). Use a versioned filename
if the file will later be passed to `build`; `export` does not enforce the
output filename convention.

| Option | Meaning | Default |
|--------|---------|---------|
| `-o`, `--output FILE` | Write the TSV file | Required |
| `--overwrite` | Replace an existing output file | Off |

```sh
s9_languages.py firmware.bin export FR -o SX474-1301.FR.tsv
```

### build

```text
build [SOURCE ...] [-o FILE] [--dry-run] [--overwrite]
      [--ignore-input-crc] [--allow-relocation]
```

Build the complete desired language set from English in the input image and
the supplied non-English sources. Output language order follows numeric LAN
IDs, not argument order. Keep the input's default language if it is included;
otherwise select English.

| Option | Meaning | Default |
|--------|---------|---------|
| `-o`, `--output FILE` | Write a separate firmware image | Required unless `--dry-run` |
| `--dry-run` | Validate sources, pack resources, and read back the result without writing an image | Off |
| `--overwrite` | Replace an existing output file | Off |
| `--ignore-input-crc` | Allow invalid input region CRCs | Off |
| `--allow-relocation` | Permit moving the string-pointer table if retaining its address fails | Off |

Missing source IDs use the input image's English text, with a warning for each
file and ID. Repeated languages, an English source, mismatched versions,
invalid source records, or insufficient resource space fail the build.

By default the string-pointer table keeps its address. The builder can grow
it in place by repacking surrounding translation resources; the language count
does not have to remain equal to the input count. Capacity depends on the
complete packed result. Use `--dry-run` to check a proposed set.

If packing at the original address fails, the build stops without publishing
an image. `--allow-relocation` permits relocation as a fallback, not as a
forced action. It cannot bypass insufficient total capacity. When relocation
occurs, **CCX and CDX must be flashed together from the output image**; the
command prints a warning identifying that change.

The builder checks input CRCs and resource boundaries, preserves other CCX
data and fonts, updates checksums of changed regions, and reads back every
resulting text before writing. BLX remains unchanged. With no relocation,
only CCX changes; CDX remains unchanged. Ignoring an input CRC does not repair
unchanged regions.

```sh
s9_languages.py firmware.bin build SX474-1301.PL.tsv --dry-run
s9_languages.py firmware.bin build SX474-1301.FR.tsv SX474-1301.PL.tsv -o en-fr-pl.bin
s9_languages.py firmware.bin build -o english.bin
```

## Source Format

A source is UTF-8 text without a header, with one record per line:

```text
ID<TAB>text
```

`<TAB>` denotes one literal tab. IDs are localized text IDs, in decimal or
`0x` hexadecimal, within the input image's text-ID range. They are not raw
string-table indexes. Record order does not matter. Blank lines are ignored.
The first tab separates the ID from the text; leading and trailing text spaces
are preserved.

| Record | Meaning |
|--------|---------|
| `ID<TAB>text` | Translation for this ID |
| `ID<TAB>` | Intentional empty string |
| No record for an ID | Use the input image's English text and print a warning |
| `ID<TAB>@EN` | Literal text `@EN`; it is not a fallback marker |

Escapes are `\\`, `\n`, `\r`, `\t`, and `\xNN` (one hexadecimal byte).
Export escapes non-UTF-8 bytes so they can be preserved when rebuilding.
Embedded NUL, unknown or incomplete escapes, duplicate IDs, and out-of-range
IDs are errors.

The filename is `SX474-NNNN.LANGUAGE.tsv`. `LANGUAGE` can be a decimal LAN ID
or one of these aliases:

| LAN ID | Alias | LAN ID | Alias |
|--------|-------|--------|-------|
| 0 | EN | 10 | DA |
| 1 | FR | 11 | NO |
| 2 | DE | 12 | FI |
| 3 | IT | 13 | JA-13 |
| 4 | ES-4 | 14 | RU |
| 5 | ES-5 | 15 | TR |
| 6 | PT-6 | 16 | ZH-TW |
| 7 | PT-7 | 17 | ZH-CN |
| 8 | NL | 18 | PL |
| 9 | SV | 19 | JA-19 |

Numbered aliases distinguish duplicate language options without assigning
regional meanings. The target image's LAN options determine which IDs are
valid. EN exports are useful as translation references; `build` takes English
from its image and rejects EN source files.

Source IDs must already correspond to the target firmware version. Renaming
a file from another version does not convert its IDs. Repository translations
may include drafts; inspect terminology and display layout on the target.

## Output

`inspect` prints image and capacity information. `export` writes a TSV and
prints the exported text count. `build` prints the resulting language IDs,
LAN mask and default, text and unique-string counts, English fallback count,
and resource usage. A build that retains the table address prints
`Changes: CCX`; a dry run also reports that no image was written.

Reports go to stdout. Errors, missing-translation warnings, and relocation
warnings go to stderr. Output files are written atomically after validation.
Input/source path aliases, including hardlinks, cannot be used as outputs.

## Exit Status

| Status | Meaning |
|--------|---------|
| `0` | Successful inspection, export, build, or dry run |
| `1` | Image, source, capacity, validation, or file error |
| `2` | Invalid command-line syntax |

English fallbacks and permitted relocation produce warnings but do not make
a successful build fail.

## Examples

For a SX474-1301 image, keep its French translation and add Polish from the
repository catalog:

```sh
s9_languages.py firmware.bin export FR -o SX474-1301.FR.tsv --overwrite
s9_languages.py firmware.bin build SX474-1301.FR.tsv locales/s9/SX474-1301/SX474-1301.PL.tsv --dry-run
s9_languages.py firmware.bin build SX474-1301.FR.tsv locales/s9/SX474-1301/SX474-1301.PL.tsv -o translated.bin
s9_languages.py translated.bin inspect
```

Permit relocation if the same language set cannot fit at the original table
address:

```sh
s9_languages.py firmware.bin build SX474-1301.FR.tsv SX474-1301.PL.tsv --allow-relocation --dry-run
```

## See Also

[s9_descriptors](s9_descriptors.md), [resmed_image](resmed_image.md).
