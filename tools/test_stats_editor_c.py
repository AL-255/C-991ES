#!/usr/bin/env python3
"""Full persistent-RAM differential checks for statistics editor primitives."""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from c_verification import write_report
from nxu8.machine import Machine


class Platform(C.Structure):
    _fields_ = [('rom', C.POINTER(C.c_uint8)), ('rom_size', C.c_size_t),
                ('ram', C.POINTER(C.c_uint8)), ('callback_pending', C.c_uint8),
                ('status', C.c_int)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=1000)
    args = parser.parse_args()
    build = ROOT / 'analysis/build/stats-editor'
    build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/platform/fx_platform.c', 'csrc/stats/fx_stats_editor.c']
    library = build / 'fx-stats-editor.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-fPIC', '-shared', *(str(ROOT / p) for p in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library)); platform_ptr = C.POINTER(Platform)
    lib.fx_stats_editor_columns.argtypes = [platform_ptr]
    lib.fx_stats_editor_columns.restype = C.c_uint8
    lib.fx_stats_editor_address_raw.argtypes = [platform_ptr,C.c_uint8,C.c_uint8,C.c_uint16]
    lib.fx_stats_editor_address_checked.argtypes = [platform_ptr,C.c_uint8,C.c_uint8,C.POINTER(C.c_uint16)]
    for name in ('write_raw','read_raw'):
        getattr(lib,'fx_stats_editor_'+name).argtypes = [platform_ptr,C.c_uint8,C.c_uint8,C.c_uint16]
    for name in ('insert','delete','move'):
        getattr(lib,'fx_stats_editor_'+name).argtypes = [platform_ptr,C.c_uint8]
    lib.fx_stats_editor_clear.argtypes = [platform_ptr]
    lib.fx_stats_editor_commit.argtypes = [platform_ptr,C.c_uint16]
    lib.fx_take_callback.argtypes = [platform_ptr]
    lib.fx_take_callback.restype = C.c_uint8
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    rom_buffer = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
    machine = Machine(rom, build / 'oracle')
    machine.lib.harness_callback.restype = C.c_uint32
    rng = random.Random(0x1d426)
    checks = {}

    def make_state(mode=3,model=1,frequency=0,rows=3,reserved=0,**fields):
        data = bytearray(rng.randbytes(65536))
        data[0x80f9]=mode; data[0x80fa]=model; data[0x8109]=frequency
        data[0x80de]=rows; data[0x80df]=reserved
        data[0x811c:0x811f]=bytes([1,1,1])
        for address,value in fields.items(): data[int(address,16)]=value
        return data

    def run(name,entry,state,arguments=(),registers=(),detail=''):
        ram = (C.c_uint8 * 65536).from_buffer_copy(state)
        platform = Platform(rom_buffer,len(rom),ram,0,0)
        machine.reset(); C.memmove(machine.ram,bytes(state),65536)
        for register,value in registers: machine.reg(register,value)
        regs = machine.call(entry,2000000)
        native_callback = machine.lib.harness_callback()
        result = getattr(lib,'fx_stats_editor_'+name)(C.byref(platform),*arguments)
        expected,actual = bytes(machine.ram),bytes(ram)
        if actual[:0x8d00]!=expected[:0x8d00] or actual[0x8dee:]!=expected[0x8dee:]:
            differences = [(hex(i),a,b) for i,(a,b) in enumerate(zip(actual,expected))
                           if a!=b and not 0x8d00<=i<0x8dee]
            raise AssertionError((name,detail,arguments,'RAM',differences[:30]))
        if result!=regs[0]: raise AssertionError((name,detail,arguments,'status',result,regs[0]))
        callback = lib.fx_take_callback(C.byref(platform))
        if callback!=native_callback: raise AssertionError((name,arguments,'callback',callback,native_callback))
        checks[name+'_full_ram_status_callback'] = checks.get(name+'_full_ram_status_callback',0)+1
        return ram,platform,result

    contexts = [(3,1,0),(3,1,1),(3,2,0),(3,2,1),(12,1,0),(12,2,1),
                (0x88,1,0),(0x88,2,1),(1,1,0),(1,2,255)]
    for mode,model,frequency in contexts:
        for option in (0,1,2,255):
            for bits in (0,0x80,255):
                data = make_state(mode,model,frequency,**{'810e':option,'8138':bits})
                run('columns',0x5110,data)
    # Native output pointer aliases are observable before geometry is read.
    output_slots = [0x8700,0x8000,0x80de,0x80df,0x80f9,0x80fa,0x8109,
                    0x810e,0x812a,0x8138,0x82ee,0xf000,0xffff,0x100]
    for mode,model,frequency in contexts:
        for selector in (0,1,2,3,4,255):
            for row in (0,1,3,4,255):
                for slot in output_slots:
                    data=make_state(mode,model,frequency,reserved=2)
                    run('address_raw',0x5096,data,(selector,row,slot),
                        ((0,selector),(1,row),(2,slot&255),(3,slot>>8)))
    for _ in range(args.random_cases):
        data=make_state(rng.randrange(256),rng.randrange(256),rng.randrange(256),
                        rng.randrange(256),rng.randrange(256),
                        **{'810e':rng.randrange(256),'8138':rng.randrange(256)})
        selector,row=rng.randrange(256),rng.randrange(256)
        slot=rng.choice(output_slots)
        run('address_raw',0x5096,data,(selector,row,slot),
            ((0,selector),(1,row),(2,slot&255),(3,slot>>8)))

    def cell_address(data,selector,row):
        mode,model,freq=data[0x80f9],data[0x80fa],data[0x8109]
        cols=(2 if mode==12 else (3 if data[0x810e] and not(data[0x8138]&128) else 2)
              if mode==0x88 else (1 if model==1 else 2)+(freq!=0))
        base=0x82ee+10*((data[0x80de]*cols)&255) if selector==3 else 0x82ee
        offset=10*((((row-1)&255)*(1 if selector==3 else cols))&255)
        if selector!=3: offset+=10*(1 if selector==2 and model==1 else selector)
        return (base+offset)&65535

    def avoids_stack(address):
        return all(not 0x8d00<=((address+i)&65535)<0x8dee for i in range(10))

    for operation,entry in [('write_raw',0x1d66c),('read_raw',0x1d6ac)]:
        for mode,model,frequency in contexts[:4]:
            for selector in (0,1,2,3):
                for row in (0,1,3,4):
                    for offset in range(-11,12):
                        data=make_state(mode,model,frequency,reserved=2)
                        pointer=(cell_address(data,selector,row)+offset)&65535
                        if avoids_stack(pointer) and avoids_stack(cell_address(data,selector,row)):
                            run(operation,entry,data,(selector,row,pointer),
                                ((0,selector),(1,row),(2,pointer&255),(3,pointer>>8)))
        for _ in range(args.random_cases):
            mode,model,frequency=rng.choice(contexts)
            data=make_state(mode,model,frequency,rng.randrange(10),rng.randrange(5))
            selector,row=rng.randrange(5),rng.choice((0,1,2,9,255))
            pointer=rng.choice((0,0x100,0x7ffc,0x8000,0x80de,0x80f9,0x8100,
                                0x82ee,0x8700,0xf000,0xfffc))
            if avoids_stack(cell_address(data,selector,row)):
                run(operation,entry,data,(selector,row,pointer),
                    ((0,selector),(1,row),(2,pointer&255),(3,pointer>>8)))
    # Prepared reserve records shift with rows and count toward capacity.
    for mode,model,frequency in contexts:
        for rows in (0,1,2,19,20,25,26,39,40,79,80,255):
            for reserve in (0,1,2,39,40,79,80,255):
                for row in (0,1,2,rows,min(rows+1,255),min(rows+2,255),255):
                    data=make_state(mode,model,frequency,rows,reserve)
                    run('insert',0x1d426,data,(row,),((0,row),))
                    # Row deletion assumes a prepared region that does not
                    # overwrite the CPU's own stack while copying the table.
                    if rows<=40 and reserve<=2:
                        run('delete',0x1d550,data,(row,),((0,row),))
    for _ in range(args.random_cases):
        mode,model,frequency=rng.choice(contexts)
        rows,reserve=rng.randrange(41),rng.randrange(3)
        row=rng.choice((0,1,rows,(rows+1)&255,rng.randrange(256)))
        data=make_state(mode,model,frequency,rows,reserve)
        run('insert',0x1d426,data,(row,),((0,row),))
        run('delete',0x1d550,data,(row,),((0,row),))
    for mode in (0,1,2,3,12,0x88,255):
        for _ in range(20): run('clear',0x1d60a,make_state(mode,rows=rng.randrange(256)))
    keys=(0xe0,0xe1,0xe2,0xe3,0xed,0,0xff)
    for mode,model,frequency in contexts:
        for rows in (0,1,2,3,19,20,26,39,40,255):
            for top,screen,column in ((1,1,1),(1,3,1),(2,3,3),(0,0,0),(255,255,255)):
                for key in keys:
                    data=make_state(mode,model,frequency,rows,
                                    **{'811c':top,'811d':screen,'811e':column})
                    run('move',0xe450,data,(key,),((1,key),))
    for _ in range(args.random_cases):
        mode,model,frequency=rng.choice(contexts)
        data=make_state(mode,model,frequency,rng.randrange(256),rng.randrange(256),
                        **{'811c':rng.randrange(256),'811d':rng.randrange(256),
                           '811e':rng.randrange(256),'80fe':rng.randrange(256),
                           '810e':rng.randrange(256),'8138':rng.randrange(256)})
        key=rng.choice(keys); run('move',0xe450,data,(key,),((1,key),))
    for model,frequency in ((1,0),(1,1),(2,0),(2,1)):
        columns=(1 if model==1 else 2)+frequency
        capacity=40 if model==1 else 80
        for rows in (0,1,2,capacity//columns-1,capacity//columns):
            for top,screen in ((1,1),(1,2),(1,3),(2,3)):
                for column in range(1,columns+1):
                    for pointer in (0x8700,0x82ee,0x82f0,0x8100,0x80de,0x100,0xfffc):
                        data=make_state(3,model,frequency,rows,**{'80fc':18,'811c':top,
                                        '811d':screen,'811e':column})
                        run('commit',0xe680,data,(pointer,),((0,pointer&255),(1,pointer>>8)))
    for _ in range(args.random_cases):
        model,frequency=rng.choice(((1,0),(1,1),(2,0),(2,1)))
        rows=rng.randrange((40 if model==1 else 80)//((1 if model==1 else 2)+frequency)+1)
        data=make_state(3,model,frequency,rows,rng.randrange(3),
                        **{'80fc':18,'811c':rng.randrange(8),'811d':rng.randrange(5),
                           '811e':rng.randrange(5)})
        pointer=rng.choice((0x8700,0x82ee,0x8100,0x80de,0x100,0xfffc))
        selected_row=(data[0x811c]+data[0x811d]-1)&255
        selector=(data[0x811e]-1)&255
        alternate=bytearray(data); alternate[0x80de]=(rows+1)&255
        if not (avoids_stack(cell_address(data,selector,selected_row)) and
                avoids_stack(cell_address(alternate,selector,selected_row))): continue
        run('commit',0xe680,data,(pointer,),((0,pointer&255),(1,pointer>>8)))
    for model,frequency in ((1,0),(1,1),(2,0),(2,1)):
        data=make_state(3,model,frequency)
        ram=(C.c_uint8*65536).from_buffer_copy(data);p=Platform(rom_buffer,len(rom),ram,0,0)
        columns=(1 if model==1 else 2)+frequency
        for row in (0,1,3,4,255):
            for column in (0,1,2,3,4,255):
                out=C.c_uint16(0xaaaa)
                status=lib.fx_stats_editor_address_checked(C.byref(p),column,row,C.byref(out))
                valid=1<=row<=3 and 1<=column<=columns
                expected=(0,0x82ee+10*((row-1)*columns+column-1)) if valid else (2,0)
                assert (status,out.value)==expected,(model,frequency,row,column,status,out.value,expected)
                assert bytes(ram)==data
                checks['checked_ui_address']=checks.get('checked_ui_address',0)+1
    p=Platform(rom_buffer,len(rom),(C.c_uint8*65536)(),0,0)
    for name,arguments in [('address_raw',(0,1,0x8700)),('write_raw',(0,1,0x8700)),
                            ('read_raw',(0,1,0x8700)),('insert',(1,)),('delete',(1,)),
                            ('clear',()),('move',(0xe0,)),('commit',(0x8700,))]:
        assert getattr(lib,'fx_stats_editor_'+name)(None,*arguments)==-1
        checks['null_host_guard']=checks.get('null_host_guard',0)+1
    before=bytes(p.ram[:65536])
    assert lib.fx_stats_editor_commit(C.byref(p),0x8700)==-1
    assert bytes(p.ram[:65536])==before
    checks['commit_context_guard']=1
    report={'status':'pass','rom_sha256':hashlib.sha256(rom).hexdigest(),
            'random_seed':'0x1d426','random_cases_per_family':args.random_cases,
            'checks':checks,'checks_total':sum(checks.values()),
            'scope':'Native columns, raw/checked cell addressing, descending-word read/write aliases, insert capacity/priority/reserved shift, delete/clear, cursor and STAT evaluated-input commit; exact return status, callback and full RAM outside CPU stack8d00..8ded.',
            'excluded':'CPU stack aliases, malformed prepared table sizes that overwrite native call stack, non-STAT branches of0E680, preceding evaluator/error routing and physical input scheduling'}
    write_report('analysis/c-verification/stats_editor.json',report,
                 sources+['csrc/platform/fx_platform.h','csrc/stats/fx_stats_editor.h','tools/c_verification.py'],
                 'tools/test_stats_editor_c.py')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
