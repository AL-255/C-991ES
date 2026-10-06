# Casio versus the supplied ePS firmwares

## Inputs and conventions

There are three supplied ePS images, not one “eps-emu firmware.” Original release dates and extraction provenance for those images were not established. Casio was pinned to its Ver.4.00 emulator extraction.

| Image | Bytes | SHA-256 |
| --- | ---: | --- |
| Casio PLUS C Ver.4 | 131,072 | 28b5c3907a67426a1601dbf82ebf62b850333e889fcc958d698786d3e5f5fb7d |
| HP 300s | 131,072 | 2fef627234972a8c6b6084667935b7419c79449963472d4ef4d0b00dcc7cf5d1 |
| HP 300s+ | 131,072 | 3d7880a9a5c51aabe884b48c0cfac9ae1882af78c0f673b52307b1f6f3a99d15 |
| Vinacal 570ES | 196,608 | 2452191971e5ede8bd0df2eb2cca59964b449e94459db3d6131c7d3a4be32c04 |

Casio PCs are byte addresses. ePS PCs/call targets are **word addresses**, so file offset=2×PC. ePS table pointers are byte addresses: stored word 12 34 fetches as instruction 1234, but table bytes are 34 then 12. Searches examined stored and adjacent-byte-swapped table views. Loader selection of ePS6800/ePS6900 by image size is emulator configuration, not independent hardware identification.

Local-only reference paths: eps-emu/roms/{hp300s_rom.bin, hp300sp_rom.bin, vinacal570es_rom.bin}, eps-emu/core/{machine.c, cpu.c}. They are not repository links or newly published assets.

## Numerical fingerprints

| Tested representation | Storage | Retained mantissa |
| --- | --- | --- |
| Casio external decimal | 10 bytes; leading digit/header,7BCD pairs, exponent/sign-scale | 15 significant digits |
| HP arithmetic slot | 10 bytes; sign/exponent bits, BCD exponent,8BCD pairs | 16 digits |
| Vinacal workspace | 12 bytes; signed exponent, sign,10BCD pairs | 20 digits |

These are tested record formats, not universal working/display precision. Casio internal kernels have guard digits. Direct 1/3 gives Casio 03333333333333339900, or 0.333333333333333; HP 300s 40013333333333333333, or 0.3333333333333333.

| Prepared function | Casio byte entry | HP 300s word entry | HP 300s+ word entry | Vinacal word entry |
| --- | --- | --- | --- | --- |
| sin radians | 1C59E | 43FE | 463B | Not tested |
| ln | 1C242 | 46E6 | 47D0 | Workspace core 129D1 |
| log 10 | 1C256 | 475B | 4845 | 129B6 |
| division | 1BFE0 | 42D0 | Not tested | Not tested |

HP initialization 4000 establishes fixed operands 10C/118. Vinacal log 10 source is indirect from 1B80; output pointer 40/41 identifies 1B8C; ln intermediate remains at 3E. Casio used 8300 and explicit radians for sine. Twelve selected original-Casio unary cases matched the historical handwritten C; physical keys/peripherals were outside these prepared tests.

Representative original stored results:

| Function | Casio | HP 300s / HP 300s+ | Vinacal |
| --- | --- | --- | --- |
| sin(2 rad) | 0.909297426825684 | 0.9092974268256827 | Not tested |
| sin(0.5 rad) | 0.479425538604200 | 0.4794255386042030 | Not tested |
| ln(2) | 0.693147180559946 | 0.6931471805599460 | 0.69314718055994531000 (workspace) |
| log 10(2) | 0.301029995663981 | 0.3010299956639814 | 0.30102999566398119521 |
| log 10(10^-20) | -20.0000000000000 | -19.99999999999998 / -20.00000000000000 | -20.000000000000000000 |

Similar LCD rounding can hide these differences. Matching one result is not itself ancestry proof.

Casio's sine path enters 1A2D4 and reconstructs decimal rotations with ten scaled angular steps at 1A2E..1A92. Its log kernel uses nineteen scaled log 10(1+10^-k) factors at 1966..1A24. ln derives from that log 10 result by division bylog 10(e). ln(2) reconstruction edge 1AEE6 → 1AE2E is taken 16 times for 17 passes; factor-loader 1B11A is called 18 times including the conversion constant.

HP uses coefficient polynomial stages. HP 300s 43EB calls saved-operand copy 404D, multiply 425E, coefficient-read 43CF, then tail-jumps to add4235. sin(2) performs four stages then three, ten multiplications and one division, reading nine 10-byte records 13046..130A0. HP+ reads the identical corresponding 120BE..12118 interval. ln(2) uses stages in groups 3+2 and reads 131FE..13262 (HP+)12276..122DA; log 10 callsln and multiplies bylog 10(e).

Vinacal log 10 wrapper 129B6 callsln 129D1, reads log 10(e) at 7E30 and multiplies. Its general ln coefficients 28F40..28F7C belong to rounded 2,2/3,…,2/19. Near-one input uses 28FB8..28FF4:1,−1/2,1/3,−1/4,1/5. Polynomial helper 13878 receives order inACC, table inTABPTR, indirect source and caller destination. Order 4 takes three 13899 → 13885 back edges; after polynomial stages it multiplies by extra workspace 62, so its contract isfactor×P(x). With argument 0.25, changing that factor 2 → 3 changes 1.7854166666666666666 → 2.6781249999999999999. This is distinct from Casio's factor-coordinate reconstruction.

## Contracts and structure

Casio public add1BFA4/subtract 1BFB8/multiply 1BFCC/divide 1BFE0 use operand pointersER0/ER2 and write through originalER0 after conversion/shared scratch. HP fixed-slot arithmetic overwrites 10C; subtract 4234 flips the second operand sign and falls into add. Vinacal has separate input/output pointers and shared workspaces.

Tested ln-domain errors make Casio write F3000000000000000000 and returnR0=3. HP retains the input slot and reportsr 47 bits 08 (HP 300s) or 04 (HP+). Vinacal log 10 errors retain a preloaded valid caller marker 7 and setr 42=80. Status registers are not universal integer return codes.

Schoolbook decimal operations resemble one another, but Casio multiplication 1B8EC groups digit contributions in threes using precomputed 2×/3× mantissas; HP425E uses odd/even nibble decomposition. Precision alone does not explain that algorithm choice.

A strong positive comparison exists between the HP images: corresponding polynomial helpers 43EB/4614 share the four-operation pattern, and 44 mapped ln(2) root-frame calls through final-normalizer entry match in order. This manually selected semantic region and mapping is not a whole-program similarity score.

## Binary/resources

No qualifying 16- or 32-byte exact run connected Casio to any ePS image in either stored/table view. Seeds required≥6 distinct bytes; greedy nonoverlapping-source selection is not exhaustive maximal matching or a similarity percentage. Reformatted/generated/encoded tables can escape the search.

The HP images have 77 qualifying 32-byte runs covering 10,684 source bytes, including an 800-byte numerical block at stored offsets 13046/120BE. Commonπ, e, ln(10), log 10(e),1/√2 digits are weak evidence. Distinctive Casio factor-table and angular-step families were absent as families.

Decoded font searches found candidate Casio ASCII glyph matches: large/small unique character IDs 11/33 (HP 300s),16/43 (HP+),0/12 (Vinacal), excluding very sparse glyphs. Some HP matches occur at regular font-like intervals. This supports possible visual/resource borrowing but does not prove complete-font identity, actual character mapping, copied authorship or shared rendering code.

## Parser resemblance and differences

Native HP+ key traces reached controller 2000 → evaluator 900 → numeric stage 5CDE → arithmetic 4DA0 → add4191 for 2.5+3. Inputs 2+3,2.5+3,1+2*3 and 1/0 were exercised; integer addition can bypass the decimal-add entry. Precedence applies multiply 43 before add41 and returns record 7.

Both Casio and HP+ use ten 10-byte value slots plus operator storage, but contracts differ:

| Role | Casio byte PC | HP+ word PC |
| --- | --- | --- |
| Value push/pop | 1669A/166C8; ER2 pointer, R11 depth | 1098/1112; fixed slot, next-free pointer 1FE |
| Operator load | 166EC non-destructive peek, R4 | 1079 pop/load currentr 56 |
| Operator push | 166FC, R0 token, R10 depth | 1084/108C, currentr 56, pointer 1FF |

Casio values 8078+10×depth/operators 8060+depth; HP bank 3 values 180, operators 1E5 and live currentr 56. Both admit ten valid values; Casio rejects malformed depth 11 via≥10, while HP equality-only full-pointer check admits malformedEE → F8. Casio overflow/empty status 7 differs from HP overflow 2/empty 1. Casio stores zero operator; HP skips it. Empty Casio peek can read poisoned prior byte; HP clearsr 56. HP operator entry 1084 allows 25,108C24; Casio universally testsdepth≥24. Casio complexC4 two-slot behavior has no established equivalent HP probe.

Casio has reducibility 1660E, priority 16714, three-action decision 16772 and incoming loop167A6. HP embeds token/range branches and apply 1159/pop 1079 in evaluator 900. Casio decrements operator depth before 16336; HP finalE23..E28 applies current then reloads previous. Error handling differs between HP reduction branches, so one failure does not specify all stack cleanup.

The separate HP 300s boot/key attempt did not validate an evaluator path and supplies no negative ancestry evidence. Vinacal parser was unexamined.

## Assessment and method limits

The combined record formats, active coefficient families, function contracts and loop structures weigh strongly against a straightforward port of the tested Casio numerical engine. HP+ has a similar but differently implemented inspected parser. Whole-program historical origin remains an inference; partial reuse, an older common ancestor or a hybrid with replacement maths remain possible.

Structural follow-up recorded 84 prepared numeric/helper calls and 40 stack calls, actual call edges, taken backward branches and ePS RPT separately. A backward edge may be a tail transfer, not a loop. Casio helper 1B150 has a nonstandard saved-LR/RT/POP-PC continuation; traces retained that rather than inventing normal frames. Cross-CPU instruction counts/register numbers were not ancestry scores.

The best-supported description is: “The supplied ePS calculators reproduce similar behavior with demonstrably different numerical implementations; no direct Casio firmware derivation was established, while possible resource borrowing remains open.” This does not identify authors, licences or a copying event. Deeper token/error/cursor/exact-record quirks, full font mapping, state-machine bugs and older image provenance could change the conclusion.

Maintained Casio code: [trig kernel](../../../csrc/trig/fx_trig_math.c), [log kernel](../../../csrc/numeric/fx_transcend.c), [raw decimal product](../../../csrc/numeric/fx_raw_decimal_multiply_add.c). Historical scripts and evidence are local-only; [PROVENANCE.md](PROVENANCE.md) lists them.
