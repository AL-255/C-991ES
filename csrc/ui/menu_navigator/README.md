`fx_menu_navigator` translates the generic DFDE controller. The immutable ROM
table at0B9A has sixteen bytes per page: text pointer, leaf and action masks,
eight numbered choices, up/down/back destinations, and a close token. Actual
menu data occupies pages0..62. An initial high-bit page is painted normally;
only a later navigation to a high-bit destination completes with result1.

The second native argument is an optional heading address. MODE's `7F E2`
instruction supplies signed immediate−1, so the actual ER2 value isFFFF. That
sentinel removes the heading and enables MODE's close policy. It is neither
a font string at007F nor a choice-visibility mask. A nonzero ordinary heading
uses the first line, followed by three body lines; a zero heading uses four
body lines. Left navigation clears an ordinary heading.

Begin and tick use the real outer key controller. Modifier keys, host exports,
reset, ordinary annunciator classification and input pairing retain that
controller's semantics. A returned semantic token can also be supplied at the
explicit prepared E04E adapter. Selection and return bytes live in host state,
without a synthetic persistent CPU-frame argument.

Ignored or unavailable choices and AC retain the native LCD blink through a
`FX_MENU_TIMER` request with period0770. The host acknowledges its delay with
`fx_menu_navigator_resume_timer`; repeated ticks during the delay make no extra
writes. AC returns0, close/navigation1, action leaves2, and ordinary leaves3.
The API does not execute CPU STOP or inject a physical timer interrupt.

The canonical original-ROM suite has95,908 checks:64,265 native observable
checkpoints and31,643 retained-delay/bounds checks. Every actual table page,
every token byte and both close policies are covered, along with ordinary
heading painters and genuine raw-key paths. Complete RAM/MMIO and the F000
write observer are compared, excluding only native CPU stack8B00..8DED.
Arbitrary pages whose text aliases generated CPU-frame contents are outside
the fixture domain. The F000 observer is distinct from the original Windows
SimU8 STOP callback, whose scheduling audit is published separately.
