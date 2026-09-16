#!/usr/bin/env python3
"""Inspect, export and rebuild Air10 firmware languages in CCX."""
import argparse
from pathlib import Path
import sys

from lib.as10_languages import AS10LanguageFirmware, build_languages, export_tsv
from lib.firmware_io import paths_alias, write_output
from lib.language_tsv import language_id


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('inspect', help='Show compiled languages and resource capacity')
    export = sub.add_parser('export', help='Export all text IDs of a language')
    export.add_argument('language', type=language_id, help='Language alias or decimal/0x LAN ID')
    export.add_argument('-o', '--output', type=Path, required=True)
    export.add_argument('--overwrite', action='store_true')
    build = sub.add_parser('build', help='Replace the language set; English is always retained')
    build.add_argument('sources', nargs='*', type=Path, help='TSV translations; no files builds English only')
    build.add_argument('-o', '--output', type=Path)
    build.add_argument('--dry-run', action='store_true')
    build.add_argument('--overwrite', action='store_true')
    build.add_argument('--ignore-input-crc', action='store_true')
    args = parser.parse_args(argv)

    try:
        sources = args.sources if args.command == 'build' else []
        fw = AS10LanguageFirmware(args.image)
        if args.command == 'inspect':
            print(f'Firmware: {fw.cdx_sid}; text IDs: 0..{fw.text_count-1}')
            print(f'LAN mask: 0x{fw.read_u32(fw.lan + fw.G8_BITMASK):X}; default: {fw.read_u8(fw.lan + fw.G8_DEFAULT)}')
            base = fw.read_u16(fw.lan + fw.G8_BASE_STR)
            for language in fw.languages:
                label = fw.texts[base + language, 0].decode('utf-8', errors='replace')
                print(f'  {language:2}  {label}')
            print(f'Language arena: 0x{fw.start:05X}..0x{fw.end:05X} (end exclusive); '
                  f'{fw.used} resource bytes / {fw.end-fw.start} capacity')
            if fw.reserved_ranges:
                print(f'Preserved data: {sum(hi-lo for lo, hi in fw.reserved_ranges)} bytes')
            return 0

        if args.output:
            if any(paths_alias(args.output, path) for path in [args.image, *sources]):
                raise ValueError('output must differ from the image and source files')
            if args.output.exists() and not args.overwrite:
                raise ValueError('output exists; use --overwrite')
        if args.command == 'export':
            write_output(args.output, export_tsv(fw, args.language), args.overwrite)
            print(f'Exported {fw.text_count} text IDs to {args.output}')
            return 0
        if args.output is None and not args.dry_run:
            raise ValueError('build requires --output or --dry-run')

        data, warnings, report = build_languages(fw, sources, args.ignore_input_crc)
        for warning in warnings:
            print('WARNING: ' + warning, file=sys.stderr)
        print(f"Languages: {report['languages']}; LAN mask: 0x{report['mask']:X}; default: {report['default']}")
        print(f"Texts: {report['texts']}; unique strings: {report['unique_strings']}; English fallbacks: {report['fallbacks']}")
        print(f"Resources: {report['old_used']} -> {report['used']} bytes; free: {report['free']} / {report['capacity']} bytes")
        if report['preserved']:
            print(f"Preserved data: {report['preserved']} bytes")
        print('Changes: CCX')
        if args.dry_run:
            print('Dry run: verified output; no image written.')
        else:
            write_output(args.output, data, args.overwrite)
            print(f'Wrote {args.output}')
        return 0
    except (OSError, ValueError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
