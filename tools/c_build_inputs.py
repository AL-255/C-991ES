"""Identify the CMake target inputs and their local header dependencies."""
import re
from pathlib import Path


def implementation_inputs(root, sources):
    """Pin a compiled source list and the quoted headers it actually includes."""
    root = Path(root).resolve()
    source_root = root / 'csrc'
    pending = [root / name for name in sources]
    discovered = set()
    while pending:
        source = pending.pop().resolve()
        if source in discovered:
            continue
        if not source.is_file() or not source.is_relative_to(source_root):
            raise ValueError(f'Invalid target input: {source}')
        discovered.add(source)
        for name in re.findall(r'^\s*#\s*include\s*"([^"]+)"', source.read_text(), re.MULTILINE):
            candidates = ((source.parent / name).resolve(), (source_root / name).resolve())
            header = next((path for path in candidates if path.is_file()), None)
            if header is None:
                raise ValueError(f'Unresolved local include {name} from {source}')
            pending.append(header)
    return sorted(str(path.relative_to(root)) for path in discovered)


def build_inputs(root):
    root = Path(root).resolve()
    cmake = root / 'csrc/CMakeLists.txt'
    names = ['csrc/' + name for name in
             re.findall(r'(?<![\w/])([\w/]+\.c)(?!\w)', cmake.read_text())]
    return ['csrc/CMakeLists.txt'] + implementation_inputs(root, names)
