# AirMini CONF Block Format

Reference for the AirMini CONF block layout, globals[] master table, var-id
dispatch, descriptor record shapes, and per-table semantics.

This reference covers `Airmini-SW03900.01.4.0.3.50927.bin`. The companion
[airmini_descriptors](../tools/airmini_descriptors.md) tool decodes this layout.

## Table of contents

- [globals[] map](#globals-map)
- [Runtime consumers](#runtime-consumers)
- [Conventions](#conventions)
- [Structure families](#structure-families)
- [DataItem descriptor selection](#dataitem-descriptor-selection)
- [Flags field](#flags-field)
- [Common DataItem descriptor fields](#common-dataitem-descriptor-fields)
- [Data rule callbacks](#data-rule-callbacks)
- [g[0] -- CONF header](#g0----conf-header)
- [g[1] -- volatile-text DataItem descriptors](#g1----volatile-text-dataitem-descriptors)
- [g[2] -- numeric DataItem descriptors](#g2----numeric-dataitem-descriptors)
- [g[3] -- bitfield DataItem descriptors](#g3----bitfield-dataitem-descriptors)
- [g[4] -- bitfield selection-order pool](#g4----bitfield-selection-order-pool)
- [g[5] -- enum DataItem descriptors](#g5----enum-dataitem-descriptors)
- [g[6] -- numeric-array DataItem descriptors](#g6----numeric-array-dataitem-descriptors)
- [g[7] -- EEPROM SettingsGroup schemas](#g7----eeprom-settingsgroup-schemas)
- [g[8] -- date DataItem descriptors](#g8----date-dataitem-descriptors)
- [g[9] -- time DataItem descriptors](#g9----time-dataitem-descriptors)
- [g[10] -- PDL power-loss snapshot](#g10----pdl-power-loss-snapshot)
- [g[11] -- identity-variable list](#g11----identity-variable-list)
- [g[12] -- short-name bucket headers](#g12----short-name-bucket-headers)
- [g[13] -- event spool definitions](#g13----event-spool-definitions)
- [g[14] -- EventNotification payload overrides](#g14----eventnotification-payload-overrides)
- [g[15] -- periodic collections](#g15----periodic-collections)
- [g[16] -- RPC JSON node permission table](#g16----rpc-json-node-permission-table)
- [APPL long names and enum symbols](#appl-long-names-and-enum-symbols)
- [Unresolved fields](#unresolved-fields)

---

## globals[] map

`count × stride` describes the root object, excluding referenced pools and
alignment padding, except for the explicitly noted g[4] span.

| Global | File offset | Count | Stride | Meaning |
| ---: | --- | ---: | ---: | --- |
| g[0] | `0x020000` | 1 | 256 | Identity header |
| g[1] | `0x020840` | 30 | 10 | volatile-text DataItem descriptors |
| g[2] | `0x02096c` | 216 | 28 | numeric DataItem descriptors |
| g[3] | `0x02210c` | 9 | 20 | bitfield DataItem descriptors |
| g[4] | `0x0221c0` | 72 bytes | — | Selection-order pool, including 2 trailing padding bytes |
| g[5] | `0x022208` | 61 | 16 | enum DataItem descriptors |
| g[6] | `0x0225d8` | 1 | 36 | Numeric-array DataItem |
| g[7] | `0x022674` | 12 | 16 | SettingsGroup schemas |
| g[8] | `0x022734` | 1 | 8 | Date DataItem |
| g[9] | `0x022744` | 1 | 8 | Time DataItem |
| g[10] | `0x02276c` | 1 | 12 | PDL member header |
| g[11] | `0x022778` | 21* | 2 | Identity-related IDs |
| g[12] | `0x022cd0` | 26 | 8 | A–Z short-name bucket headers |
| g[13] | `0x0204f8` | 14 | 36 | Event spool definitions |
| g[14] | `0x0206f0` | 20 | 6 | Event JSON payload overrides |
| g[15] | `0x0207a0` | 4 | 40 | Periodic collection definitions |
| g[16] | `0x0227a4` | 13 | 1 | JSON profile node availability |

\* g[11]: 21 decoded IDs followed by `0x0000`. Logical count and trailing-word
meaning are unknown.

---

## Runtime consumers

CONF is the declarative data model. APPL constructs objects from its descriptors,
maintains mutable flags/values and applies callbacks, persistence and logging.
CONF stores initial values; current values reside in runtime storage.

At flash address `0x08020100` the getter executes:

```text
addw r0, pc, #4
bx   lr
```

It returns the inline globals table at `0x08020108`. The table has 17 pointers;
the following bytes at `0x02014c` are event-name strings.

| Roots | Primary consumer (flash address) | Relationship |
| --- | --- | --- |
| g[0] | `0x080580e4` | Initializes identity DataItems from CONF/header versions |
| g[1] | `0x0805f1ac`, `0x0805f35e` | Text objects, capacity and startup flags |
| g[2] | `0x0805434c`, `0x080548ce`, `0x08054940` | Numeric objects, bounds and scaling |
| g[3], g[4] | `0x0805ed00`, `0x0805ef50`, `0x0805ee90` | Bitfields, selection lists and hex formatting |
| g[5] | `0x08053adc`, `0x08053e34` | Enum objects, defaults and option count |
| g[6] | `0x0805f400` | Seeds numeric-array backing storage |
| g[7] | `0x08098994`, `0x08098d58`, `0x080990f0` | EEPROM SettingsGroup files and members |
| g[8], g[9] | `0x0805f4a0`, `0x0805f820` | Date/time DataItem objects |
| g[10] | `0x0809b1d8` | Power-loss snapshot member root |
| g[11] | Unknown | u16 ID list; purpose unknown |
| g[12] | `0x08057e10`, `0x08054228` | Short tag lookup in both directions |
| g[13], g[14] | `0x0805360e`, call setup near `0x080a03d4` | Event spool and JSON payload definitions |
| g[15] | `0x080aaa0c`, `0x08095190`, `0x080a1cf2` | Periodic capture, logged-data JSON, NOR files |
| g[16] | `0x0809606a` | Availability byte indexed by a JSON object's node ID |

---

## Conventions

- `g[n]` means `globals[n]`, the nth 32-bit entry in the CONF master table.
- Record offsets such as `+0x0c` are relative to the start of the record.
- File offsets refer to the complete 1 MiB flash image. Runtime flash addresses
  are `0x08000000 + file_offset`; CONF starts at file offset `0x020000`.
- Raw example bytes are shown in file order. Multi-byte fields are little-endian
  except the stored CONF CRC, which is big-endian.
- Var IDs are version-local DataItem IDs assigned by descriptor-array position.
  Use short tags or canonical long names when comparing releases. For example,
  MOP's canonical long name is `TherapyMode`; `ActiveTherapyProfile` is a separate
  RPC selector schema, not an interchangeable DataItem name.
- All counts, addresses, masks and examples below refer to
  `Airmini-SW03900.01.4.0.3.50927.bin`, size 1,048,576 bytes, SHA-256
  `2823f7f833335a5676a438ea4b805cfd561b09798906bcf908ba8144c115abbc`.
- Layout tables use `Offset`, `Size`, `Field`, `Description`, as in the
  [Air11 format reference](../as11/conf_block_format.md). Sizes are in bytes;
  signed types are explicit. A `ptr` is a 32-bit flash address.
- Common field names follow Air11's format documentation. CLI abbreviations
  include `data_rule` for `data_rule_id`, `linked_counter` for
  `linked_counter_index`, and `event_queue` for `change_event_queue_index`.
  The enum field `n_options` appears as `option_count` in command output.
- Unknown fields are named by their record offset.

---

## Structure families

CONF roots use the following structure families and extent rules:

| Family | Roots | Extent rule |
|--------|-------|-------------|
| Descriptor array | g[1], g[2], g[3], g[5], g[6], g[8], g[9] | APPL dispatch/startup count multiplied by record stride |
| Byte pool | g[4] | maximum referenced `selection_order_offset + bit_count`: 70 bytes; two trailing alignment bytes before g[5] |
| Fixed table | g[7] | 12 SettingsGroup headers; each carries a member pointer and count |
| Header with referenced data | g[10] | 12-byte header; decode the member list through its pointer and count |
| Uncounted ID list | g[11] | u16 entries; logical count unknown |
| Bucket headers | g[12] | 26 headers; each carries an entry pointer and count |
| Table with APPL-defined count | g[13], g[14], g[15] | consumer count multiplied by record stride |
| Node-id indexed table | g[16] | 13 RPC node IDs multiplied by one byte |

Root extents exclude referenced objects. Padding is not a descriptor; the g[4]
root span in the map explicitly includes its two trailing alignment bytes.

---

## DataItem descriptor selection

The factory dispatch uses mappers at `0x0805bf8c`, `0x0805bfa2`,
`0x0805bfb8`, `0x0805bfce`, plus date/time mappers at `0x0805bfdc` and
`0x0805bff6`, and the extended-ID tests near `0x08057ff4`.

| Table | ID range | Type |
| --- | --- | --- |
| g[1] | `0x0000..0x001d` | Volatile text |
| g[2] | `0x001e..0x00f5` | Numeric |
| g[3] | `0x00f6..0x00fe` | Bitfield |
| g[5] | `0x00ff..0x013b` | Enum |
| g[6] | `0x013c` | Numeric array A00 |
| g[7] | `0x013d..0x0148` | SettingsGroup |
| g[8] | `0x0149` | DAC |
| g[9] | `0x014a` | TIC |
| g[10] | `0x014b` | PDL |

There are 332 IDs and 327 short tags. IDs without a short tag still have a long
name and a descriptor. IDs are assigned by table position, not stored in each
scalar record. `index = var_id - table_id_base`.

```text
record_index = var_id - selected_array_base
record_offset = array_offset + record_index * record_stride
```

The extended IDs for g[7] and g[10] use group/snapshot headers, not the common
scalar descriptor prefix.

---

## Flags field

The u16 `flags` field seeds runtime flags in g[1], g[2], g[3], g[5], g[6],
g[8] and g[9]. Names below are the short flag labels used by the CLI.

| Bit | Mask | Name | Meaning |
|----:|------|------|---------|
| 0 | `0x0001` | `ACT` | Active |
| 1 | `0x0002` | `VIS` | Visible |
| 2 | `0x0004` | `MOD` | Mode/UI binding flag (historical vocabulary) |
| 3 | `0x0008` | `SGN` | Signed formatting |
| 4 | `0x0010` | `INH` | Inhibited |
| 5 | `0x0020` | `VAL` | Runtime value initialized |
| 6 | `0x0040` | `ULK` | Update lock |
| 7 | `0x0080` | `RAW` | Raw numeric handling |
| 8 | `0x0100` | `MON` | Change monitoring |
| 9 | `0x0200` | `RPC` | RPC exposure |
| 10 | `0x0400` | `RPW` | RPC write capability |

CONF stores the initial mask. Startup clears `0x0040`; the update path tests
active/value state and invokes callbacks. Bit 11 semantics are unknown.
The full runtime semantics of the named bits are not specified here.

---

## Common DataItem descriptor fields

Text, numeric, bitfield, enum, numeric-array, date and time descriptors share:

| Offset | Size | Field | Description |
|--------|-----:|-------|-------------|
| +0x00 | 2 | flags | Initial flags |
| +0x02 | 1 | data_rule_id | Data-rule callback index; zero means no rule |
| +0x03 | 1 | reserved | Reserved, zero |
| +0x04 | 2 | linked_counter_index | Linked **g[2] index**, `0x7fff` means no link |
| +0x06 | 1 | change_event_queue_index | Change-event queue index; 14 is the no-queue sentinel |
| +0x07 | 1 | reserved | Reserved, zero |

The common constructor at `0x08053edc` stores a descriptor pointer separately
from runtime storage. Startup routines copy descriptor flags/defaults to RAM.
The update path at `0x080540c4` checks active/value/update conditions and invokes
the rule from `descriptor[2]`; `0x08054190` follows the linked numeric counter.

Membership in a persistent settings group is defined by the var-ID lists
referenced by g[7], not by these descriptor fields.

---

## Data rule callbacks

The common update path gets the rule from descriptor `+0x02`. The lookup at
`0x08059660` indexes a static pointer array at `0x05980c`. Entry zero is null;
entries 1–9 are Thumb pointers. Callback addresses below have the Thumb bit
cleared.

| Rule | Callback address | Variables using the rule |
| ---: | --- | --- |
| 1 | `0x080596fc` | MPA, MPI, STU |
| 2 | `0x08059704` | HMA, HMI, HSP |
| 3 | `0x0805970c` | LNC, LAN |
| 4 | `0x08059786` | IPC, STP |
| 5 | `0x080597c4` | MOP |
| 6 | `0x0805966a` | BLL |
| 7 | `0x080597c6` | RMA |
| 8 | `0x080597f0` | MHR, MHS, MHU, CUD, PHM |
| 9 | `0x080597f4` | SRN |

Rule 5 starts with a NOP and falls through into rule 7's body. Rules 1/2 use
numeric-bound update helpers; rule 4 relates CPAP start pressure to set pressure.

---

## g[0] -- CONF header

**Header size:** 256 bytes

| Offset | Size | Field | Description |
|--------|-----:|-------|-------------|
| +0x00 | 4 | data_version | Data version: 1 |
| +0x04 | 4 | platform_id | Platform ID: 39 (`0x27`) |
| +0x08 | 4 | aid | AID: 0 |
| +0x0c | 4 | variant_id | Variant ID: 3 |
| +0x10 | 4 | region_id | Region ID: 0 |
| +0x14 | 16 | platform_text | `SIMPLICITY` |
| +0x24 | 16 | default_product_code | Default product code `380XX` |
| +0x34 | 16 | default_product_name | Default product name `AirMini AutoSet` |
| +0x44 | 32 | unknown_44 | Zero-filled region; semantics unresolved |
| +0x64 | 4 | header_64_raw | 50927; meaning unknown |
| +0x68 | 12 | data_model_version | Data-model version `1.0.0` |
| +0x74 | 4 | header_74_raw | `0x0000010e`; semantics unresolved |
| +0x78 | 136 | padding | `ff` padding to the getter at `+0x100` |

### Runtime composite identifiers

The bootloader version string at file offset `0x0f00` is `3.0.0.48255`.
The application version string at `0x040000` is `4.0.3.50927`. The corresponding
component identifiers are `SW03901.00.3.0.0.48255` and
`SW03900.01.4.0.3.50927`.

### CONF CRC

CONF occupies `[0x20000, 0x40000)`. CRC-16/CCITT-FALSE has polynomial `0x1021`,
initial value `0xffff`, no reflection and no final XOR. It covers
`[0x20000, 0x3fffe)`. The stored CRC is big-endian at `0x03fffe`: `dd 3e`.

---

## g[1] -- volatile-text DataItem descriptors

**Record stride:** 10 bytes

Describes runtime string/identifier buffers.

| Offset | Size | Field | Description |
|--------|-----:|-------|-------------|
| +0x00 | 2 | flags | Initial flags |
| +0x02 | 1 | data_rule_id | Data-rule callback index; zero means no rule |
| +0x03 | 1 | reserved | Reserved, zero |
| +0x04 | 2 | linked_counter_index | Linked **g[2] index**, `0x7fff` means no link |
| +0x06 | 1 | change_event_queue_index | Change-event queue index; 14 is the no-queue sentinel |
| +0x07 | 1 | reserved | Reserved, zero |
| +0x08 | 2 | buffer_capacity | runtime string-buffer capacity in bytes |

Constructor `0x0805f1ac` multiplies the index by 10; `0x0805f1ea` reads capacity.
`0x0805f35e` iterates exactly 30 records during initialization.

The descriptor contains neither a text default nor a current-value pointer.

Example -- `BID` / `BootloaderIdentifier` in 4.0.3.50927, file offset
`0x020840`:

| Offset | Raw bytes | Field | Decoded value |
|-------:|-----------|-------|---------------|
| `+0x00` | `07 06` | flags | `0x0607` |
| `+0x02` | `00` | data_rule_id | `0` |
| `+0x03` | `00` | reserved | `0` |
| `+0x04` | `ff 7f` | linked_counter_index | `0x7FFF` |
| `+0x06` | `0e` | change_event_queue_index | `14` |
| `+0x07` | `00` | reserved | `0` |
| `+0x08` | `20 00` | buffer_capacity | `32` |

---

## g[2] -- numeric DataItem descriptors

**Record stride:** 28 bytes

Default, maximum and minimum are signed i32 values, including for records
whose display flags describe an unsigned quantity. AirMini uses 28-byte
records; the Air11 record is 32 bytes.

| Offset | Size | Field | Description |
|--------|-----:|-------|-------------|
| +0x00 | 2 | flags | Initial flags |
| +0x02 | 1 | data_rule_id | Data-rule callback index; zero means no rule |
| +0x03 | 1 | reserved | Reserved, zero |
| +0x04 | 2 | linked_counter_index | Linked **g[2] index**, `0x7fff` means no link |
| +0x06 | 1 | change_event_queue_index | Change-event queue index; 14 is the no-queue sentinel |
| +0x07 | 1 | reserved | Reserved, zero |
| +0x08 | 4 | default_raw (i32) | Default |
| +0x0c | 4 | max_raw (i32) | Maximum |
| +0x10 | 4 | min_raw (i32) | Minimum |
| +0x14 | 1 | decimal_places | Decimal-place metadata |
| +0x15 | 1 | reserved | Reserved, zero in this image |
| +0x16 | 2 | scale (i16) | Display scale divisor |
| +0x18 | 2 | step_raw (i16) | Step |
| +0x1a | 2 | tail_1a_raw | Zero tail; no Air11 bounds-slot/signal/class fields |

Display value = raw value / scale. The CLI uses raw values for zero scale.
Default/limit/step accessors:
`0x08054426`, `0x080548ce`, `0x080548e4`, `0x08054910`, `0x08054940`.

Example IPC (`CPAP-SetPressure`, ID `0x38`, offset `0x020c44`): default 500,
min 200, max 1000, scale 50, step 10. Display values are 10, 4, 20, 0.2.
RMT (ID `0xf4`, `0x0220d4`) has default 10, min 5, max 45, scale 1, step 5.
The rule code can alter effective bounds; these are baseline descriptors.

Example -- `IPC` / `CPAP-SetPressure` in 4.0.3.50927, file offset
`0x020c44`:

| Offset | Raw bytes | Field | Decoded value |
|-------:|-----------|-------|---------------|
| `+0x00` | `07 02` | flags | `0x0207` |
| `+0x02` | `04` | data_rule_id | `4` |
| `+0x03` | `00` | reserved | `0` |
| `+0x04` | `65 00` | linked_counter_index | `0x0065` |
| `+0x06` | `0e` | change_event_queue_index | `14` |
| `+0x07` | `00` | reserved | `0` |
| `+0x08` | `f4 01 00 00` | default_raw (i32) | `500` |
| `+0x0c` | `e8 03 00 00` | max_raw (i32) | `1000` |
| `+0x10` | `c8 00 00 00` | min_raw (i32) | `200` |
| `+0x14` | `01` | decimal_places | `1` |
| `+0x15` | `00` | reserved | `0` |
| `+0x16` | `32 00` | scale (i16) | `50` |
| `+0x18` | `0a 00` | step_raw (i16) | `10` |
| `+0x1a` | `00 00` | tail_1a_raw | `0000` |

---

## g[3] -- bitfield DataItem descriptors

**Record stride:** 20 bytes

| Offset | Size | Field | Description |
|--------|-----:|-------|-------------|
| +0x00 | 2 | flags | Initial flags |
| +0x02 | 1 | data_rule_id | Data-rule callback index; zero means no rule |
| +0x03 | 1 | reserved | Reserved, zero |
| +0x04 | 2 | linked_counter_index | Linked **g[2] index**, `0x7fff` means no link |
| +0x06 | 1 | change_event_queue_index | Change-event queue index; 14 is the no-queue sentinel |
| +0x07 | 1 | reserved | Reserved, zero |
| +0x08 | 4 | default_mask | Default mask |
| +0x0c | 4 | editable_mask | Editable bit mask |
| +0x10 | 1 | bit_count | Number of selection-list entries |
| +0x11 | 1 | display_bits | Display width in bits |
| +0x12 | 2 | selection_order_offset | Byte offset into g[4] |

The formatter at `0x0805ee90` divides the `+0x11` value by 4 to obtain a hex-digit
width; a zero value produces one digit.
The mask test near `0x0805ee76` reads `+0x0c` when checking an editable bit.

LNC is ID `0xfb`, record `0x022170`: default mask 1, editable mask `0x000b000f`,
20 selections, width 20, selection-pool offset 33. Its flag word is `0x0206`,
so ACT is clear.

LAN (enum index 23, ID `0x116`) has the same `0x000b000f` option mask:
indices 0, 1, 2, 3, 16, 17 and 19. This is the descriptor's allowed-option
set, not the configured LNC value: LNC defaults to bit 0 and LAN defaults to 0.
Rule 3 at `0x0805970c` reads both objects. If the current LAN value's bit is
absent from LNC, it scans the 20 positions and selects the first set LNC bit.
Both descriptors have ACT clear.

The APPL symbol table contains no LAN entries. Language-name mapping is unknown.

---

## g[4] -- bitfield selection-order pool

Each g[3] record references `[selection_order_offset, selection_order_offset + bit_count)`
inside this byte pool. Each byte is a bit index, not a var ID. The nine slices
have offsets/counts `0/3, 3/5, 8/5, 13/2, 15/18, 33/20, 53/6, 59/6, 65/5`.
They cover 70 bytes, with two alignment bytes before g[5].

---

## g[5] -- enum DataItem descriptors

**Record stride:** 16 bytes

| Offset | Size | Field | Description |
|--------|-----:|-------|-------------|
| +0x00 | 2 | flags | Initial flags |
| +0x02 | 1 | data_rule_id | Data-rule callback index; zero means no rule |
| +0x03 | 1 | reserved | Reserved, zero |
| +0x04 | 2 | linked_counter_index | Linked **g[2] index**, `0x7fff` means no link |
| +0x06 | 1 | change_event_queue_index | Change-event queue index; 14 is the no-queue sentinel |
| +0x07 | 1 | reserved | Reserved, zero |
| +0x08 | 1 | default_option | Default option index |
| +0x09 | 1 | n_options | Option count |
| +0x0a | 2 | reserved | Reserved |
| +0x0c | 4 | option_mask | Enabled-option mask |

### Option meanings

MOP, ID `0xff`, g[5][0], offset `0x022208`: flags `0207`, rule 5,
linked g[2] counter `0x79`, queue 14, default 1, count 12, mask `00000803`.
AirMini's APPL symbol table maps enabled indexes **0/1/11** to
**CPAP/AutoSet/HerAuto**. Slots 2–10 have no symbol-table entries.
LAN selection is constrained by LNC; see g[3].

Example -- `MOP` / `TherapyMode` in 4.0.3.50927, file offset
`0x022208`:

| Offset | Raw bytes | Field | Decoded value |
|-------:|-----------|-------|---------------|
| `+0x00` | `07 02` | flags | `0x0207` |
| `+0x02` | `05` | data_rule_id | `5` |
| `+0x03` | `00` | reserved | `0` |
| `+0x04` | `79 00` | linked_counter_index | `0x0079` |
| `+0x06` | `0e` | change_event_queue_index | `14` |
| `+0x07` | `00` | reserved | `0` |
| `+0x08` | `01` | default_option | `1` |
| `+0x09` | `0c` | n_options | `12` |
| `+0x0a` | `00 00` | reserved | `0` |
| `+0x0c` | `03 08 00 00` | option_mask | `0x00000803` |

---

## g[6] -- numeric-array DataItem descriptors

**Record stride:** 36 bytes

One 36-byte record, ID `0x13c`, A00, long name `_DUMMY_NUMERIC_ARRAY_ITEM`.
The first 28 bytes use the g[2] layout. Additional fields:

| Offset | Size | Field | Description |
|--------|-----:|-------|-------------|
| +0x1c | 4 | storage_index | Start index in backing numeric storage |
| +0x20 | 1 | element_count | Element count |
| +0x21 | 3 | padding | Padding |

The startup loop at `0x0805f400` uses a 36-byte stride, copies flags and fills
`storage[start + element]` with the default. This image has start 0 and three
elements, default 0, min 0, max 100, scale 100, step 1. Element values reside
in runtime storage.

---

## g[7] -- EEPROM SettingsGroup schemas

**Record stride:** 16 bytes

Twelve 16-byte SettingsGroup records, themselves in the extended DataItem ID
space. These do **not** have the common scalar prefix.

| Offset | Size | Field | Description |
|--------|-----:|-------|-------------|
| +0x00 | 4 | tag | Three-character group tag and terminator |
| +0x04 | 2 | update_counter_index | Associated g[2] counter index |
| +0x06 | 1 | policy_06 | Group policy byte, accessor at `0x08098e24`; exact policy unresolved |
| +0x07 | 1 | aggregate_counter | Include associated counter in aggregate counter sum |
| +0x08 | 4 | member_ids_ptr | u16 member-ID list |
| +0x0c | 1 | count | Member count |
| +0x0d | 3 | padding | Padding |

`0x08098994` initializes the member container from pointer/count. The member
serialization path is visible at `0x08098d58`. File names are constructed near
`0x080990f0` from `eep:0:\SETTINGS\` and the group tag, with `.set` extension.
The counter-sum consumer at `0x0809ccb2` tests `+0x07` across all 12 records.

| Group | Counter index | Members |
| --- | --- | --- |
| MML | 17 | PHM, MHR, MHS, MHU, CUD |
| AGL | 92 | MPA, MPI, STU, AFC |
| AHL | 94 | HMA, HMI, HSP |
| CGL | 101 | IPC, STP |
| EGL | 103 | EPR, EPT, EPX, EPA |
| BGL | 106 | PSH, PZH, FLG, FLZ, PCB |
| DID | 107 | PCD, SRN, PNA, IAM, IPS, IAD, GUD, UDI |
| MGL | 112 | RMA, RMT, SST, SSP |
| PGL | 117 | MSK, MSM |
| SGL | 121 | MOP, LNC, LAN |
| BTP | 136 | BC0, BA0, BP0, BC1, BA1, BP1, BC2, BA2, BP2, CED, FBD, FTD, PSK, QFC |
| MCF | 139 | MAD |

Member lists define the group schema. Runtime state determines which members
are active and stored.

---

## g[8] -- date DataItem descriptors

**Record stride:** 8 bytes

One descriptor: DAC, ID `0x149`, file offset `0x022734`.
The constructor at `0x0805f4a0` indexes with an 8-byte stride; the startup loop
at `0x0805f7c0` processes one record. The record consists of the common fields
listed below. No default date follows the prefix. Values come from runtime
date services; the gap to g[9] is not part of the descriptor.

| Offset | Size | Field | Description |
|--------|-----:|-------|-------------|
| +0x00 | 2 | flags | Initial flags |
| +0x02 | 1 | data_rule_id | Data-rule callback index; zero means no rule |
| +0x03 | 1 | reserved | Reserved, zero |
| +0x04 | 2 | linked_counter_index | Linked **g[2] index**, `0x7fff` means no link |
| +0x06 | 1 | change_event_queue_index | Change-event queue index; 14 is the no-queue sentinel |
| +0x07 | 1 | reserved | Reserved, zero |

---

## g[9] -- time DataItem descriptors

**Record stride:** 8 bytes

One descriptor: TIC, ID `0x14a`, file offset `0x022744`.
The constructor at `0x0805f820` indexes with an 8-byte stride; the startup loop
at `0x0805fb28` processes one record. No default time follows the common fields.
Values come from runtime time services; the gap to the next root is not part
of the descriptor.

| Offset | Size | Field | Description |
|--------|-----:|-------|-------------|
| +0x00 | 2 | flags | Initial flags |
| +0x02 | 1 | data_rule_id | Data-rule callback index; zero means no rule |
| +0x03 | 1 | reserved | Reserved, zero |
| +0x04 | 2 | linked_counter_index | Linked **g[2] index**, `0x7fff` means no link |
| +0x06 | 1 | change_event_queue_index | Change-event queue index; 14 is the no-queue sentinel |
| +0x07 | 1 | reserved | Reserved, zero |

---

## g[10] -- PDL power-loss snapshot

**Record stride:** 12 bytes

PDL, ID `0x14b`, uses a 12-byte header: `char tag[4]`, pointer to u16 IDs, u32
count. The pointer is `0x08022754`, count 11. Member tags in order:

```text
REM ZSE ZDT ZDD FWC FEC BTU BUC XSS RYS RFP
```

The consumer at `0x0809b1d8` loads this member list. Retention medium and
recovery protocol are unknown.

| Offset | Size | Field | Description |
|--------|-----:|-------|-------------|
| +0x00 | 4 | tag | `PDL` and terminator |
| +0x04 | 4 | member_ids_ptr | ptr to the u16 DataItem ID list |
| +0x08 | 4 | count | number of member IDs: 11 |

---

## g[11] -- identity-variable list

The 21 distinct IDs correspond to:

```text
BID BCD FGT MID PCB PCD PNA SID SRN VID PVI RID CID PVD PID TED AID DMV GUD UDI MAD
```

The span `0x022778..0x0227a3` contains 22 u16 words: the 21 IDs above and a
final `0x0000`. No count field is present. The list's purpose, logical count
and meaning of the final word are unknown.

---

## g[12] -- short-name bucket headers

**Record stride:** 8 bytes

26 eight-byte A–Z headers: pointer at `+0x00`, u8 count at `+0x04`, three zero
padding bytes at `+0x05`. Null pointer/count denotes an empty bucket.

An entry is four bytes: two suffix characters, then u16 var ID. The first tag
character is determined by the bucket. The suffix pool begins at `0x0227b4`.
Both forward and reverse lookup use these buckets.

Lookup: `0x08057e10`; reverse lookup: `0x08054228`. Total: 327 entries.

| Offset | Size | Field | Description |
|--------|-----:|-------|-------------|
| +0x00 | 4 | entries_ptr | ptr to suffix/ID entries; null for an empty bucket |
| +0x04 | 1 | count | number of entries in this bucket |
| +0x05 | 3 | reserved | zero |

**Entry stride:** 4 bytes

| Offset | Size | Field | Description |
|--------|-----:|-------|-------------|
| +0x00 | 2 | suffix | second and third characters of the short tag |
| +0x02 | 2 | var_id | DataItem ID; the first tag character comes from the bucket |

---

## g[13] -- event spool definitions

**Record stride:** 36 bytes

Fourteen 36-byte records. The loop at `0x0805360e` compares against 14.

| Offset | Size | Field | Description |
|--------|-----:|-------|-------------|
| +0x00 | 4 | name_ptr | Full event/spool name |
| +0x04 | 4 | code_ptr | Three-character tag |
| +0x08 | 4 | fifo_slots | FIFO slots |
| +0x0c | 4 | retained_record_target | Retained-record budget |
| +0x10 | 4 | event_record_bytes | Event payload record bytes |
| +0x14 | 1 | record_kind | Record kind (1, 2, 3 in this image) |
| +0x15 | 1 | default_json_payload_type | Default JSON payload type |
| +0x16 | 1 | erase_class | Erasure class |
| +0x17 | 1 | flag_17 | Writer/logger flag; semantics unknown |
| +0x18 | 4 | file_record_bytes | File record/block bytes |
| +0x1c | 4 | allocation_group_blocks | Allocation group blocks |
| +0x20 | 2 | file_init_flag_bit | File initialization flag bit |
| +0x22 | 2 | reserved_22 | Zero; semantics unknown |

The rows cover fatal/application/system errors, therapy status/settings history,
respiratory events, activity events, RPC activity and Bluetooth logs. For example
FAE (`DiagnosticExceptionEvents-FatalError`) has FIFO 4, retained-record budget
100, payload size 8, record kind 2 and file record size 128.
Payload-size and record-kind consumers: `0x0805357c`, `0x08051ffc`, `0x08056ec0`.
Writer flag `+0x17` semantics are unknown.

---

## g[14] -- EventNotification payload overrides

**Record stride:** 6 bytes

20 six-byte records: u8 event-spool index, zero byte, u16 event value,
u8 JSON payload type, zero byte. Initialization near `0x080a03d4` passes both
g[13]/14 and counts 14/20 to the formatter. This is a sparse override list,
not a replacement for the default payload type in every event definition.

Types 0 through 6 occur across defaults/overrides. Wire payload encodings are
unspecified here. The RPC-activity override uses event value `0xffff`.

| Offset | Size | Field | Description |
|--------|-----:|-------|-------------|
| +0x00 | 1 | event_spool_index | g[13] record index |
| +0x01 | 1 | reserved | zero |
| +0x02 | 2 | event_value | value to match, including the observed `0xffff` value |
| +0x04 | 1 | json_payload_type | payload formatter selector |
| +0x05 | 1 | reserved | zero |

---

## g[15] -- periodic collections

**Record stride:** 40 bytes

The loop in `0x080aaa0c` processes four records. Each record refers
to a u16 DataItem list and a parallel array of pointers to logged-data names.

| Offset | Size | Field | Description |
|--------|-----:|-------|-------------|
| +0x00 | 4 | tag_ptr | Collection tag |
| +0x04 | 2 | sample_interval_ms | Sample interval, milliseconds |
| +0x06 | 2 | max_block_duration_seconds | Maximum block duration, seconds; zero means no duration cap |
| +0x08 | 4 | file_record_bytes | Buffer/file block bytes |
| +0x0c | 4 | retention_hours | Retention **hours** |
| +0x10 | 4 | allocation_group_blocks | Allocation group blocks |
| +0x14 | 1 | file_policy | File policy passed to the writer |
| +0x15 | 1 | flag_15 | Flag; semantics unknown |
| +0x16 | 1 | gate_descriptor_index | g[5] gate index |
| +0x17 | 1 | padding | Padding |
| +0x18 | 2 | file_init_flag_bit | File initialization flag bit |
| +0x1a | 2 | padding | Padding |
| +0x1c | 1 | signal_count | Signal count |
| +0x1d | 3 | padding | Padding |
| +0x20 | 4 | signal_var_ids_ptr | u16 source DataItem IDs |
| +0x24 | 4 | signal_names_ptr | Parallel logged-data-name pointers |

`0x08095190` joins IDs to `dataId` strings for GetLoggedData output.
`0x0809521e` formats the sampling interval. `0x080aa354` converts `+0x06` to a
sample count via `seconds*1000/interval_ms`; `0x080aa478` closes the block when
that count is reached or the buffer fills. `0x080a1cf2` computes retention
allocation using the multiplier **3,600,000** stored at `0x080a1dac`, hence hours.
It constructs paths under `nor:0:\DATALOG\`.

| Tag | Interval ms | Max block s | Retention h | Gate | Source tags |
| --- | ---: | ---: | ---: | --- | --- |
| NRF | 60000 | 600 | 3650 | ZLE | AIP, LKP |
| CLI | 60000 | 600 | 100 | ZTE | AAH |
| PSD | 60000 | 600 | 100 | ZTE | BPA, RFA, AFL, LKR |
| HRF | 40 | 0 | 30 | ZLE | BFL, BPR |

All have a 2048-byte buffer and allocation group 10. Source long names and
logged-data `dataId` strings are separate namespaces.

---

## g[16] -- RPC JSON node permission table

**Record stride:** 1 byte

13 bytes, followed by three alignment bytes. Each node's availability getter
at `0x0809606a` reads `g[16][object_schema.node_id]`. These are booleans, not
Air11's two-byte independent read/write permission records.

| ID | APPL schema offset | Name | Enabled |
| ---: | --- | --- | ---: |
| 0 | `0x0979dc` | CpapProfile | 1 |
| 1 | `0x097a4c` | AutoSetProfile | 1 |
| 2 | `0x097aac` | AutoSetForHerProfile | 1 |
| 3 | `0x097a6c` | ComfortFeature | 1 |
| 4 | `0x0979cc` | EprFeature | 1 |
| 5 | `0x097a0c` | CircuitFeature | 0 |
| 6 | `0x097a9c` | AutoRampFeature | 1 |
| 7 | `0x097a7c` | SmartStartStopFeature | 1 |
| 8 | `0x097a8c` | TherapyProfiles | 1 |
| 9 | `0x097a1c` | FeatureProfiles | 1 |
| 10 | `0x097a3c` | SettingProfiles | 1 |
| 11 | `0x097a5c` | ActiveProfiles | 1 |
| 12 | `0x097a2c` | MachineMetrics | 1 |

Each 16-byte object schema contains a name pointer, u32 node ID, u32 field
count and field-list pointer. Eight-byte field entries are pairs of string
pointers: public field name and a node/variable/constant reference expression.
`0x0809607c` iterates these pairs.
For CpapProfile they are `TherapyMode:CPAP`, `SetPressure:CPAP-SetPressure`,
`StartPressure:CPAP-StartPressure`.

Availability can also depend on profile-selection predicates in APPL (see
`0x0809615a` and the five predicate records at `0x096910`). The g[16] byte
is the baseline permission.

| Offset | Size | Field | Description |
|--------|-----:|-------|-------------|
| +0x00 | 1 | enabled | baseline availability for the node at this index; 0 or 1 |

### RPC node metadata

**Record stride:** 16 bytes (APPL object schema)

| Offset | Size | Field | Description |
|--------|-----:|-------|-------------|
| +0x00 | 4 | name_ptr | ptr to the node name |
| +0x04 | 4 | node_id | index into g[16] |
| +0x08 | 4 | field_count | number of field entries |
| +0x0c | 4 | fields_ptr | ptr to 8-byte field entries |

Each field entry has a name pointer at `+0x00` and a reference-expression
pointer at `+0x04`. Both point to strings; neither is an embedded DataItem value.

Example -- `CpapProfile` object schema at flash address `0x080979dc`:

| Address | Stored u32 | Meaning |
|---------|------------|---------|
| `0x080979dc` | `0x0809ff38` | pointer to `CpapProfile` |
| `0x080979e0` | `0x00000000` | node ID 0, selecting the byte at `g[16] + 0` |
| `0x080979e4` | `0x00000003` | three field entries |
| `0x080979e8` | `0x080a01e0` | pointer to the field-entry array |

The array contains these string-pointer pairs:

| Entry address | Name pointer / string | Reference pointer / string |
|---------------|-----------------------|----------------------------|
| `0x080a01e0` | `0x0809fe28` / `TherapyMode` | `0x0809fe18` / `CPAP` |
| `0x080a01e8` | `0x0809fe34` / `SetPressure` | `0x0809fe40` / `CPAP-SetPressure` |
| `0x080a01f0` | `0x0809fe54` / `StartPressure` | `0x0809fe64` / `CPAP-StartPressure` |

The CLI's `source_address` is the APPL object-schema address. `field_count`
is its `+0x08` value; `fields` joins the strings referenced by each pair.
These fields come from APPL; only `enabled` comes from the g[16] byte array.

---

## APPL long names and enum symbols

The direct long-name table at `0x046dc4` contains 332 string pointers indexed by
var ID. `0x0805d346` performs this lookup. For example ID 255 is `TherapyMode`;
ID 56 is `CPAP-SetPressure`. Names starting with `_` are preserved verbatim.
`ActiveTherapyProfile` is a separate RPC profile-selector schema at `0x097abc`,
not the canonical DataItem long name for MOP.

The enum-symbol table at `0x04651c` contains 72 twelve-byte records:
`u32 enum_index`, `u32 option_value`, `pointer symbol`. The count 72 is stored at
`0x04687c`; the lookup near `0x0805d38c` uses these roots. `enum_index` is the
**g[5] record index**, not a global var ID. Only a subset of enum slots has a
symbol in this table.

---

## Unresolved fields

| Structure | Unresolved information |
|-----------|------------------------|
| g[0] | meanings of `+0x44`, `+0x64`, `+0x74` |
| DataItem flags | complete runtime bit semantics, including bit 11 |
| g[7] | `policy_06` |
| g[10] | retention medium and recovery protocol |
| g[11] | purpose, logical count and final `0x0000` word |
| g[13] | writer flag `+0x17` and zero tail `+0x22` |
| g[15] | `file_policy` and `flag_15` semantics |
| LAN | mapping from option indices to language names |

No mode-visibility matrix, multilingual GUI-text table, STR/EDF schema roots
or numeric bounds-slot registry has been identified for this image.
