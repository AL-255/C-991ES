# Expression tokens to pixels

C060 → AB8E chooses observed decimal kind 10, fraction 11, mixed 12, surd/π13. Settings include Math 8106, mixed choice 8107, display mode/precision 8102/8103 and gate C35E. B070 temporarily sets/restores expression pointer 812C. Examined record families include decimal, rational 20, surd 80, invalidF0; this is not a complete type specification.

Rational extractors 1C93E/1C92A/1C916 return whole/numerator/denominator (7/3 → 2,1,3). Surd 18176 returns(a√b+c√d)/e (√8 → [2,2,0,0,1]). Ordinary decimal division 15F58 need not preserve fractions; exact constructor 16058 does.

Canonical examples:

~~~text
1/3:       AE BB B8 '1' B9 B8 '3' B9 BC 00
mixed2⅓:   7C BD BB B8 '2' B9 B8 '1' B9 B8 '3' B9 BC 00
√2:        98 B8 '2' B9 00
root(3,8): 9F BB B8 '3' B9 B8 '8' B9 BC 00
sum:       69 B8 'X' BA '1' BA '5' B9 00
~~~

B8/B9 delimit children; BB/BC enclose; BD participates in mixed fractions; BA separates some parameters;00 ends the outer sequence. Input and output token grammars differ. Bytes that resemble ASCII can denote constructs; structural 93 is 10-power here, not a universal inline-fraction meaning.

## Layout dispatch

Classifier 31E2/index 327A maps exactly 14 construct tokens to far-pointer table 2C80. Historical execution checked all 256 input bytes. Dispatch 9DB6 pushesCSR/PC and uses D6A6 POPPC trampoline.

| Tokens | Handler | Construct |
| --- | --- | --- |
| 5D,69 | 99E6 | Product/sum with bounds |
| 5E,73,93 | 8F00 | Power, e-power,10-power |
| 63,98 | 8EA6 | Absolute value, square root |
| 68 | 9086 | Log with base |
| 6A | 97D0 | Definite integral |
| 6B | 9236 | Derivative at a point |
| 7C, AE | 937C | Mixed/stacked fraction |
| 9F | 9648 | Indexed root |
| A4 | 7BC0 | Recurring decoration |

Walker 9CD6 receives expressionER0, metricER2, stackx/y, returning a stopping delimiter or 0 on failure. Four-byte boxes store widthW (little-endian 16-bit), heightH, depthD. Ascent=H−D. Adjacent widths add; C544 merges:

~~~text
D=max(Dleft,Dright)
H=max(Hleft-Dleft,Hright-Dright)+D
~~~

8009=0 selects measurement; nonzero draws. C634 initializes each pass/counters; C664 selects smaller fonts. Measurement caches child boxes near 8640; drawing reuses them for centering, exponents and ornaments. Fixtures checked zero measure framebuffer writes and equal measure/draw boxes.

## Metrics and resource limits

Large/small font defaults(H, D)=(10,5)/(7,3), ordinary advance 6, tiny 4. For small-child fraction at baseliney:

~~~text
W=max(Wnum,Wden)+2; H=Hnum+Hden+2; D=Hden+1
xchild=x+floor((W-Wchild)/2)
ynum=y-Dnum-1; yden=y+Hden-Dden+1
bar: y,x+1 throughx+W-1
~~~

Mixed fractions retain whole-number original font plus 1 pxgap. Exponent baseline=y−(Horiginal−5)+Doriginal−Dexponent. Tested square roots add 7 width/2 height; absolute value adds 12 width/1 height; both keep depth. Indexed roots/calculus have size-dependent branches. Recurring 7AF4 supports dot/overline/underline/bracket styles;1FFE2=1 selects the tested overline.

8C56 places short resultsx=96−W, baseline 32−D; larger values scroll. Horizontal state 8000 uses 8 px units. Limits: weighted recursion 8007≤27, metric allocations 8008≤50, nested height 62, roughly 200 bytesremaining stack. Allocation count is not tree depth. A cache failure can retain an incremented dispatch counter until next initialization.

## Glyphs and framebuffer

3BBC unpacks the ROM tables (exclusive end):

| Range | Content |
| --- | --- |
| 0022..0400 | 176 ordinary,5 bits×9 rows |
| 0400..0694 | Same range,6 rows |
| 0694..070C | 48 tiny,4 bits×5 rows |
| 070C..0754 | 12 control,5 bits×9 rows |
| 0754..078C | 12 control,5 bits×7 rows |

Forc 32..207:bit_index=5(c−32), group=bit_index//8, shift=bit_index%8, address=base+group*height+row. Crossing slices read the next block, heightbytes away, and use mask 7C. Tiny 208..255 take high/low nibbles of 5 rowpairs, maskF0. Character 124 generatesC0 placeholder strokes.

3A8A adds a leading blank row:logical heights 10/7/6 for actual 9/6/5 bitmap rows; small controls adjusty separately. RAM87D0..894F is 32×12 bytes; mask 80>>(x&7). VRAMF800 usesstride 16 with 12 visible bytes. 3D28 maps without clipping;3CFC copies visible bytes preserving padding;3908 clears 384 bytes.

3C8E masks source S with nonzero M and composes:

| Mode | Destination |
| --- | --- |
| 0 | (dst & ~M) \| S |
| 1 | dst \| S |
| 2 | dst & (~M \| S) |
| 3/default | dst ^ S |
| 4 | (dst & ~M) \| (~S & M) |

It refuses destinations below 87DC (protects segment row 0), not upper-bound addresses. Exhaustive checks used nonzero masks and do not establish zero-mask behavior. Glyph startsx>95 are rejected but right-edge output can spill into another row/padding; ordinary callers impose saferstarts. Signed negative y supports partial draw. Single-pixel 3B88 checks 96×32 bounds and can touchrow 0.

Latest browser presentation treats first 12 snapshot bytes as hardware segment controls, renders 18 readable annunciators, and preserves actual matrix rows 1..31 and raw 384 bytes. [lcd-indicators.js](../../../simulator/device/lcd-indicators.js) and [fx_annunciator.c](../../../csrc/ui/fx_annunciator.c) implement that boundary. Two unassigned segment bits remain unlabeled. Memory 96×32 does not imply 32 ordinary visible dot rows.

## Historical proof and limits

The initial renderer investigation covered 16 layout and 8 numeric-to-pixel fixtures; all ordinary 352 font cases, tiny 48, controls 24, all 3072 pixel positions+6 outside,432 glyph edges,131072 mapper states,1310722 compositor/lower-bound cases, all 256 classifiers, transfer padding andrecursion/slot failure.

Historical executed/static instruction counts:345/347 rasterizer,1600/1909 constructs,103/239 viewport,365/591 formatter,140/417 controller,7870/46094 whole image. These are historical execution counts, not later understanding coverage, branch coverage or implementation completion.

Lossless listing reconstructs 131072 bytes and identifies 46094 instructions/112070 bytes. Manual seeds mean “reachable” is not proof of reset reachability. Eight dispatch extents were inferred:13950,1655C,12340,132B0,1323E,1328C, CDC4, DA9E. Embedded 44 bytecandidate F822..F84E has unknown invocation. First-word validity/length checks cover 65536 opcodewords; empty PUSH/POP F08E/F0CE accepted as reference no-ops are absent from classified code. This is not exhaustive operand/flag validation.

Scrolling/editing, alternate recurring styles, deep nested sizes andmode/error paths had narrower coverage. Passiveperipheral ROM fixtures do not prove physical timing or WindowsGUI pixelparity.

Maintained code: [layout](../../../csrc/render/fx_layout.c), [viewport](../../../csrc/render/fx_viewport.c), [rasterizer](../../../csrc/render/fx_render.c), [formatting](../../../csrc/format/fx_format.c). [Provenance](PROVENANCE.md) preserves qualifications and local evidence locations.
