"""Air10 language resources built on the patcher's firmware framework."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import re
import struct

from .as10_firmware import ASFirmware
from .language_tsv import export_tsv_entries, read_tsv, load_translations


class AS10LanguageFirmware(ASFirmware):
    """Read and validate the CCX string layout without a per-CDX address map."""

    def __init__(self, path, data=None):
        self.path = Path(path)
        data = self.path.read_bytes() if data is None else bytes(data)
        if len(data) != 0x100000:
            raise ValueError('expected a complete 1 MiB Air10 firmware image')
        with redirect_stdout(io.StringIO()):
            super().__init__(io.BytesIO(data), validate_crc=False)
        self.data = data

        self.g2 = self.globals_offset(2)
        g3 = self.globals_offset(3)
        if not self.ccx_off <= self.g2 < g3 < self.ccx_off + self.ccx_size:
            raise ValueError('invalid g[2]/g[3] bounds')
        if (g3 - self.g2) % 8:
            raise ValueError('g[2] does not contain complete 8-byte records')
        self.text_count = (g3 - self.g2) // 8

        self.load_firmware_string_metadata()
        self.languages = tuple(self.fw_lang_ids)
        self.lan = self.find_var('LAN')
        self.lnc = self.find_var('LNC')
        self.option_count = self.read_u8(self.lan + self.G8_NUM_OPTIONS)
        if not 0 < self.option_count <= 32 or self.languages[0] != 0:
            raise ValueError('unsupported LAN layout: English must occupy the first slot')
        if self.languages[-1] >= self.option_count:
            raise ValueError('compiled language ID exceeds LAN option count')

        self.start = self.read_u32(self.g2 + 4) - self.FLASH_BASE
        self.end = self.ccx_off + self.ccx_size - 2
        self.root = self.start - 8
        # The CCX accessor returns the adjacent root with ADDW r0,pc,#4; BX lr.
        # Preserve this entry point and root; only their pointed-to data moves.
        if not g3 <= self.root - 8 < self.start < self.end:
            raise ValueError('invalid CCX language resource bounds')
        if self.read_bytes(self.root - 8, 8) != bytes.fromhex('0ff2040070470000'):
            raise ValueError('unrecognized CCX raw-string table accessor')
        self.raw_table = self._raw_string_table_offset()
        self.used, self.texts = self._read_resources()

    def _read_resources(self):
        """Reclaim referenced resources and padding, preserving unrelated bytes.

        Custom label rewrites can leave old, unreferenced text behind. Within
        each unowned interval, reserve the span from first to last non-padding
        byte; this also preserves any embedded zero/FF bytes in unknown data.
        """
        covered = bytearray(self.end - self.start)

        def claim(off, size):
            if size < 0 or not self.start <= off <= self.end - size:
                raise ValueError(f'language resource outside CCX arena: 0x{off:X}+{size}')
            covered[off-self.start:off-self.start+size] = b'\1' * size

        stride = (2 * len(self.languages) + 3) & ~3
        arrays = set()
        indexes = {}
        for tid in range(self.text_count):
            row = self.read_u32(self.g2 + tid * 8 + 4) - self.FLASH_BASE
            if row % 4:
                raise ValueError(f'unaligned locale array for string {tid}')
            claim(row, stride)
            arrays.add((row, row + stride))
            for slot, language in enumerate(self.languages):
                indexes[tid, language] = self.read_u16(row + slot * 2)

        ids = set(indexes.values())
        if ids != set(range(max(ids) + 1)):
            raise ValueError('raw string IDs are not dense; cannot establish pointer table ownership')
        raw_end = self.raw_table + 4 * len(ids)
        if any(lo < raw_end and hi > self.raw_table for lo, hi in arrays):
            raise ValueError('raw pointer table overlaps locale arrays')
        claim(self.raw_table, 4 * len(ids))
        tables = sorted(arrays | {(self.raw_table, raw_end)})
        if any(hi > next_lo for (_, hi), (next_lo, _) in zip(tables, tables[1:])):
            raise ValueError('overlapping language tables')

        strings = {}
        for sid in ids:
            off = self.read_u32(self.raw_table + sid * 4) - self.FLASH_BASE
            claim(off, 1)
            end = self.data.find(b'\0', off, self.end)
            if end < 0:
                raise ValueError(f'unterminated raw string {sid}')
            if any(lo <= end and hi > off for lo, hi in tables):
                raise ValueError(f'raw string {sid} overlaps language tables')
            claim(off, end - off + 1)
            strings[sid] = self.data[off:end]

        self.available = bytearray(b'\1' * len(covered))
        self.reserved_ranges = []
        pos = 0
        while True:
            lo = covered.find(b'\0', pos)
            if lo < 0:
                break
            hi = covered.find(b'\1', lo)
            if hi < 0:
                hi = len(covered)
            gap = self.data[self.start+lo:self.start+hi]
            if gap.strip(b'\0\xff'):
                first = lo + len(gap) - len(gap.lstrip(b'\0\xff'))
                last = lo + len(gap.rstrip(b'\0\xff'))
                self.available[first:last] = bytes(last - first)
                self.reserved_ranges.append((self.start + first, self.start + last))
            pos = hi
        return sum(covered), {key: strings[index] for key, index in indexes.items()}

    def invalid_crcs(self):
        return [name for name, off, size in self.firmware_blocks()
                if self.crcfunc(self.read_bytes(off, size)) != 0]


def export_tsv(fw, language):
    if language not in fw.languages:
        raise ValueError('language is not present in the image')
    return export_tsv_entries(language, {tid: fw.texts[tid, language] for tid in range(fw.text_count)})


def build_languages(fw, sources, ignore_input_crc=False, *, skip_english=True):
    bad = fw.invalid_crcs()
    if bad and not ignore_input_crc:
        raise ValueError('invalid input CRC: ' + ', '.join(bad))

    count = fw.text_count
    english = {tid: fw.texts[tid, 0] for tid in range(count)}
    translations, warnings = load_translations(sources, english, skip_english=skip_english)
    if any(not 0 <= lang < fw.option_count for lang in translations):
        raise ValueError(f'language must be within 0..{fw.option_count-1}')

    languages = sorted(translations)
    mask = sum(1 << language for language in languages)
    if mask & ((1 << 13) | (1 << 19)) and mask & ((1 << 16) | (1 << 17)):
        raise ValueError('Japanese and Chinese cannot be enabled together: firmware uses one font family')

    # Distinguish regional variants only when both are included and their menu
    # labels collide. Preserve distinct custom labels and explicitly empty text.
    base_str = fw.read_u16(fw.lan + fw.G8_BASE_STR)
    for first, second, first_suffix, second_suffix in (
        (4, 5, b' (ES)', b' (LatAm)'),
        (6, 7, b' (PT)', b' (BR)'),
        (16, 17, b' (TW)', b' (CN)'),
    ):
        if first not in translations or second not in translations:
            continue
        for texts in translations.values():
            label = texts[base_str + first]
            if label and label == texts[base_str + second]:
                texts[base_str + first] = label + first_suffix
                texts[base_str + second] = label + second_suffix

    # Allocate by UTF-8 bytes, but g[2] length metadata counts characters.
    lengths = []
    for tid in range(count):
        longest = 0
        for language in languages:
            try:
                length = len(translations[language][tid].decode('utf-8'))
            except UnicodeDecodeError:
                raise ValueError(f'string {tid}, language {language}: invalid UTF-8') from None
            if length > 255:
                raise ValueError(f'string {tid}, language {language}: {length} characters exceeds the 8-bit length accessor')
            longest = max(longest, length)
        lengths.append(longest)

    stride = (2 * len(languages) + 3) & ~3
    array_size = count * stride
    entries = count * len(languages)
    if entries > 65536:
        raise ValueError('raw string indexes exceed 16-bit capacity')
    pool, shared = bytearray(), {}
    for tid in range(count):
        for language in languages:
            text = translations[language][tid]
            if text not in shared:
                shared[text] = len(pool)
                pool.extend(text + b'\0')
    tail_size = 4 * entries + len(pool)
    used = array_size + tail_size
    capacity = sum(fw.available)
    if used > capacity:
        raise ValueError(f'language resources need {used} bytes; arena has {capacity} (short by {used-capacity})')

    # Keep the first locale row adjacent to the CCX root for existing readers.
    # The pointer table/text block can occupy any remaining contiguous gap.
    free = bytearray(fw.available)
    if 0 in free[:array_size]:
        raise ValueError('expanded locale arrays would overwrite preserved data')
    free[:array_size] = bytes(array_size)
    pos = free.find(b'\1' * tail_size)
    while pos >= 0 and (fw.start + pos) % 4:
        pos = free.find(b'\1' * tail_size, pos + 1)
    if pos < 0:
        raise ValueError(f'no contiguous space for {tail_size} bytes of pointers/text after preserving unrelated data')
    raw_table = fw.start + pos
    pool_start = raw_table + 4 * entries

    data = bytearray(fw.data)
    for i, available in enumerate(fw.available):
        if available:
            data[fw.start + i] = 255
    data[pool_start:pool_start+len(pool)] = pool
    for tid in range(count):
        row = fw.start + tid * stride
        data[row:row+stride] = bytes(stride)
        struct.pack_into('<H', data, fw.g2 + tid * 8, lengths[tid])
        struct.pack_into('<I', data, fw.g2 + tid * 8 + 4, fw.FLASH_BASE + row)
        for slot, language in enumerate(languages):
            # Separate entries let redefine_fw_string change one label without
            # affecting another. Only the pointed-to text bytes are shared.
            index = tid * len(languages) + slot
            struct.pack_into('<H', data, row + slot * 2, index)
            struct.pack_into('<I', data, raw_table + index * 4,
                             fw.FLASH_BASE + pool_start + shared[translations[language][tid]])

    struct.pack_into('<I', data, fw.root, fw.FLASH_BASE + raw_table)
    struct.pack_into('<I', data, fw.lan + fw.G8_BITMASK, mask)
    if data[fw.lan + fw.G8_DEFAULT] not in languages:
        data[fw.lan + fw.G8_DEFAULT] = 0

    # As in unlock_languages, do not let EEPROM restore an old LNC mask.
    # LAN maps compiled slots; LNC enables them and selects the font family.
    flags = fw.read_u16(fw.lnc + fw.G6_FLAGS) & ~1
    struct.pack_into('<H', data, fw.lnc + fw.G6_FLAGS, flags)
    struct.pack_into('<I', data, fw.lnc + fw.G6_DEFAULT, mask)
    struct.pack_into('>H', data, fw.end, fw.crcfunc(data[fw.ccx_off:fw.end]))

    result = type(fw)(fw.path, data)
    if result.languages != tuple(languages):
        raise ValueError('output language mapping verification failed')
    for tid in range(count):
        for language in languages:
            if result.texts[tid, language] != translations[language][tid]:
                raise ValueError(f'output verification failed: string {tid}, language {language}')
        if result.read_u16(result.g2 + tid * 8) != lengths[tid]:
            raise ValueError(f'output length verification failed: string {tid}')
    if result.crcfunc(data[fw.ccx_off:fw.end+2]) != 0:
        raise ValueError('output CCX CRC verification failed')
    if data[:fw.ccx_off] != fw.data[:fw.ccx_off] or data[fw.end+2:] != fw.data[fw.end+2:]:
        raise ValueError('language rebuild changed data outside CCX')
    for lo, hi in fw.reserved_ranges:
        if data[lo:hi] != fw.data[lo:hi]:
            raise ValueError(f'language rebuild changed preserved data at 0x{lo:X}')

    fallbacks = len(warnings)
    if re.fullmatch(r'SX\d{3}-\d{4}[+!~][0-9A-Za-z]{3,4}', fw.cdx_sid):
        warnings.append('image has an Airbreak build stamp; stock translations may overwrite custom labels. '
                        'Prefer rebuilding languages before patching, or use translations adapted to this image.')
    return bytes(data), warnings, {
        'languages': languages, 'texts': count, 'unique_strings': len(shared),
        'old_used': fw.used, 'used': used, 'capacity': capacity,
        'free': capacity - used, 'fallbacks': fallbacks,
        'preserved': fw.end - fw.start - capacity,
        'mask': mask, 'default': result.read_u8(result.lan + result.G8_DEFAULT),
        'table_before': fw.raw_table, 'table_after': raw_table,
    }
