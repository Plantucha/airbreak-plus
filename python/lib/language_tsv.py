"""Shared language identifiers and byte-preserving translation TSV format."""
from pathlib import Path
import re


LANGUAGES = ('EN', 'FR', 'DE', 'IT', 'ES-4', 'ES-5', 'PT-6', 'PT-7', 'NL',
             'SV', 'DA', 'NO', 'FI', 'JA-13', 'RU', 'TR', 'ZH-TW', 'ZH-CN', 'PL', 'JA-19', 'CS')


def language_id(value):
    value = str(value)
    if value.isdecimal():
        return int(value)
    if re.fullmatch(r'0[xX][0-9a-fA-F]+', value):
        return int(value, 16)
    try:
        return LANGUAGES.index(value.upper())
    except ValueError:
        raise ValueError(f'unknown language {value!r}; use a language alias or decimal/0x LAN ID') from None


def escape_text(raw):
    """Preserve all bytes, including non-UTF-8 firmware glyph codes."""
    out = []
    for c in raw.decode('utf-8', errors='surrogateescape'):
        if c == '\\': out.append('\\\\')
        elif c == '\t': out.append('\\t')
        elif c == '\r': out.append('\\r')
        elif c == '\n': out.append('\\n')
        elif 0xdc80 <= ord(c) <= 0xdcff: out.append(f'\\x{ord(c)-0xdc00:02X}')
        elif ord(c) < 32 or ord(c) == 127: out.append(f'\\x{ord(c):02X}')
        else: out.append(c)
    return ''.join(out)


def unescape_text(text):
    out = bytearray()
    i = 0
    while i < len(text):
        c = text[i]
        if c != '\\':
            out.extend(c.encode('utf-8'))
            i += 1
            continue
        i += 1
        if i >= len(text): raise ValueError('trailing backslash')
        c = text[i]
        if c in ('\\', 'n', 'r', 't'):
            out.extend({'\\': b'\\', 'n': b'\n', 'r': b'\r', 't': b'\t'}[c])
            i += 1
        elif c == 'x' and re.fullmatch('[0-9a-fA-F]{2}', text[i+1:i+3]):
            out.append(int(text[i+1:i+3], 16))
            i += 3
        else:
            raise ValueError(f'unknown or incomplete escape at column {i}')
    if 0 in out: raise ValueError('NUL cannot be embedded in a firmware string')
    return bytes(out)


def _tsv_source(path):
    # Do not strip lines: trailing tabs and spaces are meaningful.
    language = None
    records = []
    text = Path(path).read_bytes().decode('utf-8-sig')
    for lineno, line in enumerate(text.split('\n'), 1):
        if line.endswith('\r'): line = line[:-1]
        if line == '': continue
        if line.lstrip().startswith('#'):
            if re.match(r'\s*#\s*language\b', line, re.I):
                try:
                    header = re.fullmatch(r'\s*#\s*language\s*:\s*(\S+)\s*', line, re.I)
                    if not header:
                        raise ValueError('expected # language: LANGUAGE')
                    if language is not None:
                        raise ValueError('duplicate language header')
                    language = language_id(header[1])
                except ValueError as exc:
                    raise ValueError(f'{path}:{lineno}: {exc}') from None
            continue
        records.append((lineno, line))
    return language, records


def read_tsv(path, count, *, skip_english=False):
    language, records = _tsv_source(path)
    if language is None:
        raise ValueError(f'{path}: missing # language: LANGUAGE header')
    if skip_english and language == 0:
        return language, {}
    result = {}
    for lineno, line in records:
        try:
            ident, value = line.split('\t', 1)
            if not re.fullmatch(r'(?:[0-9]+|0[xX][0-9a-fA-F]+)', ident):
                raise ValueError('expected a decimal or hexadecimal text ID')
            tid = int(ident, 16 if ident.lower().startswith('0x') else 10)
            if not 0 <= tid < count: raise ValueError(f'text ID {tid} outside 0..{count-1}')
            if tid in result: raise ValueError(f'duplicate text ID {tid}')
            result[tid] = unescape_text(value)
        except ValueError as exc:
            raise ValueError(f'{path}:{lineno}: {exc}') from None
    return language, result


def export_tsv_entries(language, entries):
    label = LANGUAGES[language] if 0 <= language < len(LANGUAGES) else str(language)
    return (f"# language: {label}\n" +
            "".join(f"{tid}\t{escape_text(raw)}\n" for tid, raw in entries.items())).encode("utf-8")


def load_translations(sources, english, *, skip_english=True):
    """Load sources before filling gaps so an English override is order-independent."""
    count = len(english)
    supplied = {}
    for source in sources:
        language, entries = read_tsv(source, count, skip_english=skip_english)
        if language == 0 and skip_english:
            continue
        if language in supplied:
            raise ValueError(f'duplicate language {language}')
        supplied[language] = (source, entries)
    translations = {0: dict(english)}
    warnings = []
    for language in sorted(supplied):
        source, entries = supplied[language]
        fallback = translations[0]
        for tid in range(count):
            if tid not in entries:
                warnings.append(f'{Path(source).name}: text ID {tid} missing; using English')
                entries[tid] = fallback[tid]
        translations[language] = entries
    return translations, warnings
