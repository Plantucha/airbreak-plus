#!/usr/bin/env python3
"""Explore S9 descriptors using version-scoped UART IDs."""
from __future__ import annotations
import argparse
import csv
import re
import shlex
import struct
import sys
import os
from pathlib import Path
from typing import Iterable, Optional
from lib.s9_firmware import S9Firmware, ConfigRecord, NameEntry, FLASH_BASE, hx, parse_int, flag_text


def iter_firmware_paths(paths: Iterable[str]) -> list[Path]:
    out: list[Path] = []
    for item in paths:
        path = Path(item)
        if path.is_dir():
            out.extend(sorted(path.glob("*.bin")))
        else:
            out.append(path)
    return out


def record_tsv_row(fw: S9Firmware, rec: ConfigRecord) -> dict[str, object]:
    known = ",".join(fw.record_names(rec))
    scale = fw.scale_for(rec)
    scale_text = f"/{scale[0]} {scale[1]}" if scale else ""
    descriptor = fw.resolve(fw.uart_id_for(rec))
    return {
        "idx": rec.idx,
        "off": f"0x{rec.off:05X}",
        "uart_id": f"0x{fw.uart_id_for(rec):04X}",
        "selector_id": f"0x{rec.selector_id:04X}",
        "known": known,
        "option_count": descriptor.option_count,
        "default_raw": rec.default,
        "min_raw": rec.min_value,
        "max_raw": rec.max_value,
        "default": fw.format_value(rec, rec.default),
        "min": fw.format_value(rec, rec.min_value),
        "max": fw.format_value(rec, descriptor.max_value),
        "scale": scale_text,
        "class": f"0x{rec.class_byte:02X}",
        "flags": f"0x{rec.flags:02X}",
        "flag_text": rec.flag_text(),
        "active": int(rec.active),
        "aux0e": f"0x{rec.aux0e:04X}",
        "step_a": rec.step_a,
        "step_b": rec.step_b,
        "aux14": f"0x{rec.aux14:04X}",
        "aux16": f"0x{rec.aux16:04X}",
        "mask": f"0x{rec.mask:04X}",
        "aux1a": f"0x{rec.aux1a:04X}",
        "text0": f"0x{rec.text0:04X}",
        "text1": f"0x{rec.text1:04X}",
        "text2": f"0x{rec.text2:04X}",
        "extra": f"0x{rec.extra:08X}",
    }


def print_info(fw, args):
    modes = [r['text'] for r in fw.options('MOP') if r['enabled']]
    languages = [r['text'] for r in fw.options('LAN') if r['value'] in fw.text_languages]
    print(f"  BID         {fw.bid}")
    print(f"  SID         {fw.cdx_version}")
    print(f"  modes       {', '.join(modes)}")
    print(f"  languages   {len(languages)} ({', '.join(languages)})")
    print(f"  variables   {len(fw.name_lookup.by_value)}")


def var_ref(fw, vid):
    names = '/'.join(fw.names_for_value(vid))
    return f"0x{vid:04X}" + (f":{names}" if names else "")


def descriptor_line(fw, rec):
    line = (f"0x{rec.idx:03X} var={var_ref(fw, rec.uart_id)} "
            f"@0x{FLASH_BASE + rec.off:08X} +0x{rec.idx * rec.stride:04X}  ")
    if rec.flags is not None:
        line += f"fl=0x{rec.flags:04X} [{flag_text(rec.flags):>20s}]  "
    if hasattr(rec, 'field_ids'):
        line += f"{rec.kind}  fields=[{' '.join(var_ref(fw, v) for v in rec.field_ids)}]"
        if rec.kind == 'stream':
            line += f"  trigger={var_ref(fw, rec.trigger_id)}  format={rec.format_code}"
        elif rec.metadata:
            for key in ('enabled', 'format', 'samples'):
                if key in rec.metadata:
                    line += f'  {key}={rec.metadata[key]}'
            if 'trigger_id' in rec.metadata:
                line += '  trigger=' + var_ref(fw, rec.metadata['trigger_id'])
        return line
    if rec.kind in ('string', 'date', 'time'):
        line += f"maxlen={rec.max_value}" if rec.kind == 'string' else rec.kind
        line += '  value=runtime'
    elif rec.option_count is not None:
        key = 'bits' if rec.kind == 'bitfield' else 'opts'
        line += f"def={rec.default}  {key}={rec.option_count:>2}  perm=0x{rec.mask:08X}"
    else:
        scale = fw.divisor(rec)
        unit = fw.text(fw.fl.u16(rec.off + (30 if rec.kind == 'setting' else 16)))
        line += f"def={rec.default / scale:g}  range={rec.min_value / scale:g}..{rec.max_value / scale:g}  div={scale}"
        if unit:
            line += f' [{unit}]'
    if rec.kind == 'setting':
        chain = fw.dependency_chain(rec.uart_id)
        if chain:
            head = chain[0]
            line += f"  dep=0x{head['index']:04X}->{var_ref(fw, head['target_id'])}"
    label = fw.label(rec.uart_id)
    if label:
        line += '  ' + quote_text(label)
    if rec.option_count is not None:
        options = fw.options(rec.uart_id)
        labels = [r['text'] or f"[text#0x{r['text_id']:04X}]" for r in options]
        line += '  (' + ', '.join(labels) + ')'
    return line


def quote_text(value):
    import json
    return json.dumps(value, ensure_ascii=False)


def print_descriptor(fw, rec, args):
    print('  ' + descriptor_line(fw, rec))
    if getattr(args, 'verbose', False):
        print(f'    type       = {rec.kind}   size={rec.stride}')
        if rec.flags is not None:
            print(f'    flags      = 0x{rec.flags:04X} ({flag_text(rec.flags)})')
        if rec.kind == 'setting':
            print(f'    class      = 0x{fw.fl.u8(rec.off + 12):02X}')
        if rec.default is not None:
            print(f'    raw values = default={rec.default} min={rec.min_value} max={rec.max_value}')
        if rec.option_count is not None:
            print('    -- options --')
            for row in fw.options(rec.uart_id):
                print(f"      [{row['value']:>2}] perm={'Y' if row['enabled'] else 'N'}  "
                      f"text=0x{row['text_id']:04X} {quote_text(row['text'])}")
        if rec.kind == 'setting':
            print_chain(fw, rec.uart_id)
        if hasattr(rec, 'field_ids'):
            print(f'    fields     = @0x{FLASH_BASE + rec.fields_offset:08X}')
            for idx, vid in enumerate(rec.field_ids):
                print(f'      [{idx:>2}] {var_ref(fw, vid)}')
            for key, value in getattr(rec, 'metadata', {}).items():
                if key not in ('raw', 'field_ids', 'fields_off', 'off', 'name'):
                    print(f'    {key:<12} = {value}')
        else:
            print('    -- editable fields --')
            print('      ' + ' '.join(fw.editable_fields(rec.uart_id)))
    if getattr(args, 'raw', False) or getattr(args, 'verbose', False):
        print(f'    raw        = {rec.raw.hex(" ")}')


def print_record(fw, rec, args):
    print_descriptor(fw, fw.resolve(fw.uart_id_for(rec)), args)
    if getattr(args, 'text_base', None) is not None:
        for field, ident in (('text0', rec.text0), ('text1', rec.text1), ('text2', rec.text2)):
            print(f'    {field} = {fw.string_at_text_base(args.text_base, ident)!r}')


def print_chain(fw, ident):
    rec = fw.resolve(ident)
    rows = fw.dependency_chain(ident)
    print(f'  Chain from {var_ref(fw, rec.uart_id)} ({len(rows)} nodes):')
    for idx, row in enumerate(rows):
        pipe = '+--' if idx == len(rows) - 1 else '|--'
        print(f"  {pipe} 0x{row['index']:04X} @0x{FLASH_BASE + row['off']:08X} "
              f"target={var_ref(fw, row['target_id'])}  op={row['opcode']}  operand={row['operand']}")
        print('      when ' + fw.condition_text(row['conditions']))
        if row['callback_address'] is not None:
            print(f"      {fw.callback_operations[row['opcode']]} @0x{row['callback_address']:08X}")



def command_table(fw: S9Firmware, args: argparse.Namespace) -> None:
    if args.array != 'setting':
        records = descriptor_tables(fw).get(args.array)
        if records is None:
            raise ValueError(f'unknown S9 table: {args.array}')
        if args.var is not None:
            raise ValueError('--selector applies only to the setting table')
        if args.tsv:
            export_descriptors(fw, records, sys.stdout)
        else:
            for rec in records[:args.limit]:
                if not args.active or rec.active:
                    print_descriptor(fw, rec, args)
        return
    records = fw.records
    if args.active:
        records = [rec for rec in records if rec.active]
    if args.var is not None:
        records = [rec for rec in records if rec.selector_id == args.var]
    if args.known:
        records = [rec for rec in records if bool(fw.record_names(rec))]
    if args.limit is not None:
        records = records[:args.limit]

    if args.tsv:
        fields = list(record_tsv_row(fw, records[0] if records else fw.records[0]).keys())
        writer = csv.DictWriter(sys.stdout, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for rec in records:
            writer.writerow(record_tsv_row(fw, rec))
        return

    for rec in records:
        print_record(fw, rec, args)


def command_var(fw, args):
    if args.index or args.selector:
        value = parse_int(args.ident)
        matches = [fw.record_by_index(value)] if args.index else fw.record_by_selector(value)
        if not matches:
            raise ValueError("no setting descriptor for that dependency selector")
        for rec in matches:
            print_record(fw, rec, args)
        return
    ident = parse_int(args.ident) if re.fullmatch(r"(?i)0x[0-9a-f]+|[0-9]+", args.ident) else args.ident.removeprefix('_').upper()
    rec = fw.resolve(ident)
    print_descriptor(fw, rec, args)


def command_texts(fw: S9Firmware, args: argparse.Namespace) -> None:
    if args.base is not None:
        ids = [parse_int(v) for v in args.ids] if args.ids else sorted(set(fw.text_ref_ids(args.field)))
        for ref_id in ids:
            text = fw.string_at_text_base(args.base, ref_id)
            print(f"{hx(ref_id)}\t{text if text is not None else '-'}")
        return

    ids = [parse_int(v) for v in args.ids] if args.ids else range(fw.text_layout[1])
    for ref_id in list(ids)[:args.limit]:
        row = fw.text_record(ref_id, args.language)
        print(f"  0x{ref_id:04X}: {quote_text(row['text'])}")


def descriptor_summary(fw, value):
    try:
        rec = fw.resolve(value)
    except ValueError as exc:
        if 'descriptor kind not implemented' not in str(exc):
            raise
        return f'var={var_ref(fw, value)}  descriptor=unresolved'
    return descriptor_line(fw, rec)


def print_name_entry(fw, entry):
    print('  ' + descriptor_summary(fw, entry.value))


def command_name(fw: S9Firmware, args: argparse.Namespace) -> None:
    if fw.name_lookup is None:
        raise SystemExit("three-character name resolver not found")

    for item_idx, ident in enumerate(args.idents):
        if item_idx:
            print()
        if re.fullmatch(r"(?i)0x[0-9a-f]+|\d+", ident):
            value = parse_int(ident)
            entries = fw.name_lookup.by_value.get(value, [])
            if not entries:
                print(f"0x{value:04X}\t-")
                continue
            for entry in sorted(entries, key=lambda item: item.name):
                print_name_entry(fw, entry)
            continue

        name = ident.upper()
        entry = fw.name_entry(name)
        if entry is None:
            print(f"{name}\t-")
            continue
        print_name_entry(fw, entry)


def command_names(fw: S9Firmware, args: argparse.Namespace) -> None:
    if fw.name_lookup is None:
        raise SystemExit("three-character name resolver not found")

    entries = fw.name_lookup.entries
    if args.prefix:
        prefix = args.prefix.upper()
        entries = [entry for entry in entries if entry.name.startswith(prefix)]
    if args.contains:
        needle = args.contains.upper()
        entries = [entry for entry in entries if needle in entry.name]
    if args.value is not None:
        entries = [entry for entry in entries if entry.value == args.value]
    if args.limit is not None:
        entries = entries[:args.limit]

    if args.tsv:
        writer = csv.DictWriter(
            sys.stdout,
            fieldnames=["name", "value", "entry_off", "descriptor"],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for entry in entries:
            writer.writerow({
                "name": entry.name,
                "value": f"0x{entry.value:04X}",
                "entry_off": f"0x{entry.off:05X}",
                "descriptor": descriptor_summary(fw, entry.value),
            })
        return

    for entry in entries:
        print_name_entry(fw, entry)


def command_scan(args: argparse.Namespace) -> None:
    paths = iter_firmware_paths(args.paths)
    print("file\tBID\tSID\tvariables\tmodes\tlanguages")
    for path in paths:
        fw = S9Firmware(path)
        modes = ', '.join(r['text'] for r in fw.options('MOP') if r['enabled'])
        languages = ', '.join(r['text'] for r in fw.options('LAN') if r['value'] in fw.text_languages)
        writer = csv.writer(sys.stdout, delimiter='\t', lineterminator='\n')
        writer.writerow((path.name, fw.bid, fw.cdx_version, len(fw.name_lookup.by_value), modes, languages))


def command_compare(args):
    firmwares = [S9Firmware(path) for path in iter_firmware_paths(args.paths)]
    names = sorted(set().union(*(fw.name_lookup.by_name for fw in firmwares)))
    print("name\t" + "\t".join(fw.path.name for fw in firmwares))
    for name in names:
        cells, values = [], []
        for fw in firmwares:
            entry = fw.name_entry(name)
            cell, rec = name_table_cell(fw, entry) if entry else ("absent", None)
            cells.append(cell)
            if rec is None:
                values.append(None)
            elif rec.kind == 'stream':
                values.append((rec.kind, tuple(tuple(fw.names_for_value(v)) or (v,) for v in rec.field_ids),
                               tuple(fw.names_for_value(rec.trigger_id)) or (rec.trigger_id,), rec.format_code))
            elif hasattr(rec, 'field_ids'):
                values.append((rec.kind, tuple(tuple(fw.names_for_value(v)) or (v,) for v in rec.field_ids),
                               tuple(rec.metadata.get('field_formats', ())), rec.metadata.get('enabled')))
            else:
                values.append((rec.kind, rec.default, rec.min_value, rec.max_value, rec.flags, rec.mask))
        if args.changed_only and len(set(values)) <= 1:
            continue
        print(name + "\t" + "\t".join(cells))


def name_table_cell(fw, entry):
    try:
        rec = fw.resolve(entry.value)
    except ValueError as exc:
        if 'descriptor kind not implemented' not in str(exc):
            raise
        return "unmapped descriptor kind", None
    return descriptor_summary(fw, entry.value), rec


def command_compare_names(args: argparse.Namespace) -> None:
    paths = iter_firmware_paths(args.paths)
    if len(paths) != 2:
        raise SystemExit("compare-names expects exactly two firmware files")

    left, right = [S9Firmware(path) for path in paths]
    if left.name_lookup is None or right.name_lookup is None:
        raise SystemExit("three-character name resolver not found in both firmware files")

    left_names = left.name_lookup.by_name
    right_names = right.name_lookup.by_name
    common = sorted(set(left_names) & set(right_names))
    only_left = sorted(set(left_names) - set(right_names))
    only_right = sorted(set(right_names) - set(left_names))

    rows = []
    id_changed = 0
    table_both = 0
    active_changed = 0
    table_presence_changed = 0
    for name in common:
        left_entry = left_names[name]
        right_entry = right_names[name]
        left_cell, left_rec = name_table_cell(left, left_entry)
        right_cell, right_rec = name_table_cell(right, right_entry)
        status = []
        if left_entry.value != right_entry.value:
            status.append("id")
            id_changed += 1
        if left_rec is not None and right_rec is not None:
            table_both += 1
            if left_rec.active != right_rec.active:
                status.append("active")
                active_changed += 1
            for field in ("kind", "default", "min_value", "max_value", "flags", "mask"):
                if getattr(left_rec, field) != getattr(right_rec, field):
                    status.append(field)
            if hasattr(left_rec, 'field_ids') and hasattr(right_rec, 'field_ids'):
                left_fields = [tuple(left.names_for_value(v)) or (v,) for v in left_rec.field_ids]
                right_fields = [tuple(right.names_for_value(v)) or (v,) for v in right_rec.field_ids]
                if left_fields != right_fields:
                    status.append('fields')
        elif left_rec is not None or right_rec is not None:
            status.append("table_presence")
            table_presence_changed += 1
        if not status:
            status.append("same")
        rows.append((name, left_entry, left_cell, left_rec, right_entry, right_cell, right_rec, ",".join(status)))

    print(f"  left        {left.path.name}  SID={left.cdx_version}")
    print(f"  right       {right.path.name}  SID={right.cdx_version}")
    print(
        f"common={len(common)} only_left={len(only_left)} only_right={len(only_right)} "
        f"id_changed={id_changed} table_both={table_both} "
        f"active_changed={active_changed} table_presence_changed={table_presence_changed}"
    )

    if args.list_only:
        if only_left:
            print("only_left\t" + ",".join(only_left))
        if only_right:
            print("only_right\t" + ",".join(only_right))

    if args.mode == "active":
        rows = [row for row in rows if "active" in row[7].split(",")]
    elif args.mode == "table-presence":
        rows = [row for row in rows if "table_presence" in row[7].split(",")]
    elif args.mode == "id":
        rows = [row for row in rows if "id" in row[7].split(",")]
    elif args.mode == "changed":
        rows = [row for row in rows if row[7] != "same"]

    if args.limit is not None:
        rows = rows[:args.limit]

    writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    writer.writerow([
        "name",
        left.path.name + "_id",
        left.path.name + "_descriptor",
        right.path.name + "_id",
        right.path.name + "_descriptor",
        "status",
    ])
    for name, left_entry, left_cell, _left_rec, right_entry, right_cell, _right_rec, status in rows:
        writer.writerow([
            name,
            f"0x{left_entry.value:04X}",
            left_cell,
            f"0x{right_entry.value:04X}",
            right_cell,
            status,
        ])


def add_command_parsers(sub):
    p = sub.add_parser('edit', help='edit known fields using VAR.FIELD=VALUE; values are scaled unless suffixed _raw')
    p.add_argument('assignments', nargs='*')
    p.add_argument('-o', '--output', type=Path)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--overwrite', action='store_true')
    p.add_argument('--ignore-input-crc', action='store_true')
    p.add_argument('--fields', metavar='VAR', help='list fields applicable to a variable')
    for name in ('text', 'strid', 'strinfo', 'raw-strid'):
        p = sub.add_parser(name, help={'text': 'show localized text', 'strid': 'show localized text (Air10 convention)',
                                      'strinfo': 'show localized text record and string pointers',
                                      'raw-strid': 'read the raw string pointer table'}[name])
        p.add_argument('ids', nargs='*' if name == 'strinfo' else '+', type=parse_int)
        p.add_argument('--language', type=parse_int, help='LAN enum value; omitted shows every available language')
    p = sub.add_parser('text-search', help='search resolved firmware text')
    p.add_argument('query')
    p.add_argument('--language', type=parse_int, default=0)
    for name in ('vars', 'search', 'dump-tsv'):
        p = sub.add_parser(name, help={'vars': 'list descriptors, optionally by table and name',
                                      'search': 'search names, labels, option texts and units',
                                      'dump-tsv': 'export descriptors to FILE or stdout (-)'}[name])
        if name == 'dump-tsv':
            p.add_argument('outfile', nargs='?', default='-', help='output path, or - for stdout')
            p.add_argument('--tables', help='comma-separated S9 descriptor kinds')
            p.add_argument('--overwrite', action='store_true')
            p.set_defaults(query=[])
        else:
            p.add_argument('query', nargs='*', default=[])
        p.add_argument('--name', help='filter by UART name or label')
        p.add_argument('--array', choices=['setting', 'numeric', 'enum', 'bitfield', 'string', 'date', 'time'])
        p.add_argument('--active', action='store_true')
        p.add_argument('--limit', type=int)
        p.add_argument('-v', '--verbose', action='store_true', default=argparse.SUPPRESS)
    for name in ('var-options', 'chain', 'refs'):
        p = sub.add_parser(name, help={'var-options': 'show option texts and permitted values',
                                      'chain': 'walk outgoing setting dependencies',
                                      'refs': 'show incoming references to a variable'}[name])
        p.add_argument('ident')
        if name == 'var-options':
            p.add_argument('--language', type=parse_int, default=0)
    p = sub.add_parser('mode', help='list modes or settings referenced by mode conditions')
    p.add_argument('ident', nargs='*', help='mode value or label')
    p.add_argument('--rules', action='store_true', help='show dependency rules whose conditions permit this MOP value; other conditions still apply')
    for name, help_text in {
        'layout': 'show structural roots or named table entries', 'globals': 'alias for layout; S9 uses named roots',
        'events': 'show EDF event records', 'edf-streams': 'show EDF periodic and event records',
        'edf-str': 'show STR summary fields and sources', 'channels': 'show UART streams',
        'collections': 'show record collections', 'storage-sets': 'show storage sets',
        'logs': 'show log and recorded-series descriptors', 'namespaces': 'list UART identifier spaces',
        'callbacks': 'show setting callbacks and callers'}.items():
        p = sub.add_parser(name, help=help_text)
        if name in ('layout', 'globals'):
            p.add_argument('items', nargs='*', metavar='TABLE[:INDEX[,END]]', help='named S9 table; END is exclusive')
        elif name not in ('namespaces', 'callbacks'):
            p.add_argument('name', nargs='?', help='filter by UART name')
    p = sub.add_parser("info", help="show firmware summary")
    p.add_argument("--text-field", default="all", help=argparse.SUPPRESS)
    p.add_argument("--limit", type=int, help=argparse.SUPPRESS)

    p = sub.add_parser("table", help="show descriptors from a named S9 table")
    p.add_argument('array', nargs='?', default='setting', help='S9 descriptor kind (default: setting)')
    p.add_argument("--active", action="store_true", help="only records with flags bit0 set")
    p.add_argument("--known", action="store_true", help="only records with UART names")
    p.add_argument("--selector", "--var", dest="var", type=parse_int, help="filter by legacy setting +0x1C selector")
    p.add_argument("--limit", type=int)
    p.add_argument("--tsv", action="store_true")

    p = sub.add_parser("var", help="show a descriptor by UART name/ID, or explicit setting index/selector")
    p.add_argument("ident", nargs="+", help="UART name, _TAG or numeric UART ID")
    p.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS, help="show multi-line details")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--index", action="store_true", help="interpret ident as setting index")
    g.add_argument("--selector", action="store_true", help="interpret ident as legacy setting +0x1C selector")
    p.add_argument("--text-base", type=parse_int, help="resolve text refs through this pointer-table base")
    p.add_argument("--raw", action="store_true")

    p = sub.add_parser("texts", help="list resolved text records; --base is an explicit raw string-table override")
    p.add_argument("ids", nargs="*")
    p.add_argument("--field", default="all", choices=["all", "text0", "text1", "text2", "extra"])
    p.add_argument("--base", type=parse_int, help="resolve ids using this base")
    p.add_argument("--limit", type=int)
    p.add_argument('--language', type=parse_int, default=0)

    p = sub.add_parser("name", help="resolve three-character CDX/UART names or ids")
    p.add_argument("idents", nargs="+", help="three-character names such as STP, or numeric ids")

    p = sub.add_parser("names", help="dump the three-character CDX/UART resolver table")
    p.add_argument("--prefix", help="only names with this prefix")
    p.add_argument("--contains", help="only names containing this text")
    p.add_argument("--value", type=parse_int, help="only names resolving to this id")
    p.add_argument("--limit", type=int)
    p.add_argument("--tsv", action="store_true")

    p = sub.add_parser("scan-dir", help="summarize one or more firmware files/directories")
    p.add_argument("paths", nargs="+")

    p = sub.add_parser("compare", help="compare named descriptors across firmware files/directories")
    p.add_argument("paths", nargs="+")
    p.add_argument("--changed-only", action="store_true")

    p = sub.add_parser("compare-names", help="compare firmware using the three-character resolver names")
    p.add_argument("paths", nargs=1, help="second firmware image")
    p.add_argument(
        "--mode",
        choices=["active", "table-presence", "id", "changed", "all"],
        default="active",
        help="which common names to print after the summary",
    )
    p.add_argument("--limit", type=int)
    p.add_argument("--list-only", action="store_true", help="also print resolver names present in only one side")

    for parser in sub.choices.values():
        if '--verbose' not in parser._option_string_actions:
            parser.add_argument('-v', '--verbose', action='store_true', default=argparse.SUPPRESS,
                                help='show details')


def build_command_parser(prog="s9"):
    parser = argparse.ArgumentParser(prog=prog)
    parser.set_defaults(verbose=False)
    add_command_parsers(parser.add_subparsers(dest="command"))
    return parser


def build_main_parser():
    parser = argparse.ArgumentParser(description="ResMed S9 - Descriptor Navigator")
    parser.add_argument("firmware", help="raw flash binary")
    parser.add_argument("-i", "--interactive", action="store_true", help="start interactive descriptor shell")
    parser.add_argument("-v", "--verbose", action="store_true", help="show multi-line details")
    add_command_parsers(parser.add_subparsers(dest="command"))
    return parser


build_parser = build_main_parser


def descriptor_tables(fw):
    groups = {}
    for vid in sorted(fw.name_lookup.by_value):
        try:
            rec = fw.resolve(vid)
        except ValueError as exc:
            if 'descriptor kind not implemented' not in str(exc):
                raise
            continue
        groups.setdefault(rec.kind, []).append(rec)
    return groups


def print_layout(fw, args):
    groups = descriptor_tables(fw)
    if args.items:
        for item in args.items:
            name, sep, selection = item.partition(':')
            if name not in groups:
                raise ValueError(f'unknown S9 table: {name}; use ' + ', '.join(groups))
            rows = groups[name]
            if sep:
                parts = selection.split(',')
                if len(parts) not in (1, 2) or any(not p for p in parts):
                    raise ValueError('expected TABLE:INDEX or TABLE:FROM,END')
                start = parse_int(parts[0])
                end = parse_int(parts[1]) if len(parts) == 2 else start + 1
                by_index = {r.idx: r for r in rows}
                if not 0 <= start < end or any(i not in by_index for i in range(start, end)):
                    raise ValueError(f'{name}: index range outside table')
                rows = [by_index[i] for i in range(start, end)]
            for rec in rows:
                print_descriptor(fw, rec, args)
        return
    print('  table             address       stride  count')
    for name, rows in groups.items():
        # Some record families consist of several separately located blocks.
        starts = [r for i, r in enumerate(rows) if i == 0 or r.off != rows[i-1].off + rows[i-1].stride]
        for start in starts:
            block = [start]
            for row in rows[rows.index(start) + 1:]:
                if row.off != block[-1].off + block[-1].stride:
                    break
                block.append(row)
            print(f'  {name:<17} 0x{FLASH_BASE + start.off:08X}  {start.stride:6d}  {len(block):5d}')
    root, count, strings = fw.text_layout
    print(f'  {"texts":<17} 0x{FLASH_BASE + root:08X}  {8:6d}  {count:5d}')
    print(f'  {"string pointers":<17} 0x{FLASH_BASE + strings:08X}  {4:6d}')
    print(f'  {"names":<17} 0x{FLASH_BASE + fw.name_lookup.offset:08X}          {len(fw.name_lookup.entries):5d}')
    print('  S9 uses direct CDX references; selectors above are table names, not globals[] indexes.')


def export_descriptors(fw, rows, output):
    fields = ('table', 'idx', 'var_id', 'uart_name', 'addr', 'offset', 'file_offset',
              'flags', 'flags_str', 'name_str_id', 'name',
              'default', 'max', 'min', 'divisor', 'default_fmt', 'max_fmt', 'min_fmt',
              'range', 'units_str_id', 'units', 'num_options', 'perm_mask',
              'base_str_id', 'option_names', 'dependency_head_idx',
              'dependency_head_var_id', 'dependency_head_name', 'dependency_count', 'maxlen')
    writer = csv.DictWriter(output, fieldnames=fields, delimiter='\t', lineterminator='\n')
    writer.writeheader()
    bases = {kind: min(rec.off for rec in records)
             for kind, records in descriptor_tables(fw).items() if records}
    label_fields = {'setting': 36, 'numeric': 18, 'enum': 12, 'string': 4,
                    'bitfield': 12, 'date': 2, 'time': 2}
    for rec in rows:
        row = dict(table=rec.kind, idx=f'0x{rec.idx:03X}', var_id=f'0x{rec.uart_id:04X}',
                   uart_name='/'.join(fw.names_for_value(rec.uart_id)),
                   addr=f'0x{FLASH_BASE + rec.off:08X}',
                   offset=f'0x{rec.off - bases[rec.kind]:05X}', file_offset=f'0x{rec.off:05X}',
                   flags=f'0x{rec.flags:04X}' if rec.flags is not None else '',
                   flags_str=flag_text(rec.flags) if rec.flags is not None else '',
                   name_str_id=f'0x{fw.fl.u16(rec.off + label_fields[rec.kind]):04X}',
                   name=fw.label(rec.uart_id))
        if rec.kind == 'string':
            row['maxlen'] = rec.max_value
        elif rec.kind not in ('date', 'time'):
            row.update(default=rec.default, max=rec.max_value, min=rec.min_value)
            if rec.option_count is not None:
                options = fw.options(rec.uart_id)
                row.update(num_options=rec.option_count, perm_mask=f'0x{rec.mask:08X}',
                           base_str_id=f"0x{options[0]['text_id']:04X}" if options else '',
                           option_names=' | '.join(
                               f"{r['value']}={'Y' if r['enabled'] else 'N'}:{r['text']}"
                               for r in options))
            else:
                divisor = fw.divisor(rec)
                unit_id = fw.fl.u16(rec.off + (30 if rec.kind == 'setting' else 16))
                row.update(divisor=divisor, units_str_id=f'0x{unit_id:04X}', units=fw.text(unit_id))
                for name, value in (('default', rec.default), ('max', rec.max_value), ('min', rec.min_value)):
                    row[name + '_fmt'] = f'{value / divisor:g}'
                row['range'] = row['min_fmt'] + '..' + row['max_fmt']
        if rec.kind == 'setting':
            chain = fw.dependency_chain(rec.uart_id)
            row['dependency_count'] = len(chain)
            if chain:
                head = chain[0]
                row.update(dependency_head_idx=f"0x{head['index']:04X}",
                           dependency_head_var_id=f"0x{head['target_id']:04X}",
                           dependency_head_name='/'.join(fw.names_for_value(head['target_id'])))
        writer.writerow(row)


def print_text(fw, args):
    ids = args.ids or [0]
    language = args.language
    if args.command == 'strid' and len(ids) == 2 and language is None:
        ids, language = ids[:1], ids[1]
    elif args.command == 'strid' and len(ids) != 1:
        raise ValueError('strid takes TEXT_ID [LANGUAGE]; use text for multiple IDs')
    languages = fw.text_languages if language is None else (language,)
    labels = {r['value']: r['text'] for r in fw.options('LAN')}
    for ident in ids:
        if args.command == 'raw-strid':
            print(f'  0x{ident:04X}: {quote_text(fw.string(ident))}')
            continue
        if args.command == 'strinfo':
            row = fw.text_record(ident, languages[0])
            print(f"  record[0x{ident:04X}] @0x{FLASH_BASE + row['off']:08X}:")
            print(f"    metadata     = 0x{row['metadata']:08X}")
            print(f"    variants     = 0x{FLASH_BASE + row['variants_off']:08X}")
            print(f"    string table = 0x{FLASH_BASE + fw.text_layout[2]:08X}")
        for lang in languages:
            row = fw.text_record(ident, lang)
            label = labels[lang]
            if args.command == 'strinfo':
                address = fw.fl.u32(fw.text_layout[2] + row['string_id'] * 4)
                print(f"    [{label}] raw_idx={row['string_id']} str_ptr=0x{address:08X} -> {quote_text(row['text'])}")
            else:
                prefix = f'0x{ident:04X} ' if len(ids) > 1 else ''
                print(f'  {prefix}{label}: {quote_text(row["text"])}')


def run_command(fw, args):
    command = args.command or "info"
    if getattr(args, 'limit', None) is not None and args.limit < 0:
        raise ValueError('--limit must be non-negative')
    if command == 'edit':
        if args.fields:
            if args.assignments or args.output:
                raise ValueError('--fields cannot be combined with edits or output')
            for name, (off, fmt) in fw.editable_fields(parse_ident(args.fields)).items():
                print(f"  {name:<14} +0x{off:02X}  { {'B': 'u8', 'H': 'u16', 'I': 'u32', 'i': 's32'}[fmt] }")
            return
        if not args.assignments:
            raise ValueError('provide at least one VAR.FIELD=VALUE assignment')
        if not args.dry_run and args.output is None:
            raise ValueError('edit requires --output or --dry-run')
        if args.output:
            if args.output.resolve() == fw.path.resolve() or (args.output.exists() and os.path.samefile(fw.path, args.output)):
                raise ValueError('input and output must be different files')
            if args.output.exists() and not args.overwrite:
                raise ValueError('output exists; use --overwrite')
        data, changes = fw.edited(args.assignments, args.ignore_input_crc)
        for change in changes:
            print('  ' + change)
        if args.dry_run:
            print('  Dry run: validated changes and output CCX CRC; no file written.')
        else:
            from lib.s9_firmware import write_output
            write_output(args.output, data, args.overwrite)
            print(f'  Wrote {args.output}; CCX CRC verified.')
    elif command in ('text', 'strid', 'strinfo', 'raw-strid'):
        print_text(fw, args)
    elif command == 'text-search':
        for ident in range(fw.text_layout[1]):
            value = fw.text(ident, args.language)
            if args.query.casefold() in value.casefold():
                print(f'  0x{ident:04X}: {quote_text(value)}')
    elif command in ('vars', 'search', 'dump-tsv'):
        rows = []
        query = ' '.join(args.query)
        if command == 'vars' and args.query and args.query[0] in ('all', 'setting', 'numeric', 'enum', 'bitfield', 'string', 'date', 'time'):
            if args.array:
                raise ValueError('specify the table either positionally or with --array')
            args.array = None if args.query[0] == 'all' else args.query[0]
            query = ' '.join(args.query[1:])
        if args.name:
            query = (query + ' ' + args.name).strip()
        tables = args.tables.split(',') if command == 'dump-tsv' and args.tables else None
        if tables:
            unknown = set(tables) - set(descriptor_tables(fw))
            if unknown:
                raise ValueError('unknown S9 tables: ' + ', '.join(sorted(unknown)))
        ids = [r.uart_id for name, records in descriptor_tables(fw).items() if name in tables
               for r in records] if tables else fw.data_item_ids()
        for vid in ids:
            rec = fw.resolve(vid)
            names, label = '/'.join(fw.names_for_value(vid)), fw.label(vid)
            if args.array and rec.kind != args.array or args.active and not rec.active:
                continue
            if tables and rec.kind not in tables:
                continue
            search_text = names + ' ' + label
            if command == 'search':
                if rec.option_count is not None:
                    search_text += ' ' + ' '.join(r['text'] for r in fw.options(vid))
                elif rec.kind in ('numeric', 'setting'):
                    search_text += ' ' + fw.text(fw.fl.u16(rec.off + (16 if rec.kind == 'numeric' else 30)))
            if query.casefold() not in search_text.casefold():
                continue
            rows.append((vid, names, label, rec))
        if command == 'dump-tsv':
            records = [r[3] for r in rows[:args.limit]]
            if args.outfile == '-':
                export_descriptors(fw, records, sys.stdout)
            else:
                import io
                target = Path(args.outfile)
                if target.resolve() == fw.path.resolve() or (target.exists() and os.path.samefile(fw.path, target)):
                    raise ValueError('input firmware and TSV output must be different files')
                output = io.StringIO()
                export_descriptors(fw, records, output)
                from lib.s9_firmware import write_output
                write_output(target, output.getvalue().encode('utf-8'), args.overwrite)
                print(f'  Wrote {args.outfile}')
        else:
            for vid, names, label, rec in rows[:args.limit]:
                print_descriptor(fw, rec, args)
            if not rows:
                print(f'  no matches for {quote_text(query)}')
    elif command in ('var-options', 'mode'):
        if command == 'mode':
            args.ident = ' '.join(args.ident) or None
        rows = fw.options(parse_ident(args.ident), args.language) if command == 'var-options' else fw.options('MOP')
        if command == 'mode' and args.ident is not None:
            ident = parse_ident(args.ident)
            rows = [r for r in rows if r['value'] == ident or r['text'].casefold() == args.ident.casefold()]
            if not rows:
                raise ValueError('unknown mode')
        for r in rows:
            print(f"  [{r['value']:>2}] perm={'Y' if r['enabled'] else 'N'}  {quote_text(r['text'])}")
        if command == 'mode' and args.ident is not None and not args.rules:
            rules = list(fw.mode_rules(rows[0]['value']))
            targets = sorted({rule['target_id'] for source, rule in rules})
            print('  Settings referenced by mode conditions (other conditions still apply):')
            for vid in targets:
                print_descriptor(fw, fw.resolve(vid), args)
        if command == 'mode' and args.rules:
            selected = rows[0]['value'] if args.ident is not None else None
            for source, rule in fw.mode_rules(selected):
                print(f"  0x{rule['index']:04X} source={var_ref(fw, source)} "
                      f"target={var_ref(fw, rule['target_id'])}  op={rule['opcode']}  operand={rule['operand']}")
                print('    when ' + fw.condition_text(rule['conditions']))
                if rule['callback_address'] is not None:
                    print(f"    {fw.callback_operations[rule['opcode']]} @0x{rule['callback_address']:08X}")
    elif command == 'callbacks':
        seen = set()
        for source in range(fw.profile.setting_first, fw.profile.setting_first + fw.profile.setting_count):
            for row in fw.dependency_chain(source):
                if row['callback_address'] is not None:
                    seen.add((row['callback'], row['callback_address']))
        for idx, address in sorted(seen):
            print(f'  [{idx:>2}] @0x{address & ~1:08X}  Thumb=0x{address:08X}')
    elif command == 'refs':
        rec = fw.resolve(parse_ident(args.ident))
        rows = fw.references(rec.uart_id)
        print(f'  References to {var_ref(fw, rec.uart_id)} ({len(rows)}):')
        for kind, name, idx, off in rows:
            index = '-' if idx is None else f'0x{idx:04X}'
            print(f'    {kind:<20} {name:<6} idx={index}  @0x{FLASH_BASE + off:08X}')
    elif command == 'namespaces':
        groups = {}
        for vid, entries in sorted(fw.name_lookup.by_value.items()):
            try:
                kind = fw.resolve(vid).kind
            except ValueError as exc:
                if 'descriptor kind not implemented' not in str(exc):
                    raise
                kind = 'unresolved'
            groups.setdefault(kind, []).append((vid, '/'.join(e.name for e in entries)))
        for kind, rows in groups.items():
            print(f'  {kind:<18} {len(rows):4d} IDs')
            if args.verbose or kind == 'unresolved':
                print('    ' + ', '.join(var_ref(fw, vid) for vid, name in rows))
    elif command == 'chain':
        print_chain(fw, parse_ident(args.ident))
    elif command in ('layout', 'globals'):
        print_layout(fw, args)
    elif command in ('channels', 'edf-streams', 'events', 'edf-str', 'collections', 'storage-sets', 'logs'):
        from lib.s9_firmware import UART_STREAM_TABLES
        if command == 'channels':
            for name in UART_STREAM_TABLES[fw.cdx_version][1]:
                if not args.name or args.name.upper() in name:
                    print_descriptor(fw, fw.resolve(name), args)
        elif command in ('collections', 'storage-sets', 'logs'):
            kind = {'collections': 'collection', 'storage-sets': 'storage', 'logs': 'log'}[command]
            for r in fw.records_by_type():
                if args.name and args.name.upper() not in '/'.join(fw.names_for_value(r.uart_id)):
                    continue
                if r.kind == kind or command == 'logs' and r.kind in ('recorded-series', 'recorded-event'):
                    print_descriptor(fw, r, args)
        elif command in ('events', 'edf-streams'):
            if command == 'edf-streams':
                for r in fw.records_by_type():
                    if r.kind == 'edf-periodic' and (not args.name or args.name.upper() in '/'.join(fw.names_for_value(r.uart_id))):
                        print_descriptor(fw, r, args)
            for r in fw.edf_events():
                if not args.name or args.name.upper() in r['name']:
                    print_descriptor(fw, fw.resolve(r['name']), args)
        else:
            for r in fw.str_fields():
                names = '/'.join(fw.names_for_value(r['uart_id'])) or hx(r['uart_id'])
                if args.name and args.name.upper() not in names:
                    continue
                source = '/'.join(fw.names_for_value(r['source_id'])) or str(r['source_id'])
                print(f"  0x{r['index']:03X} var={var_ref(fw, r['uart_id'])} "
                      f"@0x{FLASH_BASE + r['calculation_off']:08X}  samples={r['samples']}  "
                      f"op={r['opcode']}  kind={r['kind']}  source={source}  argument={r['argument']}  fl=0x{r['flags']:04X}")
    elif command == "info":
        if not hasattr(args, "text_field"):
            args.text_field, args.limit = "all", 8
        print_info(fw, args)
    elif command == "var":
        for ident in args.ident:
            item = argparse.Namespace(**vars(args))
            item.ident = ident
            command_var(fw, item)
    elif command in ("compare", "compare-names"):
        item = argparse.Namespace(**vars(args))
        item.paths = [str(fw.path), *args.paths]
        (command_compare if command == "compare" else command_compare_names)(item)
    elif command == "scan-dir":
        command_scan(args)
    else:
        handlers = {"table": command_table, "texts": command_texts,
                    "name": command_name, "names": command_names}
        handlers[command](fw, args)


def parse_ident(value):
    return parse_int(value) if re.fullmatch(r'(?i)0x[0-9a-f]+|[0-9]+', value) else value.removeprefix('_').upper()


def run_repl(fw):
    parser = build_command_parser()
    print("S9 Descriptor Navigator")
    run_command(fw, argparse.Namespace(command="info", verbose=False))
    print('Type "help" for commands, "quit" to exit.')
    while True:
        try:
            line = input("s9> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.lower() in ("quit", "exit", "q"):
            break
        try:
            parts = shlex.split(line)
            if parts == ["help"]:
                parser.print_help()
                continue
            if parts[0] == "help":
                parts = parts[1:] + ["--help"]
            run_command(fw, parser.parse_args(parts))
        except SystemExit:
            pass
        except (ValueError, OSError, IndexError, struct.error) as exc:
            print(f"error: {exc}", file=sys.stderr)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {"info", "table", "var", "texts", "name", "names", "compare", "compare-names"}
    # Accept historical command-first calls; help documents firmware-first.
    if len(argv) >= 2 and argv[0] in commands and not argv[1].startswith("-"):
        argv[:2] = [argv[1], argv[0]]
    if argv and argv[0] == "scan-dir":
        command_scan(build_command_parser().parse_args(argv))
        return 0
    args = build_main_parser().parse_args(argv)
    if args.interactive and args.command is not None:
        raise ValueError("--interactive cannot be combined with a command")
    fw = S9Firmware(Path(args.firmware))
    if args.interactive:
        run_repl(fw)
    else:
        run_command(fw, args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(0)
    except (OSError, ValueError, IndexError, struct.error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
