"""ctypes driver for the instrumented CPU harness. GPL-3.0."""
import ctypes as C
from pathlib import Path
import subprocess


class Machine:
    def __init__(self, rom, build_dir):
        here = Path(__file__).resolve().parent
        build_dir = Path(build_dir)
        build_dir.mkdir(parents=True, exist_ok=True)
        library = build_dir / 'nxu8-harness.so'
        sources = [here / 'harness.c', here / 'vendor/SimU8/core.c']
        if not library.exists() or any(p.stat().st_mtime > library.stat().st_mtime for p in here.rglob('*') if p.is_file()):
            subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-fPIC', '-shared',
                            *(str(p) for p in sources), '-o', str(library)], check=True)
        self.lib = C.CDLL(str(library.resolve()))
        self.lib.harness_init.argtypes = [C.c_void_p, C.c_size_t]
        self.lib.harness_set_pc.argtypes = [C.c_uint32]
        self.lib.harness_get_pc.restype = C.c_uint32
        self.lib.harness_set_reg.argtypes = [C.c_uint, C.c_uint8]
        self.lib.harness_get_reg.argtypes = [C.c_uint]
        self.lib.harness_get_reg.restype = C.c_uint8
        self.lib.harness_set_sp.argtypes = [C.c_uint16]
        self.lib.harness_get_sp.restype = C.c_uint16
        self.lib.harness_set_lr.argtypes = [C.c_uint32]
        self.lib.harness_ram.restype = C.POINTER(C.c_uint8 * 65536)
        self.lib.harness_run.argtypes = [C.c_uint64, C.c_uint32, C.c_bool]
        self.lib.harness_trace_open.argtypes = [C.c_char_p, C.c_bool]
        self.ram = self.lib.harness_ram().contents
        self.counts = (C.c_uint64 * 0x18000).in_dll(self.lib, 'execution_counts')
        self.rom_reads = (C.c_uint64 * 0x30000).in_dll(self.lib, 'rom_read_counts')
        self.ram_writes = (C.c_uint64 * 0x10000).in_dll(self.lib, 'ram_write_counts')
        self.rom = rom
        self.reset()

    def reset(self):
        buffer = C.create_string_buffer(self.rom)
        self.lib.harness_init(buffer, len(self.rom))

    def reg(self, index, value=None):
        if value is not None:
            self.lib.harness_set_reg(index, value)
        return self.lib.harness_get_reg(index)

    def er(self, index, value=None):
        if value is not None:
            self.reg(index, value & 255)
            self.reg(index + 1, value >> 8)
        return self.reg(index) | self.reg(index + 1) << 8

    def word(self, address, value=None):
        if value is not None:
            self.ram[address] = value & 255
            self.ram[address + 1] = value >> 8
        return self.ram[address] | self.ram[address + 1] << 8

    def trace_open(self, path, reads=True):
        if self.lib.harness_trace_open(str(Path(path).resolve()).encode(), reads):
            raise OSError(f'Cannot open trace: {path}')

    def trace_close(self):
        self.lib.harness_trace_close()

    def call(self, address, limit=1000000):
        sentinel = 0x2FFFE
        self.lib.harness_set_sp(0x8DEE)
        self.lib.harness_set_lr(sentinel)
        self.lib.harness_set_pc(address)
        status = self.lib.harness_run(limit, sentinel, False)
        if status != 100:
            raise RuntimeError(f'Firmware routine {address:#x}: status={status}, pc={self.lib.harness_get_pc():#x}, last={self.lib.harness_last_address():#x}')
        return [self.reg(i) for i in range(16)]
