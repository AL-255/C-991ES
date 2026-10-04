#!/usr/bin/env python3
"""Differential complex argument and rectangular/polar conversions.

The original firmware and CPU serve only as a test oracle. GPL-3.0-or-later.
"""
import argparse
import ctypes as C
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from nxu8.machine import Machine
from trace_natural_result import settings
from c_verification import write_report
from test_complex_c import Number, Complex, Rational, decimal_record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases',type=int,default=6000)
    parser.add_argument('--no-report',action='store_true')
    args = parser.parse_args()
    build = ROOT / 'analysis/build/complex/angles';build.mkdir(parents=True,exist_ok=True)
    library = build / 'complex-angles.so'
    sources = ['csrc/complex/fx_complex.c','csrc/complex/fx_complex_angle.c',
               'csrc/numeric/fx_numeric.c','csrc/trig/fx_trig.c',
               'csrc/trig/fx_trig_math.c','csrc/trig/fx_trig_inverse.c',
                 'csrc/numeric/fx_surd_components.c',
                 'csrc/numeric/fx_raw_decimal_divide.c',
                 'csrc/numeric/fx_raw_decimal_multiply_add.c',
                 'csrc/numeric/fx_raw_decimal_parts.c'
]
    subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror','-pedantic','-shared','-fPIC',
                    *(str(ROOT / source) for source in sources),'-o',str(library)],check=True)
    lib = C.CDLL(str(library));pointer=C.POINTER(Complex)
    lib.fx_complex_argument.argtypes=[pointer,pointer,C.c_int]
    lib.fx_complex_to_polar.argtypes=[pointer,pointer,C.c_int,C.c_int]
    lib.fx_complex_from_polar.argtypes=[pointer,pointer,C.c_int,C.c_int]
    lib.fx_complex_firmware_status.argtypes=[C.POINTER(C.c_uint8),C.c_int,pointer,pointer]
    lib.fx_decimal_parse.argtypes=[C.POINTER(Number),C.c_char_p]
    lib.fx_surd_pack.argtypes=[C.POINTER(Number),C.POINTER(Number)]
    lib.fx_rational_encode.argtypes=[C.POINTER(Number),C.POINTER(Rational)]
    machine=Machine((ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(),build / 'oracle')
    rng=random.Random(0x18366);cases=[];counts={};failures=[]

    def literal(value):
        number=Number();assert lib.fx_decimal_parse(C.byref(number),str(value).encode())==0
        return bytes(number)
    def check(group,actual,expected,detail):
        counts[group]=counts.get(group,0)+1
        if actual != expected:failures.append({'group':group,'detail':detail,'actual':actual,'expected':expected})
    def add_all(name,record):
        for unit in range(3):
            cases.append((name,record,unit,'argument',1))
            for exact in range(2):
                cases.append((name,record,unit,'to_polar',exact))
                cases.append((name,record,unit,'from_polar',exact))

    values=[-99,-4,-1,0,1,3,4,99,'.5','1e-99','1e99']
    for x in values:
        for y in values:add_all(f'named-{x}-{y}',literal(x)+literal(y))
    for index in range(args.random_cases):
        records=[]
        for component in range(2):
            if rng.randrange(10)==0: record=bytes(10)
            else:
                exponent=rng.randrange(-5,6) if index%3 else rng.randrange(-99,100)
                record=decimal_record(rng.randrange(10**14,10**15),exponent,
                                      rng.choice([-1,1]),0x40 if index%7==component else 0)
            records.append(record)
        cases.append((f'random-{index}',b''.join(records),rng.randrange(3),
                      rng.choice(['argument','to_polar','from_polar']),rng.randrange(2)))
    exact_records=[]
    for index in range(200):
        number=Number()
        if index%2:
            values=[rng.randrange(-99,100),rng.randrange(1,1000),rng.randrange(1,100),
                    rng.randrange(-99,100),rng.randrange(1,1000),rng.randrange(1,100)]
            components=(Number*6)()
            for position,value in enumerate(values):
                assert lib.fx_decimal_parse(C.byref(components[position]),str(value).encode())==0
            assert lib.fx_surd_pack(C.byref(number),components)==0
        else:
            fraction=Rational(rng.randrange(-99999,100000),rng.randrange(1,10000),0)
            assert lib.fx_rational_encode(C.byref(number),C.byref(fraction))==0
        exact_records.append(bytes(number))
    for index in range(400):
        cases.append((f'exact-{index}',rng.choice(exact_records)+rng.choice(exact_records),rng.randrange(3),
                      rng.choice(['argument','to_polar','from_polar']),rng.randrange(2)))
    metadata_values = [literal(0),literal(1),literal(-1),literal('1.5'),
                       bytes([0x40]) + bytes(9)]
    for numerator,denominator in [(1,3),(-1,3),(7,3)]:
        for marker in [0,0x40]:
            number=Number();fraction=Rational(numerator,denominator,marker)
            assert lib.fx_rational_encode(C.byref(number),C.byref(fraction))==0
            metadata_values.append(bytes(number))
    for values in [[1,2,1,0,1,1],[-1,2,1,0,1,1],
                   [1,2,1,-1,2,1],[1,2,1,-1,3,1],[1,3,1,-1,2,1]]:
        parts=(Number*6)();number=Number()
        for position,value in enumerate(values):
            assert lib.fx_decimal_parse(C.byref(parts[position]),str(value).encode())==0
        assert lib.fx_surd_pack(C.byref(number),parts)==0
        metadata_values.append(bytes(number))
    for real in metadata_values:
        for imaginary in metadata_values:
            add_all('metadata-admission',real+imaginary)
    # Exact trigonometric recognition is a dependency of polar conversion,
    # so exercise its special angles with several exact and decimal radii.
    radii = [literal(value) for value in [0,1,3,99,100,9999,'.5','1e-99','1e99']]
    for numerator,denominator in [(1,3),(1,7),(-1,3)]:
        number=Number();fraction=Rational(numerator,denominator,0)
        assert lib.fx_rational_encode(C.byref(number),C.byref(fraction))==0
        radii.append(bytes(number))
    special_angles = [[-30,30,45,60,90,180,270,360],[-50,50,100,200,400],
                      ['-.523598775598298','.523598775598298','.785398163397448',
                       '1.04719755119660','1.57079632679489','3.14159265358979']]
    # Angle-unit enum order is degree/radian/grad.
    for unit,angles in [(0,special_angles[0]),(1,special_angles[2]),(2,special_angles[1])]:
        for angle in angles:
            for radius in radii:
                for exact in range(2):
                    cases.append(('special-polar-angle',radius+literal(angle),unit,'from_polar',exact))
    for code in range(16):
        error=bytes([0xf0|code])+bytes(9)
        add_all(f'error-real-{code}',error+literal(4));add_all(f'error-imaginary-{code}',literal(3)+error)

    entries={'argument':0x18708,'to_polar':0x18366,'from_polar':0x182ec}
    for index,(name,record,unit,function,exact) in enumerate(cases):
        source=Complex.from_buffer_copy(record);output=Complex()
        if function=='argument':status=lib.fx_complex_argument(C.byref(output),C.byref(source),unit)
        else:status=getattr(lib,'fx_complex_'+function)(C.byref(output),C.byref(source),unit,exact)
        machine.reset();settings(machine);machine.ram[0x80f9]=0xc4;machine.ram[0x810c]=0
        machine.ram[0x8105]=4+unit;machine.ram[0x8106]=exact
        for position,byte in enumerate(record):machine.ram[0x8300+position]=byte
        machine.er(0,0x8300);machine.er(2,0x830a);machine.call(entries[function],limit=3000000)
        expected=bytes(machine.ram[0x8300:0x8314])
        numerical_status=C.c_uint8(0xab)
        numerical_host_status=lib.fx_complex_firmware_status(C.byref(numerical_status),
                              {'argument':6,'to_polar':7,'from_polar':8}[function],
                              C.byref(source),C.byref(output))
        check(function,[status,bytes(output).hex(),bytes(source).hex(),
                        numerical_host_status,numerical_status.value],
              [0,expected.hex(),record.hex(),0,machine.reg(0)],[name,record.hex(),unit,exact])
        if index<100:
            alias=Complex.from_buffer_copy(record)
            if function=='argument':alias_status=lib.fx_complex_argument(C.byref(alias),C.byref(alias),unit)
            else:alias_status=getattr(lib,'fx_complex_'+function)(C.byref(alias),C.byref(alias),unit,exact)
            check('output_alias',[alias_status,bytes(alias).hex()],[status,bytes(output).hex()],[name,unit,function,exact])

    report={'cases':sum(counts.values()),'groups':counts,'failures':len(failures),'mismatches':failures,
            'seed':'0x18366','random_cases':args.random_cases,
            'scope':'argument18708, rectangular/polar conversions18366/182EC in all three angle units and exact-output permissions',
            'input':'canonical real/imaginary decimal, rational, surd and error records, explicit angle unit and Math permission',
            'output':'all20 result bytes, original R0 numerical return, source immutability and output aliases',
            'limitation':'prepared contexts; no full expression/key UI, malformedBCD or global numeric scratchRAM equivalence'}
    if not args.no_report:
        path=ROOT / 'analysis/c-verification/complex_angles.json'
        if failures:report['status']='fail';path.write_text(json.dumps(report,indent=2)+'\n')
        else:write_report(path,report,[*sources,'csrc/complex/fx_complex.h','csrc/complex/fx_complex_angle.h',
                                      'csrc/numeric/fx_numeric.h','csrc/trig/fx_trig.h',
                                      'csrc/trig/fx_trig_math.h','csrc/trig/fx_trig_inverse.h',
                                      'tools/test_complex_c.py','tools/trace_natural_result.py','tools/c_verification.py',
                                         'csrc/numeric/fx_surd_components.h',
                                         'csrc/numeric/fx_numeric_components.h',
                                         'csrc/numeric/fx_raw_decimal_divide.h',
                                         'csrc/numeric/fx_raw_decimal_multiply_add.h',
                                         'csrc/numeric/fx_raw_decimal_parts.h'
],
                          'tools/test_complex_angles_c.py')
    print(f'{sum(counts.values())} complex coordinate checks, {len(failures)} mismatches')
    for failure in failures[:20]:print(failure)
    if failures:raise SystemExit(1)


if __name__=='__main__':main()
