The matrix/vector display uses its own grid controller. MATRIX is mode6 and
VECTOR is mode7; their editor screens are19 and20. Both use the same slot
backing as the numerical kernels: nine ten-byte cells, with row stride three.

The prepared current-view path selects the cell pointer from the ROM table at
0F94, copies the real record to8140 and zeros the imaginary cache at814A. It
clears the framebuffer, draws the tiny slot caption, draws brackets from the
dimensions, and traverses the active cells. Each grid cell is serialized by
3500 with a six-character budget. The cell renderer pads on the left and uses
the final six bytes. Coordinates are x=12+28(column−1), y=7+6(row−1). A selected
cell uses composition mode4; every cell resets composition mode tozero.

After the grid, the controller selects font7 and calls the existing37BC real
value line. That line shows the selected value at full precision and updates
the numeric format-selection state. Matrix display never converts or mutates
the underlying cell records. The public renderer receives resolved selected
coordinates; the separate navigation API changes811D/811E and applies the51AA
selection/cache reset only when movement succeeds. Right/equals advances
through cells in row order; left moves backward in that order. Up/down retain
the column. A boundary or unrecognized key returns native status1.

Native differential tests compare full RAM and LCD framebuffer regions,
8100..815F, F031, immutable input records and backing. They cover every byte
key at every valid position of all nine dimension pairs, all selection
positions, NULL compact fields, randomized display maps/composition state,
ordinary decimals/rationals/surds, decimal markers and error records. Foreign
6x rich records are covered as compact ERROR fields. Their selected scalar
fallback is outside the typed full-view contract and returns−1.

The selected value inherits the shared special-result controller's existing
small/extended exponent limitations. Its native local text buffer holds26
bytes; oversized prime-factor output can overwrite saved CPU registers. The
portable full-view API reports serialized length≥26 as−1 before drawing.
The native fault examples remain recorded in render_linalg.json. Physical key
scanning, user-slot switching, editing and evaluator reference dispatch remain
separate work; this module does not contain another parser.
