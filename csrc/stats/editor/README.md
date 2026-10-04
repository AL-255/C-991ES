`fx_stats_editor.c` implements the original table operations through the
platform data bus. Rows remain ten-byte numeric records at `82ee`; the editor
copies their bytes without evaluating them. Typed C locals replace native
registers and stack storage. The implementation executes no ROM instructions.

`fx_stats_editor_address_raw` represents entry `5096`, including a bus-address
output parameter that can alias mode and geometry bytes. Row zero passes the
native upper-bound-only check and becomes 255 on decrement. The record index
narrows to a byte before multiplication by ten: with one/two/three columns,
raw row zero selects `8ce4`/`8cda`/`8cd0` for x. The checked UI API requires
STAT mode, one-based visible rows and columns, and rejects row zero.

Native table read/write copies five two-byte words in descending order,
snapshotting each word before writing it. This retains partial record aliases,
ROM reads, ignored ROM writes, address wrap and platform callback effects.
Copies do not allocate a fake CPU stack in RAM.

Insertion has capacity priority over row validation: a full table returns one,
even when the requested row is zero. Otherwise invalid rows return two.
Capacity includes `rows * columns + 80df` reserved records. STAT one-variable
mode has forty record slots; other STAT models have eighty. With no reserved
records, maximum row counts are:

| Table | Frequency off | Frequency on |
| --- | ---: | ---: |
| One variable | 40 | 20 |
| Two variables | 40 | 26 |

Insertion updates the count, shifts rows and trailing reserve records, then
initializes x/y to zero and frequency to one. Deletion shifts the retained
records and zeros the vacated row. These primitives preserve `812a`; their
invoking controller must invalidate the moment cache. STAT clear zeros all
800 table bytes, resets counts/cache, and sets `811c/811d/811e` to one.

Cursor entry `e450` distinguishes handled actions from blocked actions.
Handled actions clear `8100/8101/8130`, even if the cursor finishes at its
starting position. Byte capacity arithmetic wraps, while the `limit - 2`
comparison uses a signed sixteen-bit threshold. Enter advance `ed` stops at
the bottom; ordinary down `e1` wraps. The original TABLE context restriction
on rightward movement is retained.

STAT input commit entry `e680` selects the absolute row from
`811c + 811d - 1`, inserts a missing row, copies the evaluated record, advances
with `ed`, invalidates `812a` and sets UI state `80fe` to three. Its C return
value three is UI state. The preceding evaluator/controller must route
numeric errors before calling the commit API. Other mode branches of `e680`
remain outside this module.

`tools/test_stats_editor_c.py` compares every persistent RAM byte, native
return status and callback state. CPU stack bytes and aliases into that stack
are excluded. Fixtures cover capacity/error priority, reserved data, output
pointer aliases, record aliases, raw versus checked rows, cursor boundaries
and evaluated-input commit with sources that overlap data or controller flags.
