"""S9 language TSV files and version-scoped resource rebuilding."""
from pathlib import Path
import binascii
import struct

from .language_tsv import LANGUAGES, language_id, escape_text, unescape_text, read_tsv, export_tsv_entries
from .s9_firmware import S9Firmware, Profile, PROFILES, FLASH_BASE, CCX_END, TEXT_LITERALS


class S9LanguageFirmware(S9Firmware):
    """Language-only profiles do not imply support for executable patches.

    0905 formatter at 0802C280 uses roots at literals 2C2EC/2C2D0.
    Its selector at 0802C2F0 uses setting index 7F (LAN UART ID 1CC).
    Numeric and enum roots delimit 368 text records. Other 0905 record
    namespaces and patch sites are not added to the general firmware profiles.
    """
    # Language structures are selected by CDX; BLX identity is irrelevant.
    check_bootloader_id = False
    profiles = {**PROFILES, 'SX474-0905': Profile(
        'SX525-0300', 0x571C, 0x14D, 176, 0x729C, 9, 262,
        0x9294, 0x10F, 61, 0x9BE8)}
    text_literals = {**TEXT_LITERALS, 'SX474-0905': (0x2C2EC, 0x2C2D0)}

    @property
    def text_languages(self):
        if self.cdx_version != 'SX474-0905':
            return super().text_languages
        # Unlike later selectors, 0905 counts all enabled preceding options
        # without reserving an extra English slot when bit zero is cleared.
        lan = self.resolve('LAN')
        return tuple(i for i in range(lan.option_count) if lan.mask & (1 << i))


def raw_text(fw, tid, language):
    row = fw.text_record(tid, language)
    strings = fw.text_layout[2]
    off = fw.ccx_pointer(fw.fl.u32(strings + 4*row['string_id']), 1)
    end = fw.fl.data.index(0, off, CCX_END-2)
    return fw.fl.data[off:end]


def export_tsv(fw, language):
    if language not in fw.text_languages:
        raise ValueError(f'language {language} is not present in the image')
    entries = {tid: raw_text(fw, tid, language) for tid in range(fw.text_layout[1])}
    return export_tsv_entries(language, entries)


def resource_arena(fw):
    """Validate the known resource area; fonts and descriptors precede it.

    The original 0907/0912/1201/1203 arrays start at 164A0; 1301 at 124A0.
    All nine reference images contain only variant arrays, the string pointer
    table, NUL-terminated strings and zero/FF padding through the CCX CRC.
    Rebuilt images retain that ownership boundary.
    """
    start = 0x124A0 if fw.cdx_version == 'SX474-1301' else 0x164A0
    end = CCX_END-2
    covered = bytearray(end-start)
    def claim(off, size):
        if size < 0 or not start <= off <= end-size:
            raise ValueError(f'language resource outside its arena: 0x{off:X}+{size}')
        covered[off-start:off-start+size] = b'\1'*size
    root, count, strings = fw.text_layout
    ids = set()
    for tid in range(count):
        off = fw.fl.u32(root+tid*8+4)-FLASH_BASE
        claim(off, 2*len(fw.text_languages))
        for j in range(len(fw.text_languages)):
            ids.add(fw.fl.u16(off+2*j))
    if ids != set(range(max(ids)+1)):
        raise ValueError('string IDs are not dense; cannot establish ownership of the pointer table')
    claim(strings, 4*len(ids))
    for sid in ids:
        off = fw.fl.u32(strings+4*sid)-FLASH_BASE
        claim(off, 1)
        terminator = fw.fl.data.find(b'\0', off, end)
        if terminator < 0: raise ValueError('unterminated language string')
        claim(off, terminator-off+1)
    for i, byte in enumerate(fw.fl.data[start:end]):
        if not covered[i] and byte not in (0, 255):
            raise ValueError(f'unowned data at 0x{start+i:X}; refusing to reclaim the language arena')
    return start, end, sum(covered)


def place_resources(start, end, table, variants, stride, indexes, pool):
    """Keep the pointer table fixed; pack arrays and strings around it."""
    table_size = 4*len(indexes)
    if table < start or table % 4 or table+table_size > end:
        raise ValueError('pointer table does not fit at its current address')
    gaps = [(start, table), (table+table_size, end)]
    items = []
    for offset in range(0, len(variants), stride):
        items.append(('variant', offset//stride, bytes(variants[offset:offset+stride]), 4))
    for sid, offset in enumerate(indexes):
        stop = indexes[sid+1] if sid+1 < len(indexes) else len(pool)
        items.append(('string', sid, bytes(pool[offset:stop]), 1))
    addresses, writes = {}, []
    for kind, index, raw, alignment in sorted(items, key=lambda x: (-len(x[2]), -x[3], x[0], x[1])):
        choices = []
        for gi, (lo, hi) in enumerate(gaps):
            pos = (lo+alignment-1)&~(alignment-1)
            if pos+len(raw) <= hi:
                choices.append((hi-lo-len(raw), pos, gi))
        if not choices:
            raise ValueError('resources cannot be packed around the current pointer table')
        _, pos, gi = min(choices)
        lo, hi = gaps.pop(gi)
        gaps.extend((a,b) for a,b in ((lo,pos),(pos+len(raw),hi)) if a<b)
        addresses[kind,index] = pos
        writes.append((pos,raw))
    writes.append((table,b''.join(struct.pack('<I', FLASH_BASE+addresses['string',sid]) for sid in range(len(indexes)))))
    return writes, [addresses['variant',i] for i in range(len(variants)//stride)]


def build_languages(fw, sources, ignore_input_crc=False, allow_relocation=False):
    bad = fw.invalid_crcs()
    if bad and not ignore_input_crc:
        raise ValueError('invalid input CRC: '+', '.join(bad))
    start, end, old_used = resource_arena(fw)
    root, count, old_strings = fw.text_layout
    lan = fw.resolve('LAN')
    translations = {0: {i: raw_text(fw, i, 0) for i in range(count)}}
    warnings = []
    for source in sources:
        source = Path(source)
        lang, entries = read_tsv(source, count)
        if not 0 < lang < lan.option_count:
            raise ValueError(f'{source}: language must be within 1..{lan.option_count-1}; English comes from the image')
        if lang in translations: raise ValueError(f'duplicate language {lang}')
        for tid in range(count):
            if tid not in entries:
                warnings.append(f'{Path(source).name}: text ID {tid} missing; using English')
                entries[tid] = translations[0][tid]
        translations[lang] = entries
    languages = sorted(translations)
    # Each variant array starts on a 4-byte boundary, as in original images.
    stride = (len(languages)*2+3)&~3
    variants = bytearray(count*stride)
    pool, unique, indexes = bytearray(), {}, []
    for tid in range(count):
        for j, lang in enumerate(languages):
            raw = translations[lang][tid]
            if raw not in unique:
                unique[raw] = len(indexes)
                indexes.append(len(pool))
                pool.extend(raw+b'\0')
            sid = unique[raw]
            if sid > 65535: raise ValueError('string ID exceeds 16-bit capacity')
            struct.pack_into('<H', variants, tid*stride+2*j, sid)
    used = len(variants)+4*len(indexes)+len(pool)
    if used > end-start:
        raise ValueError(f'language resources need {used} bytes; arena has {end-start} (short by {used-(end-start)})')
    strings = old_strings
    try:
        writes, variant_addresses = place_resources(start,end,strings,variants,stride,indexes,pool)
    except ValueError as exc:
        if not allow_relocation:
            raise ValueError(f'{exc}; use --allow-relocation to move the table. '
                             'Relocation couples CCX and CDX: flash both regions from the same output image.') from None
        strings = start+len(variants)
        pool_start = strings+4*len(indexes)
        blob = variants + b''.join(struct.pack('<I', FLASH_BASE+pool_start+i) for i in indexes) + pool
        writes = [(start,blob)]
        variant_addresses = [start+i*stride for i in range(count)]
    data = bytearray(fw.fl.data)
    data[start:end] = b'\xff'*(end-start)
    for off, raw in writes:
        data[off:off+len(raw)] = raw
    for tid in range(count):
        struct.pack_into('<I', data, root+tid*8+4, FLASH_BASE+variant_addresses[tid])
    string_literal = fw.text_literals[fw.cdx_version][1]
    struct.pack_into('<I', data, string_literal, FLASH_BASE+strings)
    mask = sum(1<<lang for lang in languages)
    struct.pack_into('<I', data, lan.off+24, mask)
    if lan.default not in languages: struct.pack_into('<i', data, lan.off, 0)
    for name, lo, hi in fw.regions:
        if name == 'BLX':
            continue
        # Do not silently fix a previously invalid CDX when research override is used
        # unless the string-table root actually changes that region.
        if data[lo:hi-2] != fw.fl.data[lo:hi-2]:
            struct.pack_into('>H', data, hi-2, binascii.crc_hqx(data[lo:hi-2], 65535))
    result = type(fw)(fw.path, data)
    for tid in range(count):
        for lang in languages:
            if raw_text(result, tid, lang) != translations[lang][tid]:
                raise ValueError(f'output verification failed: text {tid}, language {lang}')
    resource_arena(result)
    return bytes(data), warnings, {
        'languages': languages, 'texts': count, 'unique_strings': len(indexes),
        'old_used': old_used, 'used': used, 'capacity': end-start,
        'free': end-start-used, 'fallbacks': len(warnings),
        'mask': mask, 'default': result.resolve('LAN').default,
        'table_before': old_strings, 'table_after': strings, 'relocated': strings != old_strings,
    }
