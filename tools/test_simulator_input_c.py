#!/usr/bin/env python3
"""Focused ASCII-to-calculator-token contracts at strict O2 and O3.

Expected token fixtures are written from the existing evaluator's public
token grammar. This is a lexical/syntax test, not a numeric or original-ROM
differential test; the separate simulator suite owns that comparison.
"""
import argparse
import ctypes as C
import hashlib
import json
import os
import subprocess

from c_verification import ROOT, write_report

SOURCE = 'csrc/app/fx_simulator_input.c'
HEADER = 'csrc/app/fx_simulator_input.h'
REPORT = 'analysis/c-verification/simulator_input.json'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--no-report', action='store_true')
    args = ap.parse_args()
    build = ROOT / 'analysis/build/simulator-input'
    build.mkdir(parents=True, exist_ok=True)
    temporary = build / 'compiler-tmp'
    temporary.mkdir(exist_ok=True)
    environment = dict(os.environ, TMPDIR=str(temporary))
    inputs = [SOURCE, HEADER, 'tools/test_simulator_input_c.py',
              'tools/c_verification.py', 'tools/c_build_inputs.py']
    pins = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in inputs}
    fixtures = [
        ('0', 0, '30'), ('1.25', 0, '312e3235'), ('.', 0, '2e'),
        ('1e-3', 0, '31746033'), ('2E+99', 0, '32742b3939'),
        ('2e', 0, '3281'), ('2E', 0, '3245'),
        ('1+2*3', 0, '312b324e33'), ('-2^2', 0, '60325e3229'),
        ('2^3+4', 0, '325e33292b34'), ('2^3*4', 0, '325e33294e34'),
        ('2^3^4', 0, '325e335e342929'),
        ('2^(3+4)', 0, '325e28332b342929'),
        ('2^-3^2', 0, '325e60335e322929'),
        ('2pi', 0, '3282'), ('1/2pi', 0, '314f3282'),
        ('2(3+4)', 0, '3228332b3429'), ('(2)(3)', 0, '283229283329'),
        ('5!+20%', 0, '35572b323025'),
        ('i^2', 1, '805e3229'), ('e+pi+Ans', 0, '812b822b8b'),
        ('PreAns+1', 0, 'c82b31'), ('pReAnS', 0, 'c8'),
        ('A+B+C+D+E+F+X+Y+M', 0, '412b422b432b442b452b462b582b592b54'),
        ('3->A', 0, '3347'), ('3 -> F', 0, '3384'), ('2i->X', 1, '32804c'),
        ('2->Y', 0, '324d'), ('2->M', 0, '324b'),
        ('log(2,8)', 0, '68322c3829'), ('log(100)', 0, '6831303029'),
        ('sin(30)', 0, 'a0333029'), ('cos(60)', 0, 'a1363029'),
        ('tan(45)', 0, 'a2343529'), ('sinh(1)', 0, '703129'),
        ('Pol(3,4)', 0, '6c332c3429'), ('Rec(2,30)', 0, '6d322c333029'),
        ('frac(1,2)', 0, '28283129ae28322929'),
        ('frac(1,2)^3', 0, '28283129ae283229295e3329'),
        ('nthroot(3,-8)', 0, '282833299f286038292929'),
        ('nPr(5,2)', 0, '28283529be28322929'), ('5 nCr 2', 0, '35bf32'),
        ('qrem(10,3)', 0, '28283130295f28332929'),
        ('square(3+4)', 0, '28332b342975'),
        ('cube(2)', 0, '28322976'), ('inv(2)', 0, '28322977'),
        ('sum(X,1,3)', 0, '69582c312c3329'), ('prod(X,1,3)', 0, '5d582c312c3329'),
        ('integral(X,0,1)', 0, '6a582c302c3129'),
        ('diff(X^2,1,0.001)', 0, '6b585e32292c312c302e30303129'),
        ('RanInt(1,6)', 0, 'c2312c3629'), ('Ran#', 0, '8c'), ('Rand()', 0, '8c'),
        ('1010 and Not(1)', 2, '313031306e613129'),
        ('7 or 3 xor 1 xnor 2', 3, '376f337e317f32'),
        ('FF+A', 5, 'bdbd2bb8'), ('aBcDeF', 5, 'b8b9babbbcbd'),
        ('F+var(A)', 5, 'bd2b41'), ('abs(3)', 5, '633329'),
        (' \tSQRT(2)\r\n+ Pi\v', 0, '9832292b82'),
        ('(sqrt(998)-sqrt(997))/99', 0, '2898393938292d9839393729294f3939'),
    ]
    prefixes = {'sqrt':0x98,'cbrt':0xa8,'asin':0xb0,'acos':0xb1,'atan':0xb2,
                'cosh':0x71,'tanh':0x72,'asinh':0x90,'acosh':0x91,'atanh':0x92,
                'ln':0xa3,'exp':0x73,'exp10':0x93,'log10':0x68,'abs':0x63,
                'conj':0x88,'arg':0xc3,'round':0xb3,'Rnd':0xb3,'Not':0x61,
                'Neg':0x62,'det':0xc0,'trn':0xc1,'ref':0x5a,'rref':0x5b}
    fixtures += [(name+'(1)',0,bytes([token,ord('1'),ord(')')]).hex())
                 for name,token in prefixes.items()]
    invalid = [('',0,0), ('()',0,1), ('1+',0,2), ('2**3',0,2),
               ('sqrt(2',0,6), ('sqrt()',0,5), ('sinx(2)',0,0),
               ('sqrt(2,3)',0,6), ('Pol(3)',0,5), ('log(1,2,3)',0,7),
               ('1e100',0,4), ('1.2.3',0,3), ('1 2',0,2), ('1)',0,1),
               ('3->Ans',0,4), ('3->a',0,3), ('var 3',0,4), ('var(Q)',0,4),
               ('2 and 1',0,2), ('1.2',2,1), ('@',0,0), ('\xc3\xa9',0,0),
               ('PreAns',1,0), ('PreAns',5,0),
               ('1',6,0), ('('*33+'1'+')'*33,0,32), ('1'*4097,0,4096)]
    checks = 0
    artifacts = {}
    builds = []
    for optimization in ('O2','O3'):
        shared=build/('input-'+optimization+'.so')
        subprocess.run(['gcc','-std=c99','-'+optimization,'-Wall','-Wextra',
                        '-Werror','-pedantic','-shared','-fPIC',str(ROOT/SOURCE),
                        '-o',str(shared)],check=True,env=environment)
        artifacts[optimization]=hashlib.sha256(shared.read_bytes()).hexdigest()
        lib=C.CDLL(str(shared))
        encode=lib.fxsim_encode_expression_mode
        encode.argtypes=[C.c_char_p,C.c_uint,C.POINTER(C.c_uint8),C.c_size_t,
                         C.POINTER(C.c_size_t),C.POINTER(C.c_size_t)]
        encode.restype=C.c_int
        ordinary=lib.fxsim_encode_expression
        ordinary.argtypes=[C.c_char_p,C.POINTER(C.c_uint8),C.c_size_t,
                           C.POINTER(C.c_size_t),C.POINTER(C.c_size_t)]
        ordinary.restype=C.c_int
        start=checks
        for text,mode,expected in fixtures:
            wanted=bytes.fromhex(expected)+b'\0'
            buffer=(C.c_uint8*8195)(*([0xa5]*8195))
            length=C.c_size_t(999);error=C.c_size_t(999)
            assert encode(text.encode('ascii'),mode,buffer,8193,C.byref(length),C.byref(error))==0,(text,mode)
            assert length.value==len(wanted) and error.value==0,(text,length.value,error.value)
            assert bytes(buffer[:length.value])==wanted,(text,bytes(buffer[:length.value]).hex(),wanted.hex())
            assert bytes(buffer[length.value:])==b'\xa5'*(8195-length.value),text
            checks+=4
            for capacity in range(len(wanted)):
                buffer=(C.c_uint8*8195)(*([0xa5]*8195))
                assert encode(text.encode(),mode,buffer,capacity,C.byref(length),C.byref(error))==-2,text
                assert length.value==0 and error.value==len(text),text
                assert bytes(buffer)==b'\xa5'*8195,text
                checks+=3
        for text,mode,position in invalid:
            buffer=(C.c_uint8*8195)(*([0xa5]*8195))
            length=C.c_size_t(999);error=C.c_size_t(999)
            assert encode(text.encode('latin1'),mode,buffer,8193,C.byref(length),C.byref(error))==-1,text
            assert length.value==0 and error.value==position,(text,error.value,position)
            assert bytes(buffer)==b'\xa5'*8195,text
            checks+=3
        # Boundary nesting and maximum source length need no numeric evaluator.
        for text in ['('*32+'1'+')'*32,'1'*4096,'+'*127+'1']:
            buffer=(C.c_uint8*8193)();length=C.c_size_t();error=C.c_size_t()
            assert ordinary(text.encode(),buffer,8193,C.byref(length),C.byref(error))==0
            assert buffer[length.value-1]==0
            checks+=2
        buffer=(C.c_uint8*32)(*([0xa5]*32));length=C.c_size_t(999);error=C.c_size_t(999)
        assert ordinary(None,buffer,32,C.byref(length),C.byref(error))==-1 and length.value==0
        assert ordinary(b'1',None,32,C.byref(length),C.byref(error))==-1
        assert ordinary(b'1',buffer,32,None,C.byref(error))==-1
        assert bytes(buffer)==b'\xa5'*32
        assert ordinary(b'1',buffer,32,C.byref(length),None)==0 and length.value==2
        checks+=5
        # Successful output may alias its source: all reads finish before copy.
        alias=C.create_string_buffer(b'2^3+4',32)
        assert encode(C.cast(alias,C.c_char_p),0,C.cast(alias,C.POINTER(C.c_uint8)),
                      32,C.byref(length),C.byref(error))==0
        assert alias.raw[:length.value]==bytes.fromhex('325e33292b3400')
        checks+=2
        builds.append({'optimization':optimization,'checks':checks-start,
                       'valid_token_fixtures':len(fixtures),'invalid_fixtures':len(invalid)})
    assert pins=={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in inputs},'source drift'
    report={'checks':checks,'cases':checks,'mismatches':[],'builds':builds,
            'native_calls':0,'scope':'ASCII syntax, exact native token fixtures, transaction and capacity contracts; numerical admission is separate',
            'artifacts_sha256':artifacts}
    if not args.no_report:
        write_report(REPORT,report,[SOURCE,HEADER],__file__.replace(str(ROOT)+'/', ''))
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
