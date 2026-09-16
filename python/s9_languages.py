#!/usr/bin/env python3
"""Export S9 language TSV files and build an independent language image."""
import argparse
from pathlib import Path
import sys

from lib.firmware_io import paths_alias, write_output
from lib.s9_languages import S9LanguageFirmware, language_id, export_tsv, build_languages, resource_arena


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('inspect', help='Show language IDs, labels and resource capacity')
    export = sub.add_parser('export', help='Export all text IDs of a language')
    export.add_argument('language', type=language_id, help='LAN ID or language code, e.g. 18 or PL')
    export.add_argument('-o', '--output', type=Path, required=True)
    export.add_argument('--overwrite', action='store_true')
    build = sub.add_parser('build', help='Replace the language set; English is always retained')
    build.add_argument('sources', nargs='*', type=Path, help='tsv translation files; no files builds English only')
    build.add_argument('-o', '--output', type=Path)
    build.add_argument('--dry-run', action='store_true')
    build.add_argument('--overwrite', action='store_true')
    build.add_argument('--ignore-input-crc', action='store_true')
    build.add_argument('--allow-relocation', action='store_true',
                       help='Allow moving the string pointer table if needed; CCX and CDX must then be flashed together.')
    args = parser.parse_args(argv)
    try:
        sources = args.sources if args.command == 'build' else []
        fw = S9LanguageFirmware(args.image)
        if args.command == 'inspect':
            start, end, used = resource_arena(fw)
            print(f'Firmware: {fw.cdx_version}; text IDs: 0..{fw.text_layout[1]-1}')
            print(f'LAN mask: 0x{fw.resolve("LAN").mask:X}; default: {fw.resolve("LAN").default}')
            for row in fw.options('LAN'):
                if row['value'] in fw.text_languages:
                    print(f"  {row['value']:2}  {row['text']}")
            print(f'Language arena: 0x{start:05X}..0x{end:05X} (end exclusive); {used} resource bytes / {end-start} capacity')
            return 0
        if args.output:
            inputs = [args.image, *sources]
            if any(paths_alias(args.output, p) for p in inputs):
                raise ValueError('output must differ from the image and source files')
            if args.output.exists() and not args.overwrite:
                raise ValueError('output exists; use --overwrite')
        if args.command == 'export':
            write_output(args.output, export_tsv(fw, args.language), args.overwrite)
            print(f'Exported {fw.text_layout[1]} text IDs to {args.output}')
            return 0
        if args.output is None and not args.dry_run:
            raise ValueError('build requires --output or --dry-run')
        data, warnings, report = build_languages(fw, sources, args.ignore_input_crc, args.allow_relocation)
        for warning in warnings:
            print('WARNING: '+warning, file=sys.stderr)
        print(f"Languages: {report['languages']}; LAN mask: 0x{report['mask']:X}; default: {report['default']}")
        print(f"Texts: {report['texts']}; unique strings: {report['unique_strings']}; English fallbacks: {report['fallbacks']}")
        print(f"Resources: {report['old_used']} -> {report['used']} bytes; free: {report['free']} / {report['capacity']} bytes")
        if report['relocated']:
            print(f"WARNING: String pointer table relocated: 0x{report['table_before']:05X} -> 0x{report['table_after']:05X}. "
                  'CCX and CDX are coupled: flash BOTH regions from this output image.', file=sys.stderr)
        else:
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
