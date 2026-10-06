# Natural result display

The fx-991ES PLUS C Ver.4 ROM uses three distinct mechanisms:

| Mechanism | Stage | Finding |
| --- | --- | --- |
| Exact rational/surd arithmetic | Evaluation | Components and coefficients can survive arithmetic in tagged ten-byte records. |
| Finite trig-result lookup | Evaluation | Computed magnitudes can match stored decimal constants and be replaced by paired exact records. |
| Numeric fraction/π recognition | Formatting | Eligible ordinary results can become fractions or fixed-scale rational multiples of π. |

The final renderer constructs a new structural expression from the numeric result, measures it, draws ROM glyphs and ornaments, and transfers the framebuffer.

Read the [complete exact pipeline](exact-pipeline.md), [recognition and special angles](numeric-recognition.md), and [expression renderer](expression-renderer.md). [Provenance](PROVENANCE.md) identifies the pinned image, historical investigations and local evidence.

“QPI” means approximate-value expression recognition, following the user's [HP-42S reference](https://www.hpmuseum.org/software/qpi/42sqpi.htm). Similar behavior does not establish that Casio used that program. Its observed π mechanism is narrower; the requested (√998−√997)/99 example retains exact components.

These are curated historical findings, not new tests, complete C implementation, or universal firmware parity. Raw research remains local under analysis/ and is excluded from repository history.
