"""Atomic output and input/output alias checks for firmware tools."""
import os
from pathlib import Path
import tempfile


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


def paths_alias(a, b):
    a, b = Path(a), Path(b)
    return a.resolve() == b.resolve() or (a.exists() and b.exists() and os.path.samefile(a, b))

