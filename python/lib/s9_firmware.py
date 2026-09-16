#!/usr/bin/env python3
"""Version-scoped S9 firmware descriptors shared by patcher and explorer.

UART IDs address typed ranges. Table A +0x1C is a separate selector,
not a UART ID. All addresses in profiles are raw-image file offsets.
"""

from __future__ import annotations

import struct
import binascii
import os
import tempfile
from decimal import Decimal, DecimalException
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


FLASH_BASE = 0x08000000
BLX_OFF = 0x00000
BID_OFF = 0x02B80
CCX_OFF = 0x03000
CCX_END = 0x20800
CDX_OFF = CCX_END
TABLE_A_STRIDE = 0x28
NAME_BUCKETS = 26
NAME_BUCKET_STRIDE = 8
NAME_ENTRY_STRIDE = 4

FLAG_BITS = {'ACT': 0x01, 'VIS': 0x02, 'EDT': 0x04, 'SGN': 0x08}


def flag_text(flags: int) -> str:
    names = [name for name, bit in FLAG_BITS.items() if flags & bit]
    if flags & ~0x0F:
        names.append(f'0x{flags & ~0x0F:02X}')
    return '|'.join(names) or '-'

EXPECTED_NAME_TAGS = {
    "AHI",
    "BID",
    "BRP",
    "FLW",
    "HID",
    "MOP",
    "MPA",
    "MPI",
    "NOS",
    "PMD",
    "PRS",
    "RAW",
    "RMT",
    "SRN",
    "STP",
    "TCE",
    "TEZ",
}


@dataclass(frozen=True)
class Profile:
    bid: str
    table_a: int
    setting_first: int
    setting_count: int
    numeric: int
    numeric_first: int
    numeric_count: int
    enum: int
    enum_first: int
    enum_count: int
    names: int

PROFILES = {
    "SX474-0907": Profile("SX525-0300", 0x5734, 0x14D, 177, 0x72DC, 9, 0x106, 0x92EC, 0x10F, 61, 0x9C40),
    "SX474-0912": Profile("SX525-0300", 0x5734, 0x156, 180, 0x7354, 9, 270, 0x940C, 0x117, 62, 0x9E58),
    "SX474-1201": Profile("SX525-0300", 0x5734, 0x156, 179, 0x732C, 9, 270, 0x93E4, 0x117, 62, 0x9E30),
    "SX474-1203": Profile("SX525-0300", 0x5734, 0x156, 180, 0x7354, 9, 270, 0x940C, 0x117, 62, 0x9E58),
    "SX474-1301": Profile("SX525-0400", 0x3500, 0x165, 247, 0x7FA4, 9, 286, 0xA44C, 0x128, 58, 0xAF30),
}
PRESSURE_NAMES = frozenset("IPC IPP EPP EEP EPS MPA MPI MNE MXI STP STE STU STV MNS MXS SPT MCP EAX EAI ANS AXS EAS EPI IVS".split())
# EDF event records are separate from the live APN/HPN stream descriptors.
EDF_EVENT_TABLES = {
    "SX474-0907": (0xAB48, 1),
    "SX474-0912": (0xAD38, 1),
    "SX474-1201": (0xAD08, 1),
    "SX474-1203": (0xAD38, 1),
    "SX474-1301": (0xBB28, 2),
}

# Live UART records, not EDF event records or scalar DataItems.
UART_STREAM_TABLES = {
    "SX474-0907": (0xA748, ("APN", "BTH", "HPN")),
    "SX474-0912": (0xA8C4, ("APN", "BTH", "HPN")),
    "SX474-1201": (0xA894, ("APN", "BTH", "HPN")),
    "SX474-1203": (0xA8C4, ("APN", "BTH", "HPN")),
    "SX474-1301": (0xB6A0, ("AAE", "APN", "BRH", "BTH", "HPN")),
}

# Literal pools of the text formatter, verified in the Thumb implementation.
# Text IDs select 8-byte records; language variants hold string IDs, which
# index a separate pointer table. These are not UART IDs or globals[] slots.
TEXT_LITERALS = {
    "SX474-0907": (0x2C3A0, 0x2C384),
    "SX474-0912": (0x2E550, 0x2E534),
    "SX474-1201": (0x2E4F8, 0x2E4DC),
    "SX474-1203": (0x2E550, 0x2E534),
    "SX474-1301": (0x37100, 0x370EC),
}
STRING_DESCRIPTOR_ROOTS = {'SX474-0907': 0xA57C, 'SX474-0912': 0xA6F4,
                           'SX474-1201': 0xA6C4, 'SX474-1203': 0xA6F4, 'SX474-1301': 0xBA00}
# (collection root/count, periodic EDF root, OXH EDF record, PDL storage record)
RECORD_ROOTS = {
    'SX474-0907': (0x9A90, 11, 0xA218, 0xABB0, 0xB124),
    'SX474-0912': (0x9BD0, 11, 0xA380, 0xAD88, 0xB33C),
    'SX474-1201': (0x9BA8, 11, 0xA354, 0xAD58, 0xB30C),
    'SX474-1203': (0x9BD0, 11, 0xA380, 0xAD88, 0xB33C),
    'SX474-1301': (0xAA98, 13, 0xB64C, 0xC034, 0xC6A8),
}
DATE_ROOTS = {'SX474-0907': 0xB360, 'SX474-0912': 0xB598, 'SX474-1201': 0xB568,
              'SX474-1203': 0xB598, 'SX474-1301': 0xC918}
LOG_ROOTS = {'SX474-0907': (0xA1B8, 3), 'SX474-0912': (0xA320, 3),
             'SX474-1201': (0xA2F4, 3), 'SX474-1203': (0xA320, 3), 'SX474-1301': (0xB420, 6)}
CALLBACK_GETTERS = {'SX474-0907': 0x8BFD4, 'SX474-0912': 0x8D94C,
                    'SX474-1201': 0x8E548, 'SX474-1203': 0x8E934, 'SX474-1301': 0x63E60}

def hx(value: Optional[int], width: int = 4) -> str:
    if value is None:
        return "-"
    return f"0x{value:0{width}X}"


def write_output(path, data, overwrite=False):
    """Publish a complete file atomically, without clobbering by default."""
    path = Path(path)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name + '.', delete=False) as handle:
            name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(name, path)
        else:
            os.link(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def parse_int(text: str) -> int:
    return int(text, 16 if text.lstrip('+-').lower().startswith('0x') else 10)


def ascii_cstr(data: bytes, off: int, limit: int = 32) -> str:
    if off < 0 or off >= len(data):
        return ""
    end = data.find(b"\0", off, min(off + limit, len(data)))
    if end < 0:
        end = min(off + limit, len(data))
    return data[off:end].decode("ascii", errors="replace")


class Flash:
    def __init__(self, path: Path, data=None):
        self.path = Path(path)
        self.data = self.path.read_bytes() if data is None else bytes(data)

    def u8(self, off: int) -> int:
        return self.data[off]

    def u16(self, off: int) -> int:
        return struct.unpack_from("<H", self.data, off)[0]

    def s16(self, off: int) -> int:
        return struct.unpack_from("<h", self.data, off)[0]

    def s32(self, off: int) -> int:
        return struct.unpack_from("<i", self.data, off)[0]

    def u32(self, off: int) -> int:
        return struct.unpack_from("<I", self.data, off)[0]

    def bytes(self, off: int, size: int) -> bytes:
        return self.data[off:off + size]

    def cstr(self, off: int, limit: int = 128, encoding: str = "utf-8") -> Optional[str]:
        if off < 0 or off >= len(self.data):
            return None
        end = self.data.find(b"\0", off, min(off + limit, len(self.data)))
        if end < 0:
            return None
        raw = self.data[off:end]
        if len(raw) > limit:
            return None
        try:
            text = raw.decode(encoding, errors="replace")
        except UnicodeError:
            return None
        if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in text):
            return None
        return text

    def ptr_to_off(self, ptr: int) -> Optional[int]:
        off = ptr - FLASH_BASE
        if 0 <= off < len(self.data):
            return off
        return None

    def is_ccx_string_ptr(self, ptr: int) -> bool:
        off = self.ptr_to_off(ptr)
        return off is not None and CCX_OFF <= off < CCX_END and self.cstr(off) is not None


@dataclass
class TableALocation:
    offset: int
    count: int
    variant: str


@dataclass
class NameEntry:
    name: str
    value: int
    off: int


@dataclass
class NameLookup:
    offset: int
    score: int
    entries: list[NameEntry]

    @property
    def by_name(self) -> dict[str, NameEntry]:
        return {entry.name: entry for entry in self.entries}

    @property
    def by_value(self) -> dict[int, list[NameEntry]]:
        out: dict[int, list[NameEntry]] = {}
        for entry in self.entries:
            out.setdefault(entry.value, []).append(entry)
        return out


@dataclass
class ConfigRecord:
    idx: int
    off: int
    raw: bytes
    default: int
    max_value: int
    min_value: int
    class_byte: int
    flags: int
    aux0e: int
    step_a: int
    step_b: int
    aux14: int
    aux16: int
    mask: int
    aux1a: int
    selector_id: int
    text0: int
    text1: int
    text2: int
    extra: int

    @classmethod
    def parse(cls, fl: Flash, idx: int, off: int) -> "ConfigRecord":
        return cls(
            idx=idx,
            off=off,
            raw=fl.bytes(off, TABLE_A_STRIDE),
            default=fl.s32(off + 0x00),
            max_value=fl.s32(off + 0x04),
            min_value=fl.s32(off + 0x08),
            class_byte=fl.u8(off + 0x0C),
            flags=fl.u8(off + 0x0D),
            aux0e=fl.u16(off + 0x0E),
            step_a=fl.s16(off + 0x10),
            step_b=fl.s16(off + 0x12),
            aux14=fl.u16(off + 0x14),
            aux16=fl.u16(off + 0x16),
            mask=fl.u32(off + 0x18),
            aux1a=fl.u16(off + 0x1A),
            selector_id=fl.u16(off + 0x1C),
            text0=fl.u16(off + 0x1E),
            text1=fl.u16(off + 0x20),
            text2=fl.u16(off + 0x22),
            extra=fl.u32(off + 0x24),
        )

    @property
    def active(self) -> bool:
        return bool(self.flags & 0x01)

    @property
    def visible_or_enabled(self) -> bool:
        return bool(self.flags & 0x02)

    @property
    def editableish(self) -> bool:
        return bool(self.flags & 0x04)

    def flag_text(self) -> str:
        return flag_text(self.flags)


class S9Firmware:
    image_size = 0x100000
    check_bootloader_id = True
    # Named regions with file offsets; end offsets are exclusive.
    regions = (('BLX', BLX_OFF, CCX_OFF), ('CCX', CCX_OFF, CCX_END),
               ('CDX', CDX_OFF, image_size))
    profiles = PROFILES
    text_literals = TEXT_LITERALS

    def __init__(self, path: Path, data=None):
        self.fl = Flash(path, data)
        self.path = Path(path)
        self.bid = ascii_cstr(self.fl.data, BID_OFF, 16)
        self.cdx_version = ascii_cstr(self.fl.data, CDX_OFF, 16)
        if len(self.fl.data) != self.image_size:
            raise ValueError("expected a 1 MiB raw S9 image")
        try:
            self.profile = self.profiles[self.cdx_version]
        except KeyError:
            raise ValueError(f"unsupported S9 CDX: {self.cdx_version!r}") from None
        if self.check_bootloader_id and self.bid != self.profile.bid:
            raise ValueError(f"unexpected BID {self.bid!r} for {self.cdx_version}")
        self.table_a = find_table_a(self.fl, self.profile)
        self.records = [ConfigRecord.parse(self.fl, i, self.table_a.offset + i * 40)
                        for i in range(self.table_a.count)]
        self.name_lookup = parse_name_lookup_at(self.fl, self.profile.names)
        if self.name_lookup is None:
            raise ValueError("invalid UART name table for this CDX")
        if len(self.name_lookup.by_name) != len(self.name_lookup.entries):
            raise ValueError("duplicate UART names")
        # Firmware literals confirm roots, independently of the UI anchor.
        for root in (self.profile.table_a, self.profile.numeric, self.profile.enum):
            if struct.pack("<I", FLASH_BASE + root) not in self.fl.data[CDX_OFF:]:
                raise ValueError(f"missing CDX reference to descriptor root 0x{root:X}")
        self.sentinel_text_id = (0xDF if self.cdx_version == 'SX474-1301' else
                                 0xB5 if self.cdx_version == 'SX474-0905' else 0xB6)
        self.pressure_unit_id = self.fl.u16(self.resolve('IPC').off + 30)

    def uart_id_for(self, rec: ConfigRecord) -> int:
        return self.profile.setting_first + rec.idx

    def record_names(self, rec: ConfigRecord) -> list[str]:
        return self.names_for_value(self.uart_id_for(rec))

    def resolve(self, ident: str | int):
        if isinstance(ident, str):
            entry = self.name_entry(ident)
            if entry is None:
                raise ValueError(f"unknown UART name: {ident}")
            vid = entry.value
        else:
            vid = ident
        p = self.profile
        if 0 <= vid < 9:
            root = STRING_DESCRIPTOR_ROOTS[self.cdx_version]
            if struct.pack('<I', FLASH_BASE + root) not in self.fl.data[CDX_OFF:]:
                raise ValueError('missing CDX reference to string descriptor table')
            return StringDescriptor(self.fl, vid, vid, root + vid * 6)
        if self.cdx_version == 'SX474-1301' and vid == 0x127:
            if self.fl.u32(0x380BC) != FLASH_BASE + 0xC078:
                raise ValueError('invalid bitfield descriptor root')
            return Descriptor(self.fl, 'bitfield', vid, 0, 0xC078, 16)
        for idx, name in enumerate(('DAC', 'TIC')):
            if self.name_entry(name).value == vid:
                root = DATE_ROOTS[self.cdx_version]
                if struct.pack('<I', FLASH_BASE + root) not in self.fl.data[CDX_OFF:]:
                    raise ValueError('missing CDX reference to date descriptor')
                return StringDescriptor(self.fl, vid, idx, root + 4 * idx, 'date' if idx == 0 else 'time', 4)
        for kind, first, count, root, stride in (
            ("setting", p.setting_first, p.setting_count, p.table_a, 40),
            ("numeric", p.numeric_first, p.numeric_count, p.numeric, 20),
            ("enum", p.enum_first, p.enum_count, p.enum, 16),
        ):
            if first <= vid < first + count:
                return Descriptor(self.fl, kind, vid, vid - first, root + (vid - first) * stride, stride)
        root, names = UART_STREAM_TABLES[self.cdx_version]
        for idx, name in enumerate(names):
            entry = self.name_entry(name)
            if entry is not None and entry.value == vid:
                return self._stream_descriptor(vid, idx, root, name)
        for record in self.records_by_type():
            if vid == record.uart_id:
                return record
        for row in self.edf_events():
            if self.name_entry(row['name']).value == vid:
                return RecordDescriptor(self.fl, vid, (row['off'] - EDF_EVENT_TABLES[self.cdx_version][0]) // 24, row['off'], 'edf-event', 24,
                                        row['field_ids'], row['fields_off'], row)
        if self.name_entry('STR').value == vid:
            root = self.str_root
            fields = tuple(r['uart_id'] for r in self.str_fields())
            return RecordDescriptor(self.fl, vid, 0, root, 'edf-str', 36, fields,
                                    self.fl.u32(root + 20) - FLASH_BASE, {})
        raise ValueError(f"UART ID 0x{vid:04X}: descriptor kind not implemented")

    def records_by_type(self):
        root, count, periodic, oxh, storage = RECORD_ROOTS[self.cdx_version]
        out = []
        logs, log_count = LOG_ROOTS[self.cdx_version]
        layouts = [
            ('collection', [root + i * 20 for i in range(count)], 1, 0, 8, 20),
            ('edf-periodic', [periodic + i * 28 for i in range(3)] + [oxh], 9, 8, 16, 28),
            ('storage', [storage], 0, 8, 4, 12),
            ('log', [logs + i * 24 for i in range(log_count)], 0, 8, 4, 24),
        ]
        if self.cdx_version in ('SX474-0912', 'SX474-1201', 'SX474-1203'):
            root = 0xA6FC if self.cdx_version == 'SX474-1201' else 0xA72C
            layouts.append(('recorded-series', [root, root + 28], 17, 16, 24, 28))
            root = 0xAC14 if self.cdx_version == 'SX474-1201' else 0xAC44
            layouts.append(('recorded-event', [root], 13, 12, 20, 28))
        for kind, offsets, name_field, count_field, fields_field, stride in layouts:
            for idx, off in enumerate(offsets):
                name = ascii_cstr(self.fl.data, off + name_field, 4)
                entry = self.name_entry(name)
                if entry is None or self.fl.u8(off + name_field + 3) != 0:
                    raise ValueError(f'{kind}: invalid record name at 0x{off:X}')
                n = self.fl.u32(off + count_field) if kind == 'storage' else self.fl.u8(off + count_field)
                if not 0 < n <= 255:
                    raise ValueError(f'{name}: invalid field count {n}')
                fields = self.ccx_pointer(self.fl.u32(off + fields_field), n * 2, 2)
                ids = struct.unpack_from(f'<{n}H', self.fl.data, fields)
                # Field references are scalar/string IDs. Validate without
                # recursively dispatching other record tables.
                allowed = set(self.scalar_ids()) | set(range(9)) | {self.name_entry(n).value for n in ('DAC', 'TIC')}
                if any(vid not in allowed for vid in ids):
                    raise ValueError(f'{name}: field outside DataItem namespaces')
                extra = {}
                if kind in ('collection', 'edf-periodic'):
                    fmt_field = 12 if kind == 'collection' else 20
                    formats = self.ccx_pointer(self.fl.u32(off + fmt_field), n * 2, 2)
                    extra['formats_off'] = formats
                    extra['field_formats'] = struct.unpack_from(f'<{n}H', self.fl.data, formats)
                    extra['format'] = self.fl.u32(off + stride - 4)
                if kind == 'edf-periodic':
                    extra['enabled'] = self.fl.u32(off + 4)
                if kind == 'log':
                    extra['trigger_id'] = self.fl.u16(off + 10)
                    extra['metadata'] = self.fl.bytes(off + 9, 15).hex()
                if kind == 'recorded-series':
                    extra['period'] = self.fl.u32(off + 8)
                    extra['duration'] = self.fl.u32(off + 12)
                    extra['metadata'] = self.fl.bytes(off, 8).hex()
                if kind == 'recorded-event':
                    extra['trigger_id'] = self.fl.u16(off + 24)
                    extra['metadata'] = self.fl.bytes(off, 12).hex()
                out.append(RecordDescriptor(self.fl, entry.value, 0 if off == oxh else idx, off, kind, stride, ids, fields, extra))
        return out

    def _stream_descriptor(self, vid, idx, root, name):
        data = self.fl.data
        if struct.pack('<I', FLASH_BASE + root) not in data[CDX_OFF:]:
            raise ValueError('missing CDX reference to UART stream table')
        off = root + idx * 16
        if data[off + 1:off + 5] != name.encode('ascii') + b'\0':
            raise ValueError(f'{name}: unexpected UART stream name')
        count = self.fl.u8(off)
        fields = self.fl.u32(off + 8) - FLASH_BASE
        if not 0 < count <= 127 or fields % 2 or not CCX_OFF <= fields <= CCX_END - count * 2:
            raise ValueError(f'{name}: invalid UART stream field list')
        ids = struct.unpack_from(f'<{count}H', data, fields)
        trigger = self.fl.u16(off + 12)
        p = self.profile
        for item in (*ids, trigger):
            if not any(first <= item < first + size for first, size in (
                (p.numeric_first, p.numeric_count), (p.enum_first, p.enum_count),
                (p.setting_first, p.setting_count),
            )):
                raise ValueError(f'{name}: unsupported field/trigger UART ID 0x{item:04X}')
        return StreamDescriptor(self.fl, vid, idx, off, tuple(ids), trigger,
                                self.fl.u8(off + 14), fields)

    def respiratory_record_offset(self) -> int:
        """Resolve and validate the EVE recorder, including its UART fields."""
        root, count = EDF_EVENT_TABLES[self.cdx_version]
        data = self.fl.data
        if struct.pack('<I', FLASH_BASE + root) not in data[CDX_OFF:]:
            raise ValueError('missing CDX reference to EDF event table')
        matches = [root + i * 24 for i in range(count)
                   if data[root + i * 24 + 8:root + i * 24 + 12] == b'\x03EVE']
        if len(matches) != 1:
            raise ValueError('expected exactly one EVE recording descriptor')
        off = matches[0]
        if data[off + 2] != 1 or data[off + 4] not in (0, 1):
            raise ValueError('unexpected EVE recorder initialization flags')
        fields = self.fl.u32(off + 16) - FLASH_BASE
        if not CCX_OFF <= fields <= CCX_END - 6:
            raise ValueError('EVE field list outside CCX')
        expected = tuple(self.resolve(n).uart_id for n in ('ETI', 'DUR', 'AET'))
        if struct.unpack_from('<3H', data, fields) != expected:
            raise ValueError('unexpected EVE fields; expected ETI/DUR/AET')
        if self.fl.u16(off + 20) != self.resolve('APT').uart_id:
            raise ValueError('unexpected EVE trigger; expected APT')
        if data[off + 22:off + 24] != b'\x03\x01':
            raise ValueError('unexpected EVE record format')
        return off

    def record_by_selector(self, selector_id: int) -> list[ConfigRecord]:
        return [rec for rec in self.records if rec.selector_id == selector_id]

    def record_by_index(self, idx: int) -> ConfigRecord:
        if not 0 <= idx < len(self.records):
            raise ValueError("Table A index out of range")
        return self.records[idx]

    def names_for_value(self, value: int) -> list[str]:
        if self.name_lookup is None:
            return []
        return sorted(entry.name for entry in self.name_lookup.by_value.get(value, []))

    def name_entry(self, name: str) -> Optional[NameEntry]:
        if self.name_lookup is None:
            return None
        return self.name_lookup.by_name.get(name.upper())

    def ccx_pointer(self, pointer: int, size: int, alignment: int = 1) -> int:
        off = pointer - FLASH_BASE
        if off % alignment or size < 0 or not CCX_OFF <= off <= CCX_END - size:
            raise ValueError(f"invalid CCX pointer 0x{pointer:08X} (size {size})")
        return off

    @property
    def text_layout(self):
        record_literal, string_literal = self.text_literals[self.cdx_version]
        root = self.ccx_pointer(self.fl.u32(record_literal), 8, 4)
        expected = self.profile.numeric + self.profile.numeric_count * 20
        if root != expected:
            raise ValueError("text record root disagrees with CDX profile")
        strings = self.ccx_pointer(self.fl.u32(string_literal), 4, 4)
        count = (self.profile.enum - root) // 8
        return root, count, strings

    @property
    def text_languages(self):
        # The language selector reserves variant zero for English even when
        # LAN bit zero is disabled; subsequent variants follow enabled bits.
        lan = self.resolve('LAN')
        return (0, *(i for i in range(1, lan.option_count) if lan.mask & (1 << i)))

    def string(self, string_id: int) -> str:
        if string_id < 0:
            raise ValueError("string ID must be nonnegative")
        _, _, base = self.text_layout
        slot = self.ccx_pointer(FLASH_BASE + base + 4 * string_id, 4, 4)
        off = self.ccx_pointer(self.fl.u32(slot), 1)
        end = self.fl.data.find(b'\0', off, CCX_END)
        if end < 0:
            raise ValueError(f"unterminated string ID {string_id}")
        # The display font uses bytes outside ASCII; retain undecodable bytes
        # explicitly instead of silently replacing them with identical U+FFFD.
        return self.fl.data[off:end].decode('utf-8', errors='backslashreplace')

    def text_record(self, text_id: int, language: int = 0):
        root, count, _ = self.text_layout
        if not 0 <= text_id < count:
            raise ValueError(f"text ID {text_id} outside 0..{count - 1}")
        languages = self.text_languages
        if language not in languages:
            raise ValueError(f"language {language} unavailable; available LAN values: {languages}")
        off = root + text_id * 8
        variants = self.ccx_pointer(self.fl.u32(off + 4), len(languages) * 2, 2)
        string_id = self.fl.u16(variants + 2 * languages.index(language))
        return {'id': text_id, 'off': off, 'metadata': self.fl.u32(off),
                'variants_off': variants, 'language': language, 'string_id': string_id,
                'text': self.string(string_id)}

    def text(self, text_id: int, language: int = 0) -> str:
        return self.text_record(text_id, language)['text']

    def options(self, ident, language: int = 0):
        rec = self.resolve(ident)
        if rec.option_count is None:
            raise ValueError("variable has no enumerated options")
        base = self.fl.u16(rec.off + (14 if rec.kind == 'bitfield' else 10 if rec.kind == 'enum' else 30))
        return [{'value': i, 'enabled': bool(rec.mask & (1 << i)),
                 'text_id': base if base == self.sentinel_text_id else base + i,
                 'text': self.text(base if base == self.sentinel_text_id else base + i, language)}
                for i in range(rec.option_count)]

    def scalar_ids(self):
        p = self.profile
        return (*range(p.numeric_first, p.numeric_first + p.numeric_count),
                *range(p.enum_first, p.enum_first + p.enum_count),
                *range(p.setting_first, p.setting_first + p.setting_count))

    def data_item_ids(self):
        return (*range(9), *self.scalar_ids(),
                *((0x127,) if self.cdx_version == 'SX474-1301' else ()),
                self.name_entry('DAC').value, self.name_entry('TIC').value)

    def references(self, ident):
        vid = self.resolve(ident).uart_id
        out = []
        for record in self.records_by_type():
            for idx, field in enumerate(record.field_ids):
                if field == vid:
                    out.append((record.kind, '/'.join(self.names_for_value(record.uart_id)), idx, record.fields_offset + idx * 2))
        root, names = UART_STREAM_TABLES[self.cdx_version]
        for name in names:
            rec = self.resolve(name)
            for idx, field in enumerate(rec.field_ids):
                if field == vid:
                    out.append(('uart-field', name, idx, rec.fields_offset + idx * 2))
            if rec.trigger_id == vid:
                out.append(('uart-trigger', name, None, rec.off + 12))
        for rec in self.edf_events():
            for idx, field in enumerate(rec['field_ids']):
                if field == vid:
                    out.append(('event-field', rec['name'], idx, rec['fields_off'] + idx * 2))
            if rec['trigger_id'] == vid:
                out.append(('event-trigger', rec['name'], None, rec['off'] + 20))
        for row in self.str_fields():
            if row['uart_id'] == vid:
                out.append(('STR-output', 'STR', row['index'], row['calculation_off']))
            if row['source_id'] == vid:
                out.append(('STR-source', 'STR', row['index'], row['calculation_off'] + 2))
        if self.resolve(vid).kind == 'setting':
            for source in range(self.profile.setting_first, self.profile.setting_first + self.profile.setting_count):
                for row in self.dependency_chain(source):
                    if row['target_id'] == vid:
                        out.append(('dependency-target', '/'.join(self.names_for_value(source)) or hx(source), row['index'], row['off']))
        return out

    def label(self, ident, language=0):
        rec = self.resolve(ident)
        if rec.kind not in ('setting', 'numeric', 'enum', 'string', 'bitfield', 'date', 'time'):
            return '/'.join(self.names_for_value(rec.uart_id))
        field = {'setting': 36, 'numeric': 18, 'enum': 12, 'string': 4, 'bitfield': 12, 'date': 2, 'time': 2}[rec.kind]
        return self.text(self.fl.u16(rec.off + field), language)

    def dependency_chain(self, ident):
        rec = self.resolve(ident)
        if rec.kind != 'setting':
            return []
        root, count = (0x5B98, 769) if self.cdx_version == 'SX474-1301' else (0x3400, 751)
        if struct.pack('<I', FLASH_BASE + root) not in self.fl.data[CDX_OFF:]:
            raise ValueError('missing CDX reference to dependency table')
        idx = self.fl.s16(rec.off + 28)
        if idx == 0x7FFF:
            return []
        out = []
        while True:
            if not 0 <= idx < count:
                raise ValueError('dependency chain outside table or missing terminator')
            off = root + idx * 12
            target = self.fl.u8(off + 1)
            if target >= self.profile.setting_count:
                raise ValueError('dependency target outside setting table')
            condition = self.fl.u32(off + 4)
            if condition:
                self.ccx_pointer(condition, 1)
            out.append({'index': idx, 'off': off, 'opcode': self.fl.u8(off),
                        'target_id': self.profile.setting_first + target,
                        'condition': condition, 'callback': self.fl.u8(off + 8),
                        'conditions': self.conditions(condition),
                        'operand': self.fl.u16(off + 2),
                        'callback_address': self.callback_address(self.fl.u8(off + 8)) if self.fl.u8(off) in self.callback_operations else None,
                        'continuation': self.fl.u8(off + 9),
                        'raw': self.fl.bytes(off, 12).hex()})
            if not self.fl.u8(off + 9):
                return out
            idx += 1

    @property
    def callback_operations(self):
        base = 21 if self.cdx_version == 'SX474-1301' else 18
        return {base: 'set-upper-bound', base + 1: 'set-lower-bound', base + 2: 'set-value'}

    def callback_address(self, index):
        getter = CALLBACK_GETTERS[self.cdx_version]
        if self.fl.bytes(getter, 8) != bytes.fromhex('014951f820007047'):
            raise ValueError('dependency callback getter signature mismatch')
        root = self.fl.u32(getter + 8) - FLASH_BASE
        slot = root + index * 4
        if not CDX_OFF <= slot <= len(self.fl.data) - 4:
            raise ValueError('dependency callback slot outside CDX')
        address = self.fl.u32(slot)
        if not address & 1 or not FLASH_BASE + CDX_OFF <= address < FLASH_BASE + len(self.fl.data):
            raise ValueError('dependency callback is not a Thumb code address')
        return address

    def conditions(self, pointer):
        """OR of groups, each an AND of inclusive setting-value intervals.

        1301 0803A504 / 1201 08030F84: group stride 8, clause stride 16;
        nonzero bytes at group +4 and clause +12 terminate their lists.
        """
        if pointer == 0:
            return []
        group_off = self.ccx_pointer(pointer, 8, 4)
        groups = []
        while True:
            self.ccx_pointer(FLASH_BASE + group_off, 8, 4)
            clause_off = self.ccx_pointer(self.fl.u32(group_off), 16, 4)
            clauses = []
            while True:
                self.ccx_pointer(FLASH_BASE + clause_off, 16, 4)
                idx = self.fl.u8(clause_off)
                if idx >= self.profile.setting_count:
                    raise ValueError('condition setting index outside Table A')
                clauses.append({'off': clause_off, 'uart_id': self.profile.setting_first + idx,
                                'min': self.fl.s32(clause_off + 8), 'max': self.fl.s32(clause_off + 4)})
                if self.fl.u8(clause_off + 12):
                    break
                clause_off += 16
            groups.append(clauses)
            if self.fl.u8(group_off + 4):
                return groups
            group_off += 8

    def condition_text(self, groups):
        if not groups:
            return 'true'
        def term(clause):
            name = '/'.join(self.names_for_value(clause['uart_id'])) or hx(clause['uart_id'])
            lo, hi = clause['min'], clause['max']
            return f'{name} == {lo}' if lo == hi else f'{lo} <= {name} <= {hi}'
        return ' OR '.join('(' + ' AND '.join(term(c) for c in group) + ')' for group in groups)

    def mode_rules(self, mode=None):
        mop = self.resolve('MOP').uart_id
        out = []
        for source in range(self.profile.setting_first, self.profile.setting_first + self.profile.setting_count):
            for rule in self.dependency_chain(source):
                groups = rule['conditions']
                if not any(c['uart_id'] == mop for group in groups for c in group):
                    continue
                if mode is not None and not any(all(c['uart_id'] != mop or c['min'] <= mode <= c['max'] for c in group) for group in groups):
                    continue
                out.append((source, rule))
        return out

    def edf_events(self):
        root, count = EDF_EVENT_TABLES[self.cdx_version]
        out = []
        for i in range(count):
            off = root + i * 24
            if self.fl.u8(off + 2) != 1 or self.fl.u8(off + 4) not in (0, 1):
                raise ValueError('invalid EDF event flags')
            n = self.fl.u8(off + 8)
            fields = self.ccx_pointer(self.fl.u32(off + 16), n * 2, 2)
            ids = struct.unpack_from(f'<{n}H', self.fl.data, fields)
            trigger = self.fl.u16(off + 20)
            allowed = set(self.data_item_ids())
            if any(vid not in allowed for vid in (*ids, trigger)):
                raise ValueError('EDF event field/trigger outside DataItem namespaces')
            out.append({'name': ascii_cstr(self.fl.data, off + 9, 4), 'off': off,
                        'enabled': bool(self.fl.u8(off + 4)), 'field_ids': ids,
                        'trigger_id': trigger, 'fields_off': fields,
                        'format': self.fl.bytes(off + 22, 2).hex()})
        return out

    @property
    def str_root(self):
        return {'SX474-0907': 0xA830, 'SX474-0912': 0xAA08,
                'SX474-1201': 0xA9D8, 'SX474-1203': 0xAA08,
                'SX474-1301': 0xBC50}[self.cdx_version]

    def str_fields(self):
        root = self.str_root
        if self.fl.bytes(root + 13, 4) != b'STR\0':
            raise ValueError('invalid STR descriptor name')
        count = self.fl.u8(root + 12)
        if not count:
            raise ValueError('empty STR field list')
        fields = self.ccx_pointer(self.fl.u32(root + 20), count * 2, 2)
        formats = self.ccx_pointer(self.fl.u32(root + 24), count * 2, 2)
        calcs = self.ccx_pointer(self.fl.u32(root + 32), count * 6, 2)
        out = []
        for i in range(count):
            vid = self.fl.u16(fields + i * 2)
            if vid not in self.data_item_ids():
                raise ValueError('STR field outside DataItem namespaces')
            off = calcs + i * 6
            opcode, kind, source, arg, flags = struct.unpack_from('<BBhbB', self.fl.data, off)
            out.append({'index': i, 'uart_id': vid, 'samples': self.fl.u16(formats + i * 2),
                        'calculation_off': off, 'opcode': opcode, 'kind': kind,
                        'source_id': source, 'argument': arg, 'flags': flags})
        return out

    def scale_for(self, rec: ConfigRecord) -> Optional[tuple[int, str]]:
        desc = self.resolve(self.uart_id_for(rec))
        if desc.option_count is not None:
            return None
        divisor = self.divisor(desc)
        unit = self.text(self.fl.u16(desc.off + 30))
        return (divisor, unit) if divisor != 1 or unit else None

    def divisor(self, rec):
        if rec.option_count is not None:
            return 1
        field = 14 if rec.kind == 'numeric' else (20 if self.cdx_version == 'SX474-1301' else 18)
        value = self.fl.u16(rec.off + field)
        return value or 1

    def editable_fields(self, ident):
        rec = self.resolve(ident)
        if rec.kind in ('string', 'date', 'time'):
            return {'flags': (0, 'B'), 'label': (4 if rec.kind == 'string' else 2, 'H')}
        if rec.kind not in ('setting', 'numeric', 'enum', 'bitfield'):
            raise ValueError(f'{rec.kind} has no editable scalar fields')
        fields = {'default': (0, 'B' if rec.kind == 'enum' else 'I' if rec.kind == 'bitfield' else 'i'),
                  'flags': (rec.flags_offset - rec.off, 'B'),
                  'label': ({'setting': 36, 'numeric': 18, 'enum': 12, 'bitfield': 12}[rec.kind], 'H')}
        if rec.option_count is None:
            fields.update(min=(8, 'i'), max=(4, 'i'),
                          scale=(14 if rec.kind == 'numeric' else (20 if self.cdx_version == 'SX474-1301' else 18), 'H'),
                          unit=(16 if rec.kind == 'numeric' else 30, 'H'))
        else:
            fields.update(mask=(4 if rec.kind in ('enum', 'bitfield') else 24, 'I'),
                          options_text=(14 if rec.kind == 'bitfield' else 10 if rec.kind == 'enum' else 30, 'H'))
        return fields

    def edited(self, assignments, ignore_input_crc=False):
        invalid = self.invalid_crcs()
        if invalid and not ignore_input_crc:
            raise ValueError('invalid input CRC: ' + ', '.join(invalid))
        data, changes, touched, occupied, scaled = bytearray(self.fl.data), [], {}, set(), set()
        for assignment in assignments:
            try:
                lhs, value = assignment.split('=', 1)
                ident, field = lhs.rsplit('.', 1)
            except ValueError:
                raise ValueError(f'expected VAR.FIELD=VALUE: {assignment}') from None
            ident = parse_int(ident) if ident[:1].isdigit() else ident.removeprefix('_').upper()
            rec = self.resolve(ident)
            raw = field.endswith('_raw')
            field = field.removesuffix('_raw')
            fields = self.editable_fields(ident)
            if field not in fields:
                raise ValueError(f'{ident}: unknown field {field}; editable: {", ".join(fields)}')
            if raw and field not in ('default', 'min', 'max'):
                raise ValueError('_raw applies only to default/min/max')
            relative, fmt = fields[field]
            off, size = rec.off + relative, struct.calcsize('<' + fmt)
            if occupied.intersection(range(off, off + size)):
                raise ValueError(f'duplicate or overlapping edit: {lhs}')
            occupied.update(range(off, off + size))
            if field == 'flags' and any(c.isalpha() for c in value) and not value.lower().startswith('0x'):
                number = 0
                for flag in value.upper().split('|'):
                    if flag not in FLAG_BITS:
                        raise ValueError(f'unknown S9 flag: {flag}')
                    number |= FLAG_BITS[flag]
            else:
                try:
                    number = Decimal(int(value, 0)) if value.lower().startswith(('0x', '-0x', '+0x')) else Decimal(value)
                    if field in ('default', 'min', 'max') and not raw:
                        number *= self.divisor(rec)
                        scaled.add(rec.uart_id)
                    if not number.is_finite() or number != number.to_integral_value():
                        raise ValueError(f'{lhs}: value is not exactly representable')
                    lo, hi = {'B': (0, 255), 'H': (0, 65535), 'I': (0, 0xffffffff), 'i': (-0x80000000, 0x7fffffff)}[fmt]
                    if not lo <= number <= hi:
                        raise ValueError(f'{lhs}: value outside {fmt} storage range')
                    number = int(number)
                except (DecimalException, OverflowError):
                    raise ValueError(f'{lhs}: invalid number {value!r}') from None
            try:
                encoded = struct.pack('<' + fmt, number)
            except struct.error:
                raise ValueError(f'{lhs}: value outside {fmt} storage range') from None
            if field in ('label', 'unit', 'options_text'):
                self.text(number)
                if field == 'options_text':
                    self.text(number + rec.option_count - 1)
            if field == 'scale' and number == 0:
                raise ValueError('scale must be positive')
            if field == 'mask' and number >> rec.option_count:
                raise ValueError('mask contains bits outside declared options')
            old = struct.unpack_from('<' + fmt, data, off)[0]
            data[off:off + size] = encoded
            changes.append(f'{lhs}: {old} -> {number} (stored, off=0x{off:05X})')
            touched.setdefault(rec.uart_id, set()).add(field)
        candidate = S9Firmware(self.path, data)
        for vid, fields in touched.items():
            if 'scale' in fields and vid in scaled:
                raise ValueError('use _raw values when changing scale in the same transaction')
            rec = candidate.resolve(vid)
            if fields.intersection(('default', 'min', 'max')) and not rec.min_value <= rec.default <= rec.max_value:
                raise ValueError(f'{vid:#x}: require min <= default <= max')
            if rec.kind == 'bitfield' and fields.intersection(('mask', 'default')) and rec.default & ~rec.mask:
                raise ValueError(f'{vid:#x}: default has bits outside mask')
            if rec.kind != 'bitfield' and rec.option_count is not None and fields.intersection(('mask', 'default')) and not (rec.mask & (1 << rec.default)):
                raise ValueError(f'{vid:#x}: default option is disabled by mask')
        crc = binascii.crc_hqx(data[CCX_OFF:CCX_END - 2], 0xFFFF)
        struct.pack_into('>H', data, CCX_END - 2, crc)
        if binascii.crc_hqx(data[CCX_OFF:CCX_END], 0xFFFF):
            raise ValueError('output CCX CRC verification failed')
        return bytes(data), changes

    def invalid_crcs(self):
        return [name for name, start, end in self.regions
                if binascii.crc_hqx(self.fl.data[start:end], 0xFFFF)]

    def format_value(self, rec: ConfigRecord, value: int) -> str:
        scale = self.scale_for(rec)
        if not scale:
            return str(value)
        divisor, unit = scale
        return f"{value / divisor:g} {unit}"

    def text_ref_ids(self, field: str = "all") -> list[int]:
        out = []
        for rec in self.records:
            if field in ("all", "text0"):
                out.append(rec.text0)
            if field in ("all", "text1"):
                out.append(rec.text1)
            if field in ("all", "text2"):
                out.append(rec.text2)
            if field in ("all", "extra"):
                out.append(rec.extra & 0xFFFF)
        return [v for v in out if v not in (0, 0xFFFF, 0x7FFF)]

    def string_at_text_base(self, base: int, ref_id: int) -> Optional[str]:
        ptr_off = base + ref_id * 4
        if not (CCX_OFF <= ptr_off <= min(CCX_END, len(self.fl.data)) - 4):
            return None
        ptr = self.fl.u32(ptr_off)
        if not self.fl.is_ccx_string_ptr(ptr):
            return None
        str_off = self.fl.ptr_to_off(ptr)
        return self.fl.cstr(str_off) if str_off is not None else None

def find_table_a(fl: Flash, profile=None) -> TableALocation:
    version = ascii_cstr(fl.data, CDX_OFF, 16)
    if profile is None and version not in PROFILES:
        raise ValueError(f"unsupported S9 CDX: {version!r}")
    p = profile if profile is not None else PROFILES[version]
    checks = ((0, 0x7FFF), (1, 0x7FFF), (2, 1)) if version == "SX474-1301" else ((0, 0x7FFF), (2, 0), (3, 2))
    if any(fl.u16(p.table_a + idx * 40 + 0x1C) != val for idx, val in checks):
        raise ValueError("Table A anchor does not match the CDX profile")
    return TableALocation(p.table_a, p.setting_count, "13xx" if version == "SX474-1301" else "std")


def is_name_char(value: int) -> bool:
    return ord("A") <= value <= ord("Z") or ord("0") <= value <= ord("9")


def parse_name_lookup_at(fl: Flash, off: int) -> Optional[NameLookup]:
    if off < 0 or off + NAME_BUCKETS * NAME_BUCKET_STRIDE > len(fl.data):
        return None

    entries: list[NameEntry] = []
    nonempty = 0
    for bucket in range(NAME_BUCKETS):
        bucket_off = off + bucket * NAME_BUCKET_STRIDE
        ptr = fl.u32(bucket_off)
        count = fl.u8(bucket_off + 4)
        if fl.bytes(bucket_off + 5, 3) != b"\0\0\0":
            return None
        if count == 0:
            if ptr != 0:
                return None
            continue
        if count > 128:
            return None
        entry_off = fl.ptr_to_off(ptr)
        if entry_off is None or entry_off < CCX_OFF or entry_off + count * NAME_ENTRY_STRIDE > CCX_END:
            return None
        nonempty += 1
        first = chr(ord("A") + bucket)
        for idx in range(count):
            item_off = entry_off + idx * NAME_ENTRY_STRIDE
            char2 = fl.u8(item_off)
            char3 = fl.u8(item_off + 1)
            if not is_name_char(char2) or not is_name_char(char3):
                return None
            value = fl.s16(item_off + 2)
            if value < 0 or value >= 0x7FFF:
                return None
            entries.append(NameEntry(first + chr(char2) + chr(char3), value, item_off))

    names = {entry.name for entry in entries}
    expected_hits = len(names & EXPECTED_NAME_TAGS)
    if len(entries) < 100 or nonempty < 12 or expected_hits < 6:
        return None

    score = len(entries) + nonempty + expected_hits * 10
    if len(names) != len(entries):
        score -= len(entries) - len(names)
    return NameLookup(off, score, entries)


def find_name_lookup(fl: Flash) -> Optional[NameLookup]:
    candidates = []
    for off in range(0, len(fl.data) - NAME_BUCKETS * NAME_BUCKET_STRIDE, 4):
        candidate = parse_name_lookup_at(fl, off)
        if candidate is not None:
            candidates.append(candidate)
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError("ambiguous UART resolver")
    return candidates[0]



@dataclass(frozen=True)
class RecordDescriptor:
    fl: Flash
    uart_id: int
    idx: int
    off: int
    kind: str
    stride: int
    field_ids: tuple
    fields_offset: int
    metadata: dict
    default = min_value = max_value = flags = flags_offset = mask = option_count = active = None

    @property
    def raw(self):
        return self.fl.bytes(self.off, self.stride)


@dataclass(frozen=True)
class StringDescriptor:
    fl: Flash
    uart_id: int
    idx: int
    off: int
    kind: str = 'string'
    stride: int = 6
    default = min_value = mask = option_count = None

    @property
    def max_value(self):
        return self.fl.u16(self.off + 2) if self.kind == 'string' else None
    @property
    def flags_offset(self):
        return self.off
    @property
    def flags(self):
        return self.fl.u8(self.off)
    @property
    def active(self):
        return bool(self.flags & 1)
    @property
    def raw(self):
        return self.fl.bytes(self.off, self.stride)


@dataclass(frozen=True)
class StreamDescriptor:
    fl: Flash
    uart_id: int
    idx: int
    off: int
    field_ids: tuple[int, ...]
    trigger_id: int
    format_code: int
    fields_offset: int
    kind: str = "stream"
    stride: int = 16
    # Scalar properties do not apply to records. In particular, +8 is a
    # pointer, not an ACT/flags byte, and +0 is a count, not a default.
    default: None = None
    min_value: None = None
    max_value: None = None
    flags: None = None
    flags_offset: None = None
    mask: None = None
    option_count: None = None
    active: None = None

    @property
    def raw(self):
        return self.fl.bytes(self.off, self.stride)


@dataclass(frozen=True)
class Descriptor:
    fl: Flash
    kind: str
    uart_id: int
    idx: int
    off: int
    stride: int

    @property
    def raw(self):
        return self.fl.bytes(self.off, self.stride)
    @property
    def default(self):
        return self.fl.u8(self.off) if self.kind == "enum" else self.fl.u32(self.off) if self.kind == 'bitfield' else self.fl.s32(self.off)
    @property
    def flags_offset(self):
        return self.off + {"setting": 13, "numeric": 12, "enum": 8, 'bitfield': 9}[self.kind]
    @property
    def flags(self):
        return self.fl.u8(self.flags_offset)
    @property
    def active(self):
        return bool(self.flags & 1)
    @property
    def min_value(self):
        return 0 if self.option_count is not None else self.fl.s32(self.off + 8)
    @property
    def max_value(self):
        count = self.option_count
        if self.kind == 'bitfield':
            return (1 << count) - 1
        return count - 1 if count is not None else self.fl.s32(self.off + 4)
    @property
    def option_count(self):
        if self.kind == 'bitfield':
            return self.fl.u8(self.off + 8)
        if self.kind == "enum":
            return self.fl.u8(self.off + 1)
        if self.kind == "setting" and self.fl.u8(self.off + 12) & 31 == 1:
            # 1301 inserts two bytes before the display/option-count fields.
            field = 22 if ascii_cstr(self.fl.data, CDX_OFF, 16) == "SX474-1301" else 20
            return self.fl.u8(self.off + field)
        return None
    @property
    def mask(self):
        if self.kind in ("enum", 'bitfield'):
            return self.fl.u32(self.off + 4)
        if self.kind == "setting" and self.option_count is not None:
            return self.fl.u32(self.off + 24)
        return None
