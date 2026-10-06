# Fraction/π recognition and special trigonometric values

The [HP QPI reference](https://www.hpmuseum.org/software/qpi/42sqpi.htm) describes continued-fraction selection among rational, square-root,π, logarithmic and exponential forms. Casio has narrower observed mechanisms; shared authorship or copied implementation is not established.

## Fraction before π

For eligible ordinary results, C060 → AB8E → AEF8 → 10C1E tries an ordinary fraction. Success wins:0.5 becomes 1/2 withoutπ recognition. The same helper also converts numeric operands, so its call count alone does not show display recognition.

After failure, AF18..AF48 checks model permission, selection state≥13, exponent and Math permission. ROM1FFE1 read through 1186C is 0 and permits this image's branch. Math setting 8106=0 skips it. Preliminary exponent bounds include−7 and 9; recognizer 10C44..10C4A rejects exponent≥6, imposing tested|x|<10^6. Radians control inverse-trig numeric units, not recognition of a supplied decimal orπ expression.

## Fixed-scale π algorithm

10C2C operates on a formatter-owned copy:

~~~text
u = abs(result)
pi = native_pi_constructor()
k = native_decimal_multiply(native_decimal_divide(u,pi),25200)
k = native_low_mantissa_cleanup(k)
reject unless k is integral
g = gcd(k,25200)
n = k/g; d = 25200/g
split n/d into integer part and remainder
restore sign; return 255
~~~

| Instruction | Action |
| --- | --- |
| 10C38 | Copy input |
| 10C4E | π constructor 1D16E |
| 10C56 | Division 1BFE0 |
| 10C60 | Multiplication 1BFCC using ROM2640 |
| 10C64/10C68 | Cleanup 10B60 and reject fractional remainder |
| 10C7E | GCD1C982 |
| 10C88/10C92 | Reduce numerator/denominator |
| 10CA2 | Split coefficient 1C3FA |
| 10CA6..10CBE | Success 255 and sign |
| AD12..AD16 | Appendπ token 82 |

ROM2640=02520000000000000401 encodes 25200. Nativeπ is 03141592653589800001, or 3.14159265358980. Because 25200=2^4*3^2*5^2*7, a recognized reduced denominator divides 25200. Range, precision and context remain necessary. The native π/d sweep, d1..128, matched divisibility in its prepared COMP Math context:π/16 andπ/25200 work;π/11 andπ/32 fail.

For asin(0.5) in radians, evaluator 171F4 dispatch 2976 → 1C568 returns ordinary record 05235987755982999900, or 0.523598775598299:

~~~text
x/pi = 0.166666666666666
scaled k = 4199.99999999998
cleanup = 4200
gcd(4200,25200) = 4200
coefficient = 1/6
tokens = AE BB B8 31 B9 B8 36 B9 BC 82
~~~

Kind 13 yields a stacked 1/6 followed byπ, box(14,16,8), x 82/baseline 24. B070 repeats formatting for display. The stored ordinary result stays unchanged. The decimal literal 0.523598775598299 reaches the same representation without a symbolicπ operand.

10B60 changes the last packed mantissa byte to 00/99 depending on whether it is below 50, invokes near-integer cleanup 1CEF0 and fractional-digit test 1CABE. Low-digit helper 1A6DA makes tolerance exponent-dependent. Near 4200,4200.00000000049 and 4199.99999999950 pass; adjacent 4200.00000000050 and 4199.99999999949 fail. Literal 0.5235987756 scales to 4200.00000001361 and fails despite matching display digits.

| Controls | Finding |
| --- | --- |
| asin(0.5) rad,5π/6,−π/6,3.14159265358979/6 | π forms |
| 4 atan(1) rad | π |
| 0.5, asin(0.5) deg | 1/2 or 30; noπ recognizer |
| π/6 with decimal selection/Math disabled | Decimal; branch skipped |
| 300000π /400000π | First recognized; second range-rejected |
| Decimal approximations to√2 ande | Decimal in this formatting path |

The original report cites Casio's [Natural Display range documentation](https://support.casio.com/global/en/calc/manual/fx-570ESPLUS_991ESPLUS_en/technical_informatoin/calculation_ranges.html) forπ limits and possible missed/spurious forms from numeric error. The traces cover the pinned image/contexts.

## Special trigonometric results

Hardcoded **result magnitudes**, not input angles, are matched after numeric evaluation. Paired ten-byte records are exact arithmetic objects, not strings.

| Decimal address | Magnitude | Exact address | Exact value |
| --- | --- | --- | --- |
| 29F6 | 0.258819045102521 | 2A28 | (√6−√2)/4 |
| 2A00 | 0.5 | 2A32 | 1/2 |
| 2A0A | 0.707106781186548 | 2A3C | √2/2 |
| 2A14 | 0.866025403784439 | 2A46 | √3/2 |
| 2A1E | 0.965925826289068 | 2A50 | (√6+√2)/4 |
| 2A5A | 0.267949192431123 | 2A82 | 2−√3 |
| 2A64 | 0.577350269189626 | 2A8C | √3/3 |
| 2A6E | 1.73205080756888 | 2A96 | √3 |
| 2A78 | 3.73205080756888 | 2AA0 | 2+√3 |

Sine 16268 → 1C59E and cosine 16272 → 1C58C share five candidates; tangent 16308 → 1C57A uses four. Loop16298 copies each decimal candidate and subtracts magnitude at 162A2. Exponent/leading-digit tests 162A6..162CC use absolute difference below 5 e−13, relaxed to 5 e−12 for tangent's larger two entries, with native rounded arithmetic.

On match 162DE → 18212 checks exact eligibility. 162E6 advances by 50 bytes for sine/cosine or 40 for tangent;162F2 copies the exact record;162FE restores negative sign. Without exact permission it copies the matched decimal constant; without a match the computed result survives.

sin(45°) replaces 07071067811865479900 with 80000001000201020100 at ROM2A3C, already representing√2/2 before formatting. sin(30°) replaces 05000000000000009900 with rational 21A20000000000000301.

Controls:sin(390°) matches 1/2; cos(120°) restores−1/2; a radian approximation toπ/4 matches√2/2; sin(45.00000000001°) matches butsin(45.000000001°) does not. Literal 0.707106781186548 stays decimal because the wrapper is not called. sin(18°) stays decimal although mathematically(√5−1)/4; that exact value is absent from the finite table.

## Cold EQN and SOLVE witnesses

A later original/C comparison used physical matrix packets at genuine controller waits, zero RAM plus F040=FF, boot 6F82 and real timer acknowledgements. No result or external C body completion was injected.

| Recipe | Original display | Session 10C1E/10C2C calls |
| --- | --- | --- |
| COMP π/6 | (1/6)π | 1/1 |
| EQN6 x+0 y=π;0x+y=0 | x=(1/6)π | 7/1 |
| SOLVE6X−π=0, initialX=0 | X=0.5235987756; L−R=0 | 0/0 |

EQN MODE5/choice 1 opens the grid; MAIN D930 → E862; E880 → 14F0C solves; successful 15658 → 5192 → C046 clears format flags and appends replay roots; E8E6 sets screen 1 and 80FD=2. EXE displays x/y. Error fallbackE89A → 112F6 was not taken.

COMP/EQN displayB24E → C060 → C1E0 → AB8E attempts ordinary fraction. Six EQN10C1E calls return at 1114C during arithmetic, one atAEFC during display. AF24 has selection 13, AF3C Math permission 1; AF48 → 10C2C returns 255 atAF4C. AD12 appends 82; C1D2 returnskind 13 at destinations 8398/8546. Records 05235987755983009900 (COMP) and 05235987755982979900 (EQN) render the sameπ form despite low-digit differences.

SOLVE1F450 sets 80FF=19; B136/B13E call 3658 to force selection 10. C060/C1D2 returns decimal kind 10 at 8D9A with tokens 302E35323335393837373536. Neither recognizer executes in the session, matching the [documented decimal SOLVE policy](https://support.casio.com/global/en/calc/manual/fx-115ESPLUS_991ESPLUSC_en/function_calculations/using_SOLVE.html).

Six historical cold sessions atO2/O3 checked 406 paired RAM/callback/LCD checkpoints and 32 actual 5550 poll pairs. Scalar scratch 8000..8077 and written native frames within 8B28..8DED were excluded; operands 8078..80DB, component pool 8640..877F, LCD and other persistent RAM were strict. No unexpected persistent differences occurred. This establishes only three recipes/default SOLVE start, not arbitrary equations, public-browser behavior or full C parity.

Maintained code: [formatting](../../../csrc/format/fx_format.c), [trig math](../../../csrc/trig/fx_trig_math.c). Reproduction and evidence: [PROVENANCE.md](PROVENANCE.md).
