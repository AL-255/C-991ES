# Complete exact pipeline: (√998−√997)/99

The final two-radical value is preserved during arithmetic. The formatter rebuilds a common fraction without inferring the radicals from a decimal approximation. The ROM has bounded exact records and fallback branches; this is not arbitrary symbolic algebra.

## Recorded execution and scope

The independent SimU8 harness supplied expression tokens, initial context, pointer arguments and four routine boundaries. The ROM performed arithmetic, emitted tokens and drew pixels. Peripherals were passive; this was not a cold-key session.

Initial context: 80F9=C1, 8106=1 (Math), 8121=1 (RAM framebuffer), 812C=8200. SP=8DEE and LR used a return sentinel.

| Phase | Entry and supplied state | Instructions |
| --- | --- | ---: |
| Evaluate | 171F4; ER0=8190 input-pointer cell; ER2=8300 destination | 112,645 |
| Select format | C034; result key 80F5=F0 | 11 |
| Display | B070; ER0=8300 | 77,856 |
| Transfer | 3CFC; existing framebuffer | 332 |

Total 190,844 instructions at 5,837 distinct PCs. Recorded reads matched ROM plus replayed RAM writes, final RAM matched, and every PC occurred in the static listing. This validates the recording, not all inputs.

## Parse and dispatch

Input at 8200:

~~~text
28 98 39 39 38 29 2D 98 39 39 37 29 29 4F 39 39 00
~~~

The root token 98 includes a function opening. Evaluator root syntax 98 '998'29 differs from generated layout 98 B8 '998' B9; these streams are not interchangeable parser fixtures.

171F4 creates a60-byte operand workspace at 8DA0 and holds its cursor inER14. 159D0 decodes packed 12-bit token table 245A; category dispatch starts at 25DA. Pending operations enter 16336 and load near pointers from 291E at 16558, then BL ER4 at 1655C retains code segment 1.

| Operation | Table address / index | Target |
| --- | --- | --- |
| Both square roots | 296A /38 | 1C870 |
| Subtraction | 2994 /59 | 15F40 |
| Parenthesis completion | 2942 /18 | 15C18 |
| Division | 2998 /61 | 15F58 |

Parsed ordinary records are 998=09980000000000000201,997=09970000000000000201,99=09900000000000000101.

## Keep exact components

Root path 1C870 → 1C780 checks Math eligibility 18212 and ordinary range 1C852. 1C862 → 11110 converts an eligible ordinary number to rational form;17820 expands components;17A46 normalizes square factors;17616 packs:

~~~text
√998 = 80000001099801010100
√997 = 80000001099701010100
~~~

High nibble 8 tags surds. The radicands remain explicit rather than decimal root approximations.

Subtraction 15F40 → 1C690 checks operand tags at 1C6E0..1C6EE and selects 180CC. Workspace loading/expansion 17B68,17BC4,178BA and normalization including 17F46 culminate in 17616:

~~~text
89970101099801010106 = -√997 + √998
~~~

Division 15F58 → 1C6B8 → 18118 loads/classifies operands. Tests 1812A/18156 select scalar-divisor 17EE2 for 99. Arithmetic and packing give:

~~~text
89970199099801990106 = (-√997)/99 + (√998)/99
~~~

The evaluator writes real result 8300, zero imaginary 830A, returns 0 and advances beyond the terminator. Expander 178BA produces six ordinary values[-1,997,99,1,998,99].

| Offset | Final bytes | Role in this record |
| --- | --- | --- |
| 0..1 | 89 97 | Surd nibble 8 and packed radicand 997 |
| 2..3 | 01 99 | First coefficient magnitude/denominator |
| 4..5 | 09 98 | Packed radicand 998 |
| 6..7 | 01 99 | Second coefficient magnitude/denominator |
| 8 | 01 | Second coefficient positive-unit sign/exponent |
| 9 | 06 | First coefficient negative-unit sign/exponent |

This describes this instance, not every compact coefficient encoding.

Recognition does occur during operand conversion:11148 → 10C1E handles 998,997,99 at evaluator steps 733,26625,60063. The precise conclusion is that the final radicals survive arithmetic, and the display phase enters neither 10C1E norπ recognizer 10C2C.

## Rebuild and render

C034 reads 80F5=F0 and calls 3658 to write 8100=13; kind 13 was not directly injected. The ordinary result handler uses evaluator call 1F366 and selection call 1F3FA.

B070 copies the result and calls C060 → AB8E. Surd gatesAD68..AD86 invoke 18176, producing[1,998,-1,997,99] with meaning(a√b+c√d)/e. Serialization omits unit coefficients, emits subtraction and a common denominator:

~~~text
AE BB B8 98 B8 39 39 38 B9 2D 98 B8 39 39 37 B9 B9 B8 39 39 B9 BC 00
~~~

AE BB opens the fraction; B8/B9 delimit numerator√998−√997 and denominator 99. Display order differs from stored term order. This is newly generated layout, not copied source text.

8C56 calls 9CD6 to measure then draw. Fraction 937C uses small children; root 8EA6 adds ornaments. Each radical is(W, H, D)=(25,9,3); minus advance 6 gives numerator(56,9,3); denominator(12,7,3); entire fraction(58,18,8). Right alignment givesx=38, baseline 24; numeratorx 39/baseline 20; denominatorx 61/baseline 29. Radicands startx 44/75; bar isy 24, x 39..95.

3BBC unpacks glyphs,3A8A draws,3C8E composites RAM87D0;3CFC copies 32 twelve-byte rows into stride 16 VRAMF800. Framebuffer SHA256:a0b20e6fc4d6759555fac8a601af01ce22bed7fc34f36bb99953bda1d02c75c9.

## Controls

Destroying input withA5 after evaluation gives identical pixels; selection/display/transfer read no original input bytes. Decimal input 0.000159911011805457 remains ordinary decimal/kind 10 and does not recover radicals. The exact value is generally degree 4 over rationals:

~~~text
96059601*x^4 - 39105990*x^2 + 1 = 0
~~~

Explicit radicands avoid inferring that relation. Maintained code: [surd components](../../../csrc/numeric/fx_surd_components.c), [layout](../../../csrc/render/fx_layout.c). Reproduction and local evidence: [PROVENANCE.md](PROVENANCE.md).
