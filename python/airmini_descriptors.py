#!/usr/bin/env python3
"""Offline CONF explorer and scalar descriptor editor for AirMini 4.0.3.50927.

Uses only the standard library. Offsets and APPL signatures are deliberately
version-specific; see docs/airmini/conf_block_format.md for the evidence.
"""

import argparse
import binascii
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import io
import os
import re
import shlex
import tempfile
from pathlib import Path
import struct
import sys


FLASH_BASE = 0x08000000
CONF_BASE = 0x20000
CONF_END = 0x40000
GLOBALS_OFFSET = 0x20108
IMAGE_SIZE = 0x100000
APP_VERSION = "4.0.3.50927"
MAX_VAR_ID = 0x14B

# Checked against the factory's range mappers at 0x0805bf8c..0x0805bfda.
FACTORY_OFFSET = 0x5BF8C
FACTORY_SIGNATURE = bytes.fromhex(
    "b0f11e0189b2d82902d347f6ff7000e01e3800b27047"
    "b0f1f60189b2092902d347f6ff7000e0f63800b27047"
    "b0f1ff0189b23d2902d347f6ff7000e0ff3800b27047"
    "00b21e2801db47f6ff7000b27047"
)


@dataclass(frozen=True)
class Root:
    offset: int
    kind: str
    count: int | None = None
    stride: int | None = None
    id_base: int | None = None


ROOTS = (
    Root(0x20000, "conf_header", 1, 256),
    Root(0x20840, "volatile_text_descriptors", 30, 10, 0),
    Root(0x2096C, "numeric_descriptors", 216, 28, 30),
    Root(0x2210C, "bitfield_descriptors", 9, 20, 246),
    Root(0x221C0, "bitfield_selection_order"),
    Root(0x22208, "enum_descriptors", 61, 16, 255),
    Root(0x225D8, "numeric_array_descriptors", 1, 36, 316),
    Root(0x22674, "eeprom_settings_groups", 12, 16, 317),
    Root(0x22734, "date_descriptors", 1, 8, 329),
    Root(0x22744, "time_descriptors", 1, 8, 330),
    Root(0x2276C, "power_loss_snapshot", 1, 12, 331),
    Root(0x22778, "identity_list", 21, 2),
    Root(0x22CD0, "short_name_bucket_headers", 26, 8),
    Root(0x204F8, "event_spool_definitions", 14, 36),
    Root(0x206F0, "event_json_payload_overrides", 20, 6),
    Root(0x207A0, "periodic_collections", 4, 40),
    Root(0x227A4, "rpc_node_permissions", 13, 1),
)
PRIMARY_ROOTS = (1, 2, 3, 5)
DESCRIPTOR_ROOTS = (1, 2, 3, 5, 6, 7, 8, 9, 10)
LONG_NAMES_OFFSET = 0x46DC4
ENUM_SYMBOLS_OFFSET = 0x4651C
ENUM_SYMBOL_COUNT = 72
RULE_TABLE_OFFSET = 0x5980C
RULE_COUNT = 10
RPC_NODE_OFFSETS = (0x979DC, 0x97A4C, 0x97AAC, 0x97A6C, 0x979CC,
                    0x97A0C, 0x97A9C, 0x97A7C, 0x97A8C, 0x97A1C,
                    0x97A3C, 0x97A5C, 0x97A2C)


class AirMiniFirmware:
    def __init__(self, path, *, data=None, ignore_input_crc=False):
        self.path = Path(path)
        self.data = self.path.read_bytes() if data is None else bytes(data)
        if len(self.data) != IMAGE_SIZE:
            raise ValueError("expected a full 1 MiB AirMini flash image")
        if (self.u32(CONF_BASE) != 1 or self.u32(CONF_BASE + 4) != 0x27
                or self.ascii_field(CONF_BASE + 0x14, 16) != "SIMPLICITY"
                or self.ascii_field(0x40000, 32) != APP_VERSION):
            raise ValueError("unsupported firmware layout; expected AirMini " + APP_VERSION)
        # AirMini returns the inline table with ADR, not Air11's literal load.
        if self.data[0x20100:GLOBALS_OFFSET] != bytes.fromhex("0ff2040070470000"):
            raise ValueError("unsupported CONF globals getter")
        if self.data[FACTORY_OFFSET:FACTORY_OFFSET + len(FACTORY_SIGNATURE)] != FACTORY_SIGNATURE:
            raise ValueError("unsupported DataItem factory range layout")
        for index, root in enumerate(ROOTS):
            if self.u32(GLOBALS_OFFSET + index * 4) != FLASH_BASE + root.offset:
                raise ValueError(f"unsupported globals[{index}] pointer/layout")

        self.crc_stored = int.from_bytes(self.data[CONF_END - 2:CONF_END], "big")
        self.crc_computed = binascii.crc_hqx(self.data[CONF_BASE:CONF_END - 2], 0xFFFF)
        self.crc_ok = self.crc_stored == self.crc_computed
        if not self.crc_ok and not ignore_input_crc:
            raise ValueError(
                f"CONF CRC mismatch: stored=0x{self.crc_stored:04X} "
                f"computed=0x{self.crc_computed:04X}; "
                "use --ignore-input-crc for inspection or repair"
            )
        self.names, self.name_ids = self._read_names()
        self.long_names = {vid: self.string_at(self.u32(LONG_NAMES_OFFSET + vid * 4))
                           for vid in range(MAX_VAR_ID + 1)}
        self.long_ids = {}
        for vid, name in self.long_names.items():
            self.long_ids.setdefault(name.casefold(), []).append(vid)
        self.enum_symbols = self._read_enum_symbols()
        # Validate all DataItem descriptors before any CLI output/export.
        self.records = {}
        for index in DESCRIPTOR_ROOTS:
            root = ROOTS[index]
            for row in range(root.count):
                record = self._read_descriptor(index, row)
                self.records[record["var_id"]] = record
        if len(self.records) != MAX_VAR_ID + 1:
            raise ValueError("DataItem ranges are not complete")

    def unpack(self, fmt, offset):
        size = struct.calcsize("<" + fmt)
        if not 0 <= offset <= len(self.data) - size:
            raise ValueError(f"read outside firmware at 0x{offset:X}")
        return struct.unpack_from("<" + fmt, self.data, offset)[0]

    def u16(self, offset):
        return self.unpack("H", offset)

    def u32(self, offset):
        return self.unpack("I", offset)

    def ascii_field(self, offset, size):
        try:
            return self.data[offset:offset + size].split(b"\0", 1)[0].decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError(f"non-ASCII identity field at 0x{offset:X}") from exc

    def _read_names(self):
        names, ids = {}, {}
        for bucket in range(26):
            header = ROOTS[12].offset + bucket * 8
            pointer, count = self.u32(header), self.data[header + 4]
            if self.data[header + 5:header + 8] != b"\0\0\0":
                raise ValueError(f"short-name bucket {bucket} has invalid reserved bytes")
            if pointer == 0 and count == 0:
                continue
            offset = pointer - FLASH_BASE
            # This profile's suffix pool lies between g[16] and g[12].
            if not ROOTS[16].offset + 16 <= offset <= ROOTS[12].offset - count * 4:
                raise ValueError(f"short-name bucket {bucket} points outside its pool")
            for row in range(count):
                off = offset + row * 4
                suffix = self.data[off:off + 2]
                if not all(0x21 <= char <= 0x7E for char in suffix):
                    raise ValueError(f"invalid short-name suffix at 0x{off:X}")
                tag = chr(ord("A") + bucket) + suffix.decode("ascii")
                var_id = self.u16(off + 2)
                if var_id > MAX_VAR_ID:
                    raise ValueError(f"short name {tag} has out-of-range ID 0x{var_id:04X}")
                if tag in ids or var_id in names:
                    raise ValueError(f"duplicate short name or ID at {tag}")
                names[var_id], ids[tag] = tag, var_id
        return names, ids

    def _read_descriptor(self, root_index, index):
        if root_index in (7, 10):
            return self._read_group(root_index, index)
        root = ROOTS[root_index]
        off = root.offset + index * root.stride
        var_id = root.id_base + index
        record = dict(
            array=f"g{root_index}", index=index, offset=off,
            address=FLASH_BASE + off, var_id=var_id,
            short_name=self.names.get(var_id, ""), long_name=self.long_names[var_id], kind=root.kind,
            flags=self.u16(off),
            flag_names="|".join(name for bit, name in enumerate(FLAG_NAMES)
                                if self.u16(off) & (1 << bit)),
            rule_id_raw=self.data[off + 2],
            linked_counter_index=self.u16(off + 4),
            event_queue_raw=self.data[off + 6],
        )
        if self.data[off + 3] or self.data[off + 7]:
            raise ValueError(f"nonzero reserved prefix at 0x{off:X}")
        counter = record["linked_counter_index"]
        if counter != 0x7FFF and counter >= ROOTS[2].count:
            raise ValueError(f"counter index outside g2 at 0x{off:X}")
        if root_index == 1:
            record["buffer_capacity"] = self.u16(off + 8)
        elif root_index in (2, 6):
            record.update(
                default_raw=self.unpack("i", off + 8),
                max_raw=self.unpack("i", off + 12),
                min_raw=self.unpack("i", off + 16),
                decimal_places_raw=self.data[off + 20],
                reserved_15_raw=self.data[off + 21],
                scale=self.unpack("h", off + 22),
                step_raw=self.unpack("h", off + 24),
                tail_1a_raw=self.data[off + 26:off + 28].hex(),
            )
            if record["min_raw"] > record["max_raw"]:
                raise ValueError(f"numeric min exceeds max at 0x{off:X}")
            if record["scale"]:
                for field in ("default", "min", "max", "step"):
                    record[field] = format(
                        Decimal(record[field + "_raw"]) / Decimal(record["scale"]), "f"
                    )
            else:
                record.update({field: record[field + "_raw"] for field in ("default", "min", "max", "step")})
            if root_index == 6:
                record.update(storage_index=self.u32(off + 28), element_count=self.data[off + 32],
                              reserved_21_23=self.data[off + 33:off + 36].hex())
        elif root_index == 3:
            count, pool_index = self.data[off + 16], self.u16(off + 18)
            pool_size = ROOTS[5].offset - ROOTS[4].offset
            if count > 32 or pool_index + count > pool_size:
                raise ValueError(f"bit-selection slice outside g4 at 0x{off:X}")
            start = ROOTS[4].offset + pool_index
            order = tuple(self.data[start:start + count])
            if any(bit >= 32 for bit in order):
                raise ValueError(f"bit-selection index exceeds 31 at 0x{off:X}")
            record.update(
                default_mask=self.u32(off + 8), editable_mask=self.u32(off + 12),
                bit_count=count, byte_11_raw=self.data[off + 17],
                selection_offset=pool_index, selection_order=order,
            )
        elif root_index == 5:
            default, count = self.data[off + 8:off + 10]
            if not 1 <= count <= 32 or default >= count:
                raise ValueError(f"unsupported enum option count/default at 0x{off:X}")
            mask = self.u32(off + 12)
            record.update(
                default_option=default, option_count=count,
                reserved_0a_raw=self.u16(off + 10), option_mask=mask,
                enabled_options=tuple(i for i in range(count) if mask & (1 << i)),
            )
        record["raw"] = self.data[off:off + root.stride].hex()
        return record

    def resolve(self, selector):
        tag = selector[1:] if selector.startswith("_") else selector
        if tag.casefold() in self.long_ids:
            candidates = self.long_ids[tag.casefold()]
            if len(candidates) != 1:
                raise ValueError(f"ambiguous long name {selector!r}: IDs {candidates}")
            var_id = candidates[0]
        elif tag.upper() in self.name_ids:
            var_id = self.name_ids[tag.upper()]
        else:
            try:
                var_id = parse_number(selector)
            except ValueError as exc:
                raise ValueError(f"unknown variable {selector!r}; use a short tag, long name or numeric ID") from exc
        if var_id not in self.records:
            raise ValueError(f"variable ID {var_id} is outside 0..{MAX_VAR_ID}")
        return self.records[var_id]

    def selected_records(self, array="all", name=None):
        try:
            pattern = re.compile(name, re.IGNORECASE) if name is not None else None
        except re.error as exc:
            raise ValueError(f"invalid name regex: {exc}") from exc
        return [record for record in self.records.values()
                if (array == "all" or record["array"] == array)
                and (pattern is None or pattern.search(record["short_name"] + " " + record["long_name"]))]

    def info(self):
        return dict(
            platform="AirMini", app_version=APP_VERSION,
            data_version=self.u32(CONF_BASE), platform_id=self.u32(CONF_BASE + 4),
            platform_text=self.ascii_field(CONF_BASE + 0x14, 16),
            product_code=self.ascii_field(CONF_BASE + 0x24, 16),
            product_name=self.ascii_field(CONF_BASE + 0x34, 16),
            image_bytes=len(self.data), sha256=hashlib.sha256(self.data).hexdigest(),
            globals_address=FLASH_BASE + GLOBALS_OFFSET, globals_count=len(ROOTS),
            decoded_descriptors=len(self.records), named_ids=len(self.names),
            max_var_id=MAX_VAR_ID, crc_stored=self.crc_stored,
            crc_computed=self.crc_computed, crc_ok=self.crc_ok,
        )

    def cmd_info(self):
        """Match the human-readable default summary of as11_descriptors."""
        platform_id = self.u32(CONF_BASE + 4)
        data_version = self.u32(CONF_BASE)
        print(f"  File:     {self.path}")
        print(f"  Platform: {self.ascii_field(CONF_BASE + 0x14, 16)}")
        print("  Product defaults: code=%s name=%s" % (
            self.ascii_field(CONF_BASE + 0x24, 16),
            self.ascii_field(CONF_BASE + 0x34, 16),
        ))
        print(
            "  Firmware: data_version=%d platform_id=%d aid=%d "
            "variant_id=%d region_id=%d" % (
                data_version, platform_id, self.u32(CONF_BASE + 8),
                self.u32(CONF_BASE + 12), self.u32(CONF_BASE + 16),
            )
        )
        print("  Versions:")
        boot_version = self.ascii_field(0xF00, 24)
        if boot_version:
            print(f"    Bootloader:  SW{platform_id:03d}01.00.{boot_version}")
        print(f"    Application: SW{platform_id:03d}00.{data_version:02d}."
              f"{self.ascii_field(0x40000, 32)}")
        data_model = self.ascii_field(CONF_BASE + 0x68, 12)
        if data_model:
            print(f"    Data model:  {data_model}")

        mop_id = self.name_ids.get("MOP")
        mop = self.records.get(mop_id, {})
        mode_names = {value: symbol for (enum, value), symbol in self.enum_symbols.items()
                      if enum == mop.get("index")}
        modes = [mode_names.get(index, f"index {index}")
                 for index in mop.get("enabled_options", ())]
        lnc_id = self.name_ids.get("LNC")
        lnc = self.records.get(lnc_id, {})
        languages = [f"index {index}" for index in range(lnc.get("bit_count", 0))
                     if lnc.get("default_mask", 0) & (1 << index)]
        print()
        print("  Therapy modes:  " + (", ".join(modes) or "(none)"))
        print("  Languages:      " + (
            ", ".join(languages) + " (no names in firmware enum table)" if languages else "(none)"
        ))

    def checked_offset(self, pointer, size, *, conf=False):
        off = pointer - FLASH_BASE
        low, high = (CONF_BASE, CONF_END - 2) if conf else (0, len(self.data))
        if size < 0 or not low <= off <= high - size:
            raise ValueError(f"pointer 0x{pointer:08X}, size {size} is outside {'CONF' if conf else 'image'}")
        return off

    def string_at(self, pointer):
        off = self.checked_offset(pointer, 1)
        end = self.data.find(b"\0", off, min(off + 512, len(self.data)))
        if end < 0 or any(c < 32 or c > 126 for c in self.data[off:end]):
            raise ValueError(f"invalid ASCII string at 0x{pointer:08X}")
        return self.data[off:end].decode("ascii")

    def _read_enum_symbols(self):
        symbols = {}
        for index in range(ENUM_SYMBOL_COUNT):
            off = ENUM_SYMBOLS_OFFSET + index * 12
            enum_type, value, pointer = struct.unpack_from("<III", self.data, off)
            if enum_type >= ROOTS[5].count or value >= 32:
                raise ValueError(f"invalid enum-symbol row at 0x{off:X}")
            key = enum_type, value
            if key in symbols:
                raise ValueError(f"duplicate enum-symbol key {key}")
            symbols[key] = self.string_at(pointer)
        return symbols

    def member_ids(self, pointer, count):
        if count > MAX_VAR_ID + 1:
            raise ValueError(f"member count {count} exceeds DataItem range")
        if count == 0 and pointer == 0:
            return ()
        off = self.checked_offset(pointer, count * 2, conf=True)
        ids = struct.unpack_from(f"<{count}H", self.data, off)
        if any(vid > MAX_VAR_ID for vid in ids):
            raise ValueError(f"invalid member ID at 0x{off:X}")
        return ids

    def member_rows(self, root, off, count):
        ids = self.member_ids(FLASH_BASE + off, count)
        return [dict(global_index=int(root[1:]), index=i, offset=off + i * 2,
                     var_id=vid, short_name=self.names.get(vid, ""),
                     long_name=self.long_names[vid], raw=self.data[off+i*2:off+i*2+2].hex())
                for i, vid in enumerate(ids)]

    def _read_group(self, root_index, index):
        root = ROOTS[root_index]
        off = root.offset + index * root.stride
        vid = root.id_base + index
        name = self.ascii_field(off, 4)
        if not re.fullmatch(r"[A-Z0-9]{3}", name):
            raise ValueError(f"invalid group tag at 0x{off:X}")
        pointer = self.u32(off + (8 if root_index == 7 else 4))
        count = self.data[off + 12] if root_index == 7 else self.u32(off + 8)
        members = self.member_ids(pointer, count)
        row = dict(array=f"g{root_index}", index=index, offset=off,
                   address=FLASH_BASE + off, var_id=vid, short_name=name,
                   long_name=self.long_names[vid], kind=root.kind)
        if root_index == 7:
            counter = self.u16(off + 4)
            if counter != 0x7FFF and counter >= ROOTS[2].count:
                raise ValueError(f"invalid storage counter at 0x{off:X}")
            row.update(linked_counter_index=counter, policy_06=self.data[off + 6],
                       aggregate_counter=bool(self.data[off + 7]),
                       path=f"eep:0:\\SETTINGS\\{name}.set",
                       reserved_0d_0f=self.data[off+13:off+16].hex())
        row.update(member_count=count, members=members,
                   member_names=tuple(self.names.get(v, self.long_names[v]) for v in members),
                   raw=self.data[off:off + root.stride].hex())
        return row

    def events(self):
        rows = []
        for index in range(ROOTS[13].count):
            off = ROOTS[13].offset + index * 36
            name, tag = (self.string_at(self.u32(off + delta)) for delta in (0, 4))
            if not name or not re.fullmatch(r"[A-Z0-9]{3}", tag):
                raise ValueError(f"invalid event names at 0x{off:X}")
            row = dict(root="g13", index=index, offset=off, name=name, tag=tag,
                       fifo_slots=self.u32(off + 8), retained_records=self.u32(off + 12),
                       event_record_bytes=self.u32(off + 16), record_kind=self.data[off + 20],
                       default_json_payload_type=self.data[off + 21],
                       erase_class=self.data[off + 22], flag_17=self.data[off + 23],
                       file_record_bytes=self.u32(off + 24),
                       allocation_group_blocks=self.u32(off + 28),
                       file_init_flag_bit=self.u16(off + 32), reserved_22=self.u16(off + 34),
                       raw=self.data[off:off + 36].hex())
            if (row["fifo_slots"] == 0 or row["event_record_bytes"] == 0 or
                    row["record_kind"] not in (1, 2, 3) or
                    row["default_json_payload_type"] > 6 or row["file_init_flag_bit"] >= 32):
                raise ValueError(f"invalid event definition at 0x{off:X}")
            rows.append(row)
        return rows

    def event_payload_types(self):
        events = self.events()
        rows = []
        for i in range(ROOTS[14].count):
            off = ROOTS[14].offset + i * 6
            spool, padding, value, payload, padding2 = struct.unpack_from("<BBHBB", self.data, off)
            if spool >= len(events) or payload > 6 or padding or padding2:
                raise ValueError(f"invalid event payload override at 0x{off:X}")
            event = events[spool]
            rows.append(dict(root="g14", index=i, offset=off, event_spool_index=spool,
                             event_name=event["name"], tag=event["tag"], event_value=value,
                             json_payload_type=payload, raw=self.data[off:off + 6].hex()))
        return rows

    def collections(self):
        rows = []
        for i in range(ROOTS[15].count):
            off = ROOTS[15].offset + i * 40
            tag = self.string_at(self.u32(off))
            count = self.data[off + 28]
            ids = self.member_ids(self.u32(off + 32), count)
            names_off = self.checked_offset(self.u32(off + 36), count * 4, conf=True)
            names = tuple(self.string_at(self.u32(names_off + j * 4)) for j in range(count))
            gate = self.data[off + 22]
            if not count or gate >= ROOTS[5].count or self.u16(off + 4) == 0:
                raise ValueError(f"invalid collection at 0x{off:X}")
            header = dict(root="g15", index=i, offset=off, tag=tag,
                          interval_ms=self.u16(off + 4), max_block_seconds=self.u16(off + 6),
                          buffer_bytes=self.u32(off + 8), retention_hours=self.u32(off + 12),
                          allocation_group_blocks=self.u32(off + 16),
                          file_policy=self.data[off + 20], flag_15=self.data[off + 21],
                          gate_index=gate, gate=self.names.get(ROOTS[5].id_base + gate, ""),
                          file_init_flag_bit=self.u16(off + 24), signal_count=count,
                          raw=self.data[off:off+40].hex())
            for j, (vid, name) in enumerate(zip(ids, names)):
                rows.append(dict(header, signal_index=j, var_id=vid,
                                 short_name=self.names.get(vid, ""), long_name=self.long_names[vid],
                                 data_id=name))
        return rows

    def rpc_nodes(self):
        rows = []
        for index, off in enumerate(RPC_NODE_OFFSETS):
            name = self.string_at(self.u32(off))
            if self.u32(off + 4) != index:
                raise ValueError(f"RPC node ID mismatch at 0x{off:X}")
            enabled = self.data[ROOTS[16].offset + index]
            if enabled not in (0, 1):
                raise ValueError(f"invalid RPC permission for node {index}")
            count = self.u32(off + 8)
            if count > 64:
                raise ValueError(f"RPC node field count exceeds 64 at 0x{off:X}")
            fields_off = self.checked_offset(self.u32(off + 12), count * 8)
            fields = []
            for j in range(count):
                key = self.string_at(self.u32(fields_off + j * 8))
                target = self.string_at(self.u32(fields_off + j * 8 + 4))
                fields.append(f"{key}:{target}")
            rows.append(dict(global_index=16, node_id=index, offset=ROOTS[16].offset + index,
                             name=name, enabled=bool(enabled), field_count=count,
                             fields=tuple(fields), source_address=FLASH_BASE + off,
                             raw=f"{enabled:02x}"))
        return rows

    def data_rules(self):
        rows = []
        for rule in range(1, RULE_COUNT):
            off = RULE_TABLE_OFFSET + rule * 4
            pointer = self.u32(off)
            if not pointer & 1:
                raise ValueError(f"data rule {rule} has a non-Thumb callback")
            self.checked_offset(pointer & ~1, 2)
            uses = [rec for rec in self.records.values() if rec.get("rule_id_raw") == rule]
            rows.append(dict(rule=rule, callback=pointer & ~1, source_address=FLASH_BASE + off,
                             use_count=len(uses), variables=tuple(rec["short_name"] or rec["long_name"] for rec in uses)))
        return rows

    def mode_rows(self, selector=None):
        mop = self.resolve("MOP")
        modes = {value: symbol for (enum, value), symbol in self.enum_symbols.items()
                 if enum == mop["index"]}
        if selector is None:
            return [dict(mode=idx, name=name, enabled=idx in mop["enabled_options"],
                         default=idx == mop["default_option"])
                    for idx, name in sorted(modes.items())]
        matches = [idx for idx, name in modes.items() if name.casefold() == selector.casefold()]
        try:
            index = matches[0] if matches else parse_number(selector)
        except ValueError as exc:
            raise ValueError(f"unknown therapy mode {selector!r}") from exc
        if index not in modes:
            raise ValueError(f"mode {index} has no AirMini profile in this firmware")
        prefix = modes[index] + "-"
        return [dict(rec, mode=index, scope="name_namespace") for rec in self.records.values()
                if rec["long_name"].startswith(prefix)]

    def conf_layout(self):
        rows = []
        for i, root in enumerate(ROOTS):
            size = root.count * root.stride if root.count is not None else 72
            rows.append(dict(global_index=i, offset=root.offset, address=FLASH_BASE + root.offset,
                             kind=root.kind, count=root.count if root.count is not None else size,
                             size=size))
        return rows

    def global_contents(self, index, raw=False):
        if not 0 <= index < len(ROOTS):
            raise ValueError("globals index must be in 0..16")
        root = ROOTS[index]
        if index == 0:
            return [dict(
                global_index=0, offset=CONF_BASE,
                data_version=self.u32(CONF_BASE),
                platform_id=self.u32(CONF_BASE + 4), aid=self.u32(CONF_BASE + 8),
                variant_id=self.u32(CONF_BASE + 12), region_id=self.u32(CONF_BASE + 16),
                platform_text=self.ascii_field(CONF_BASE + 0x14, 16),
                default_product_code=self.ascii_field(CONF_BASE + 0x24, 16),
                default_product_name=self.ascii_field(CONF_BASE + 0x34, 16),
                header_64_raw=self.u32(CONF_BASE + 0x64),
                data_model_version=self.ascii_field(CONF_BASE + 0x68, 12),
                header_74_raw=self.u32(CONF_BASE + 0x74),
                raw=self.data[CONF_BASE:CONF_BASE + 0x100].hex(),
            )]
        if index in DESCRIPTOR_ROOTS:
            return self.selected_records(f"g{index}")
        if index == 4:
            return [dict(
                global_index=4, kind="bitfield_selection_order", array="g3", index=rec["index"],
                offset=root.offset + rec["selection_offset"], var_id=rec["var_id"],
                short_name=rec["short_name"], long_name=rec["long_name"],
                list_offset=f"0x{rec['selection_offset']:04X}", count=rec["bit_count"],
                values="natural" if rec["selection_order"] == tuple(range(rec["bit_count"])) else rec["selection_order"],
                raw=bytes(rec["selection_order"]).hex(),
            ) for rec in self.selected_records("g3")]
        if index == 12:
            rows = []
            for bucket in range(26):
                header = root.offset + bucket * 8
                count = self.data[header + 4]
                offset = self.u32(header) - FLASH_BASE
                if count == 0:
                    rows.append(dict(global_index=12, bucket=chr(65 + bucket), bucket_idx=bucket, header_off=header, count=0))
                for row in range(count):
                    off = offset + row * 4
                    var_id = self.u16(off + 2)
                    rows.append(dict(
                        global_index=12, bucket=chr(65 + bucket), bucket_idx=bucket, header_off=header, entry_idx=row,
                        offset=off, var_id=var_id, short_name=self.names[var_id], long_name=self.long_names[var_id],
                        raw=self.data[off:off + 4].hex(),
                    ))
            return rows
        if index == 11:
            return self.member_rows("g11", ROOTS[11].offset, 21)
        if index == 13:
            return self.events()
        if index == 14:
            return self.event_payload_types()
        if index == 15:
            return self.collections()
        if index == 16:
            return self.rpc_nodes()
        raise ValueError(f"no decoder for globals[{index}]")

    def global_map(self, indexes, raw=False):
        layout = self.conf_layout()
        rows = []
        for index in indexes:
            if not 0 <= index < len(ROOTS):
                raise ValueError("globals index must be in 0..16")
            root, section = ROOTS[index], layout[index]
            row = dict(global_index=index, value=f"0x{FLASH_BASE + root.offset:08X}",
                       offset=root.offset, kind=root.kind, count=section["count"], size=section["size"])
            if raw:
                row["raw"] = self.data[root.offset:root.offset + min(32, section["size"])].hex()
            rows.append(row)
        return rows


def parse_number(value):
    value = value.strip()
    return int(value, 16 if value.lstrip("+-").lower().startswith("0x") else 10)


HEX_FIELDS = {
    "offset": 6, "address": 8, "var_id": 4, "flags": 4,
    "linked_counter_index": 4, "option_mask": 8, "default_mask": 8, "editable_mask": 8,
    "globals_address": 8, "max_var_id": 4, "crc_stored": 4,
    "crc_computed": 4, "id_base": 4, "id_last": 4,
    "rule": 2, "source_off": 6, "header_off": 6, "selection_order_off": 6,
    "reserved_0a_raw": 4, "gate_g5_index": 4, "gate_var": 4, "rule_id_raw": 2, "event_queue_raw": 2, "callback": 8, "source_address": 8,
}


def format_value(key, value):
    if value is None or value == "":
        return "n/a"
    if key in HEX_FIELDS:
        return f"0x{value:0{HEX_FIELDS[key]}X}"
    if key in ("default", "min", "max", "step") and isinstance(value, str):
        text = format(Decimal(value), ".8f").rstrip("0").rstrip(".")
        return "0" if text in ("", "-0") else text
    if key == "size":
        return f"0x{value:X}"
    if key == "selection_offset":
        return f"+0x{value:04X}"
    if isinstance(value, bool):
        return str(int(value))
    if key == "flag_names":
        return value.replace("|", ",")
    if isinstance(value, (tuple, list)):
        return ",".join(format_value("", item) for item in value) or "n/a"
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", "\\n").replace("\r", "\\r")


# Keep internal record names separate from the Air11-compatible output schema.
OUTPUT_NAMES = {
    "index": "idx", "offset": "off", "address": "addr",
    "var_id": "var", "short_name": "short",
    "linked_counter_index": "linked_counter", "long_name": "long",
    "rule_id_raw": "data_rule", "event_queue_raw": "event_queue",
    "decimal_places_raw": "decimal_places", "byte_11_raw": "display_bits",
    "selection_offset": "selection_order_offset", "reserved_0a_raw": "reserved",
}


def descriptor_fields(record):
    """Air11's common field order; append only real AirMini-specific fields."""
    keys = ["array", "index", "offset", "address", "var_id", "short_name", "long_name"]
    if record["array"] not in ("g7", "g10"):
        keys += ["flags", "flag_names", "linked_counter_index", "event_queue_raw", "rule_id_raw"]
    family = record["array"]
    if family == "g1":
        keys += ["buffer_capacity"]
    elif family in ("g2", "g6"):
        keys += ["default", "min", "max", "step", "scale", "default_raw", "min_raw",
                 "max_raw", "step_raw", "decimal_places_raw"]
    elif family == "g3":
        keys += ["selection_order", "selection_offset", "selection_order_off", "bit_count",
                 "default_mask", "editable_mask", "editable_bits"]
        record = dict(record, selection_order_off=ROOTS[4].offset + record["selection_offset"],
                      editable_bits=tuple(i for i in range(32)
                                          if record["editable_mask"] & (1 << i)))
    elif family == "g5":
        keys += ["default_option", "option_count", "option_mask", "enabled_options", "reserved_0a_raw"]
    result = {key: record[key] for key in keys if key in record}
    result.update({key: value for key, value in record.items() if key not in result and key != "kind"})
    return result


def output_fields(record, raw=True):
    if "array" in record and "raw" in record and "kind" in record and "var_id" in record and record.get("kind") != "bitfield_selection_order":
        record = descriptor_fields(record)
    return {OUTPUT_NAMES.get(key, key): format_value(key, value)
            for key, value in record.items() if key != "raw" or raw}


def emit(record, raw=False):
    print("|".join(f"{key}={value}" for key, value in output_fields(record, raw).items()))


def make_tsv(records):
    # Stable union of fields; empty cells distinguish inapplicable values from 0.
    records = [output_fields(row) for row in records]
    fields = list(dict.fromkeys(key for row in records for key in row))
    if not fields:
        fields = ["array", "idx", "off", "addr", "var", "short", "kind", "raw"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for row in records:
        writer.writerow(row)
    return stream.getvalue()


# Only in-place scalar fields with verified layouts are editable. No pointers,
# table sizes, storage membership or executable code are changed by this command.
COMMON_EDIT_FIELDS = {
    "flags": (0, "H"), "data_rule": (2, "B"),
    "linked_counter": (4, "H"), "event_queue": (6, "B"),
}
NUMERIC_EDIT_FIELDS = {
    "default_raw": (8, "i"), "max_raw": (12, "i"), "min_raw": (16, "i"),
    "decimal_places": (20, "B"), "scale": (22, "h"), "step_raw": (24, "h"),
}
FLAG_NAMES = ("ACT", "VIS", "MOD", "SGN", "INH", "VAL", "ULK", "RAW", "MON", "RPC", "RPW")


def editable_fields(record):
    array = record["array"]
    fields = dict(COMMON_EDIT_FIELDS) if array not in ("g7", "g10") else {}
    if array == "g1":
        fields["buffer_capacity"] = (8, "H")
    elif array in ("g2", "g6"):
        fields.update(NUMERIC_EDIT_FIELDS)
        fields.update({name: fields[name + "_raw"] for name in ("default", "min", "max", "step")})
    elif array == "g3":
        fields.update(default_mask=(8, "I"), editable_mask=(12, "I"), option_mask=(12, "I"))
    elif array == "g5":
        fields.update(default_option=(8, "B"), option_mask=(12, "I"))
    return fields


def apply_edits(fw, assignments):
    plans, locations = [], set()
    for assignment in assignments:
        try:
            left, value = assignment.split("=", 1)
            selector, field = left.rsplit(".", 1)
        except ValueError as exc:
            raise ValueError(f"expected VAR.FIELD=VALUE, got {assignment!r}") from exc
        selector, field, value = selector.strip(), field.strip().lower(), value.strip()
        rec = fw.resolve(selector)
        aliases = {"data_rule_id": "data_rule", "linked_counter_index": "linked_counter",
                   "change_event_queue_index": "event_queue"}
        if rec["array"] == "g1":
            aliases.update(max_len="buffer_capacity", max_length="buffer_capacity")
        elif rec["array"] == "g3":
            aliases.update(default="default_mask", editable="editable_mask")
        elif rec["array"] == "g5":
            aliases.update(default_opt="default_option", mask="option_mask")
        field = aliases.get(field, field)
        fields = editable_fields(rec)
        if field not in fields:
            raise ValueError(f"{selector}: editable fields: {', '.join(fields) or '(none)'}")
        delta, fmt = fields[field]
        offset = rec["offset"] + delta
        if offset in locations:
            raise ValueError(f"duplicate assignment to {selector}.{field}")
        locations.add(offset)
        plans.append(dict(rec=rec, field=field, value=value, offset=offset, fmt=fmt))
    scales = {p["rec"]["var_id"]: parse_number(p["value"]) for p in plans if p["field"] == "scale"}
    data = bytearray(fw.data)
    changes = []
    for plan in plans:
        rec, field, text_value = plan["rec"], plan["field"], plan["value"]
        if field in ("default", "min", "max", "step") and rec["array"] in ("g2", "g6"):
            scale = scales.get(rec["var_id"], rec["scale"])
            if scale <= 0:
                raise ValueError("scaled edits require a positive scale")
            number = (Decimal(parse_number(text_value)) if text_value.lstrip("+-").lower().startswith("0x")
                      else Decimal(text_value))
            if not number.is_finite():
                raise ValueError("numeric values must be finite")
            numerator, denominator = number.as_integer_ratio()
            value, remainder = divmod(numerator * scale, denominator)
            if remainder:
                raise ValueError(f"{field}={text_value} is not exactly representable at scale {scale}")
        elif field == "flags" and any(char.isalpha() for char in text_value) and not text_value.lower().startswith("0x"):
            value = 0
            for token in text_value.split("|"):
                if token.strip().upper() not in FLAG_NAMES:
                    raise ValueError(f"unknown flag {token!r}")
                value |= 1 << FLAG_NAMES.index(token.strip().upper())
        else:
            value = parse_number(text_value)
        if field == "data_rule" and not 0 <= value < RULE_COUNT:
            raise ValueError("data_rule must be in 0..9")
        if field == "event_queue" and not 0 <= value <= ROOTS[13].count:
            raise ValueError("event_queue must be in 0..14 (14 means no queue)")
        if field == "scale" and value <= 0:
            raise ValueError("scale must be positive")
        if field in ("step", "step_raw") and value < 0:
            raise ValueError("step must be nonnegative")
        old = fw.unpack(plan["fmt"], plan["offset"])
        try:
            struct.pack_into("<" + plan["fmt"], data, plan["offset"], value)
        except struct.error as exc:
            raise ValueError(f"{field}={value} is outside its storage range") from exc
        plan["stored"] = value
        changes.append(dict(var_id=rec["var_id"], short_name=rec["short_name"],
                            field=field, offset=plan["offset"], old_raw=old, new_raw=value))
    crc = binascii.crc_hqx(data[CONF_BASE:CONF_END - 2], 0xFFFF)
    data[CONF_END - 2:CONF_END] = crc.to_bytes(2, "big")
    checked = AirMiniFirmware(fw.path, data=data)
    for plan in plans:
        if checked.unpack(plan["fmt"], plan["offset"]) != plan["stored"]:
            raise ValueError("edit read-back verification failed")
        rec = checked.records[plan["rec"]["var_id"]]
        if rec["array"] in ("g2", "g6") and not rec["min_raw"] <= rec["default_raw"] <= rec["max_raw"]:
            raise ValueError(f"{rec['short_name']}: default is outside the edited bounds")
    return bytes(data), changes


def write_image(input_path, output_path, data, overwrite=False):
    source, target = Path(input_path), Path(output_path)
    if source.resolve() == target.resolve() or (target.exists() and os.path.samefile(source, target)):
        raise ValueError("output path must differ from input, including link aliases")
    if target.exists() and not overwrite:
        raise ValueError("output already exists; use --overwrite to replace it")
    fd, temp = tempfile.mkstemp(prefix=".airmini-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temp, target)
        else:
            os.link(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("firmware", help="full 1 MiB AirMini flash image")
    result.add_argument("-i", "--interactive", action="store_true", help="start interactive descriptor shell")
    result.add_argument("--ignore-input-crc", action="store_true", help="inspect invalid CONF CRC; layout checks remain enabled")
    commands = result.add_subparsers(dest="command")
    info = commands.add_parser("info", help="show firmware summary (default command)")
    info.add_argument("--raw", action="store_true", help="emit machine-readable identity, counts and CRC")
    glob = commands.add_parser("globals", help="list globals[] values or dump one globals table")
    glob.add_argument("index", nargs="?", type=parse_number, help="optional globals index")
    glob.add_argument("--raw", action="store_true", help="include raw record bytes")
    glob.add_argument("--verbose", action="store_true", help="show detailed table fields, including RPC object schemas")
    commands.add_parser("conf-layout", help="list globals[] root objects and their decoded sizes")
    var = commands.add_parser("var", help="show variable descriptors by id, long name, or short tag")
    var.add_argument("ident", nargs="+", help="one or more var_ids, long names, tags, or _TAG aliases")
    var.add_argument("--raw", action="store_true")
    var.add_argument("--verbose", action="store_true", help="show multi-line details")
    opts = commands.add_parser("var-options", help="show enum option slots for a g5 variable")
    opts.add_argument("ident", help="var_id, long name, tag, or _TAG")
    opts.add_argument("--verbose", action="store_true", help="show multi-line enum details")
    mode = commands.add_parser("mode", help="list modes or name-scoped settings (no CONF visibility matrix)")
    mode.add_argument("mode", nargs="?", help="mode name or index; omit to list modes")
    rules = commands.add_parser("data-rules", help="list APPL DataItem rule callbacks and their CONF users")
    rules.add_argument("rule", nargs="*", type=parse_number, help="optional rule ids")
    events = commands.add_parser("events", help="list event spool definitions from g[13]")
    events.add_argument("filter", nargs="*", help="optional code/name substring filter")
    events.add_argument("--verbose", action="store_true", help="show multi-line details")
    payloads = commands.add_parser("event-payload-types", help="list g[14] EventNotification payload rules")
    payloads.add_argument("filter", nargs="*", help="optional code/name substring filter")
    collections = commands.add_parser("collections", help="list g[15] collection tables")
    collections.add_argument("collection", nargs="*", help="optional collection tag filter, e.g. NRF HRF")
    collections.add_argument("--verbose", action="store_true", help="include collection rows")
    storage = commands.add_parser("storage-sets", help="list EEPROM SettingsGroup schemas")
    storage.add_argument("set", nargs="*", help="optional set tag filter, e.g. HST BGL")
    storage.add_argument("--names-only", action="store_true", help="show each set with its counter and member names")
    storage.add_argument("--verbose", action="store_true", help="show multi-line details")
    for command in ("vars", "dump-tsv"):
        listing = commands.add_parser(command, help="list variables" if command == "vars" else "export descriptors and raw bytes")
        if command == "dump-tsv":
            listing.add_argument("output", help="new TSV file, or - for stdout; existing files are never replaced")
        else:
            listing.add_argument("--raw", action="store_true")
            listing.add_argument("--verbose", action="store_true", help="show multi-line details")
        listing.add_argument("--array", choices=("all",) + tuple(f"g{i}" for i in DESCRIPTOR_ROOTS), default="all",
                             help="descriptor array; default scans all DataItem families")
        listing.add_argument("--name", help="case-insensitive regex over resolved names")
    edit = commands.add_parser("edit", help="edit scalar descriptor fields and write a separate image")
    edit.add_argument("assignments", nargs="+", metavar="VAR.FIELD=VALUE",
                      help="flags/data_rule/linked_counter/event_queue; numeric default/min/max/step/scale; enum default_option/option_mask; bitfield default_mask/editable_mask")
    edit.add_argument("-o", "--output", help="output firmware image (must differ from input)")
    edit.add_argument("--dry-run", action="store_true", help="validate and show changes without writing")
    edit.add_argument("--overwrite", action="store_true", help="replace an existing output file")
    edit.add_argument("--ignore-input-crc", action="store_true", default=argparse.SUPPRESS, help="allow an invalid input CONF CRC")
    return result


def filtered(rows, terms, fields):
    if not terms:
        return rows
    return [row for row in rows if any(term.casefold() in " ".join(str(row.get(k, "")) for k in fields).casefold()
                                      for term in terms)]


def emit_rows(rows, args):
    for row in rows:
        if getattr(args, "verbose", False):
            for key, value in output_fields(row, raw=True).items():
                print(f"  {key}: {value}")
            print()
        else:
            emit(row, getattr(args, "raw", False))


def enum_option_rows(fw, rec):
    if rec["array"] != "g5":
        raise ValueError("var-options requires a g5 enum descriptor")
    lnc = fw.resolve("LNC") if rec["short_name"] == "LAN" else None
    return [dict(var_id=rec["var_id"], short_name=rec["short_name"], long_name=rec["long_name"],
                 index=rec["index"], opt=i,
                 enabled=i in rec["enabled_options"] and
                 (lnc is None or bool(lnc["default_mask"] & (1 << i))),
                 default=i == rec["default_option"],
                 symbol=fw.enum_symbols.get((rec["index"], i)))
            for i in range(rec["option_count"])]


def emit_options(fw, rec, verbose=False):
    rows = enum_option_rows(fw, rec)
    if not verbose:
        for row in rows:
            emit(row)
        return
    print(f"  var_id:   0x{rec['var_id']:04X}  tag={rec['short_name'] or 'n/a'}  name={rec['long_name'] or 'n/a'}")
    print(f"  dispatch: g[5][{rec['index']}]   option_count={rec['option_count']}   "
          f"default_option={rec['default_option']}   option_mask=0x{rec['option_mask']:08X}")
    print("  options:")
    for row in rows:
        flags = [key for key in ("enabled", "default") if row[key]]
        suffix = f" [{','.join(flags)}]" if flags else ""
        print(f"    {row['opt']:3d}: symbol={row['symbol'] or 'n/a'!r}{suffix}")


def emit_descriptor(fw, rec, args):
    if not getattr(args, "verbose", False):
        emit(rec, getattr(args, "raw", False))
        return
    print(f"  var_id:    0x{rec['var_id']:04X} ({rec['var_id']})")
    print(f"  short:     {rec['short_name'] or 'n/a'}")
    print(f"  long:      {rec['long_name'] or 'n/a'}")
    print(f"  Dispatch:  g[{rec['array'][1:]}][{rec['index']}]  (0x{rec['offset']:06X})")
    print()
    for key, value in output_fields(rec, raw=False).items():
        print(f"  {key}: {value}")
    print("  raw: " + " ".join(f"{byte:02X}" for byte in bytes.fromhex(rec["raw"])))
    fields = editable_fields(rec)
    if fields:
        print("  editable_fields: " + " ".join(fields))
    print()
    if rec["array"] == "g5":
        emit_options(fw, rec, verbose=True)


def table_rows(fw, command, rows, *, verbose=False, names_only=False, raw=False):
    """Use the Air11 schema for common concepts, without borrowing its layouts."""
    result = []
    for row in rows:
        if command == "events":
            fields = dict(index=row["index"], offset=row["offset"], code=row["tag"], name=row["name"],
                          fifo_slots=row["fifo_slots"], retained_record_target=row["retained_records"],
                          event_record_bytes=row["event_record_bytes"],
                          default_json_payload_type=row["default_json_payload_type"],
                          file_record_bytes=row["file_record_bytes"])
            if verbose:
                fields.update({key: row[key] for key in ("record_kind", "erase_class", "flag_17",
                              "allocation_group_blocks", "file_init_flag_bit", "reserved_22")})
        elif command == "event-payload-types":
            fields = dict(index=row["index"], offset=row["offset"], event_spool_idx=row["event_spool_index"],
                          event_value=row["event_value"], json_payload_type=row["json_payload_type"],
                          code=row["tag"], name=row["event_name"])
        elif command == "collections":
            fields = dict(collection=row["tag"], collection_idx=row["index"])
            if verbose:
                gate_vid = ROOTS[5].id_base + row["gate_index"]
                fields.update(offset=row["offset"], sample_interval_ms=row["interval_ms"],
                              max_block_duration_seconds=row["max_block_seconds"],
                              file_record_bytes=row["buffer_bytes"], retention_hours=row["retention_hours"],
                              allocation_group_blocks=row["allocation_group_blocks"],
                              file_policy=row["file_policy"], flag_15=row["flag_15"],
                              gate_g5_index=row["gate_index"], gate_var=gate_vid,
                              gate_short=row["gate"], gate_long=fw.long_names[gate_vid],
                              file_init_flag_bit=row["file_init_flag_bit"], signal_count=row["signal_count"])
            fields.update(signal_idx=row["signal_index"], var_id=row["var_id"],
                          short_name=row["short_name"], long_name=row["long_name"], data_id=row["data_id"])
        elif command == "storage-sets":
            counter = row["linked_counter_index"]
            counter_name = fw.names.get(ROOTS[2].id_base + counter) if counter != 0x7fff else None
            counter_text = f"0x{counter:04X}:{counter_name or 'n/a'}"
            if names_only:
                fields = dict(set=row["short_name"], index=row["index"], update_counter=counter_text,
                              count=row["member_count"], names=tuple(
                                  f"{fw.names.get(vid) or 'n/a'}/{fw.long_names[vid] or 'n/a'}"
                                  for vid in row["members"]))
            else:
                for i, vid in enumerate(row["members"]):
                    fields = dict(set=row["short_name"], set_idx=row["index"], item_idx=i,
                                  update_counter=counter_text, var_id=vid,
                                  short_name=fw.names.get(vid), long_name=fw.long_names[vid])
                    if verbose:
                        fields.update(offset=row["offset"], path=row["path"], policy_06=row["policy_06"],
                                      aggregate_counter=row["aggregate_counter"])
                    if raw:
                        fields["raw"] = row["raw"]
                    result.append(fields)
                continue
        elif command == "data-rules":
            fields = dict(rule=row["rule"], callback=row["callback"], registration="pointer_table",
                          source_off=row["source_address"] - FLASH_BASE, use_count=row["use_count"],
                          vars=row["variables"])
        else:
            fields = dict(row)
        if raw and "raw" in row:
            fields["raw"] = row["raw"]
        result.append(fields)
    return result


def tag_filtered(rows, terms, key):
    wanted = {term.upper().lstrip("&") for term in terms}
    return [row for row in rows if not wanted or row[key].upper().lstrip("&") in wanted]


def run_command(fw, args):
    command = args.command or "info"
    if command == "info":
        if getattr(args, "raw", False):
            emit(fw.info())
        else:
            fw.cmd_info()
        return
    if command == "globals":
        rows = fw.global_contents(args.index, args.raw) if args.index is not None else fw.global_map(range(len(ROOTS)), args.raw)
    elif command == "conf-layout":
        rows = sorted(fw.conf_layout(), key=lambda row: row["offset"])
    elif command == "var":
        rows = [fw.resolve(selector) for selector in args.ident]
    elif command == "var-options":
        emit_options(fw, fw.resolve(args.ident), args.verbose)
        return
    elif command == "mode":
        source = fw.mode_rows(args.mode)
        if args.mode is None:
            rows = []
            for row in source:
                count = len(fw.mode_rows(str(row["mode"])))
                rows.append(dict(mode=row["mode"], mode_name=row["name"], baseline_variables=None,
                                 name_scoped_variables=count, total_variables=count,
                                 enabled=row["enabled"], default=row["default"]))
        else:
            modes = {row["mode"]: row["name"] for row in fw.mode_rows()}
            rows = [dict(mode=row["mode"], mode_name=modes[row["mode"]], var_id=row["var_id"],
                         short_name=row["short_name"], long_name=row["long_name"], array=row["array"],
                         index=row["index"], flags=row["flags"], flag_names=row["flag_names"])
                    for row in source]
    elif command == "data-rules":
        if any(rule < 1 or rule >= RULE_COUNT for rule in args.rule):
            raise ValueError("rule ID must be in 1..9 (0 means no callback)")
        rows = [row for row in fw.data_rules() if not args.rule or row["rule"] in args.rule]
    elif command == "events":
        rows = filtered(fw.events(), args.filter, ("tag", "name"))
    elif command == "event-payload-types":
        rows = filtered(fw.event_payload_types(), args.filter, ("tag", "event_name"))
    elif command == "collections":
        rows = tag_filtered(fw.collections(), args.collection, "tag")
    elif command == "storage-sets":
        rows = tag_filtered(fw.selected_records("g7"), args.set, "short_name")
    elif command == "edit":
        if not args.dry_run and not args.output:
            raise ValueError("edit requires -o/--output unless --dry-run is used")
        data, changes = apply_edits(fw, args.assignments)
        if args.output:
            target = Path(args.output)
            if target.resolve() == fw.path.resolve() or (target.exists() and os.path.samefile(fw.path, target)):
                raise ValueError("output path must differ from input, including link aliases")
        if not args.dry_run:
            write_image(fw.path, args.output, data, args.overwrite)
        edited = AirMiniFirmware(fw.path, data=data)
        for change in changes:
            rec = fw.records[change["var_id"]]
            field = change["field"]
            old, new = change["old_raw"], change["new_raw"]
            if field in ("default", "min", "max", "step"):
                updated = edited.records[rec["var_id"]]
                old, new = rec[field], updated[field]
            elif field in ("flags", "default_mask", "editable_mask", "option_mask"):
                width = 4 if field == "flags" else 8
                old, new = f"0x{old:0{width}X}", f"0x{new:0{width}X}"
            print(f"  {rec['long_name'] or rec['short_name']}.{field}: {old} -> {new}")
        print(f"  CONF CRC: 0x{int.from_bytes(data[CONF_END-2:CONF_END], 'big'):04X}")
        print("  Dry run; output not written" if args.dry_run else f"  Wrote {args.output}")
        return
    else:
        rows = fw.selected_records(args.array, args.name)
        if command == "dump-tsv":
            content = make_tsv(rows)
            if args.output == "-":
                sys.stdout.write(content)
            else:
                with open(args.output, "x", encoding="utf-8", newline="") as stream:
                    stream.write(content)
            return
    if command in ("var", "vars") or (command == "globals" and args.index in DESCRIPTOR_ROOTS and args.index not in (7, 10)):
        for row in rows:
            emit_descriptor(fw, row, args)
        return
    table_command = command
    if command == "globals":
        if args.index == 16 and not args.verbose:
            rows = [{key: value for key, value in row.items()
                     if key not in ("field_count", "fields", "source_address")} for row in rows]
        if args.index == 10:
            header = fw.records[331]
            rows = [dict(global_index=10, list="PDL", index=i,
                         offset=fw.u32(header["offset"]+4)-FLASH_BASE+i*2,
                         var_id=vid, short_name=fw.names.get(vid), long_name=fw.long_names[vid],
                         **({"raw": vid.to_bytes(2, "little").hex()} if args.raw else {}))
                    for i, vid in enumerate(header["members"])]
        table_command = {7: "storage-sets", 13: "events", 14: "event-payload-types", 15: "collections"}.get(args.index, command)
    if table_command in ("events", "event-payload-types", "collections", "storage-sets", "data-rules"):
        rows = table_rows(fw, table_command, rows,
                          verbose=getattr(args, "verbose", False) or (command == "globals" and args.index == 15),
                          names_only=getattr(args, "names_only", False), raw=getattr(args, "raw", False))
        # Air11 collections --verbose extends rows instead of switching to prose.
        if table_command in ("collections", "storage-sets"):
            for row in rows:
                emit(row, getattr(args, "raw", False))
            return
    if table_command == "events" and getattr(args, "verbose", False):
        for row in rows:
            print(f"[event {row['index']}]")
            for key, value in output_fields(row, raw=getattr(args, "raw", False)).items():
                print(f"  {key}: {value}")
        return
    emit_rows(rows, args)


def interactive(fw):
    fw.cmd_info()
    while True:
        try:
            line = input("airmini> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if line.lower() in ("quit", "exit", "q"):
            return
        if not line:
            continue
        try:
            words = shlex.split(line)
            if words[0] == "help":
                words = ["--help"] if len(words) == 1 else words[1:] + ["--help"]
            args = parser().parse_args([str(fw.path)] + words)
            if args.interactive:
                raise ValueError("already in interactive mode")
            run_command(fw, args)
        except SystemExit:
            pass  # argparse help/errors should not terminate the shell.
        except (OSError, ValueError, InvalidOperation) as exc:
            print(f"error: {exc}", file=sys.stderr)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.interactive and args.command is not None:
            raise ValueError("-i cannot be combined with a command")
        fw = AirMiniFirmware(args.firmware, ignore_input_crc=args.ignore_input_crc)
        if not fw.crc_ok:
            print("warning: inspecting a CONF block with an invalid CRC", file=sys.stderr)
        if args.interactive:
            interactive(fw)
        else:
            run_command(fw, args)
    except (OSError, ValueError, InvalidOperation) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
