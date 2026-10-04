# Casio Explore

Research into the Casio fx-991ES Plus firmware, with original execution traces and an ongoing implementation in readable, high-level C.

The [C implementation guide](csrc/README.md) describes the compiled subsystems, build commands, differential tests, and remaining implementation scope. Original CPU execution is confined to the test oracles.

The extracted images and their provenance are recorded in [firmware/extraction.json](firmware/extraction.json). The [complete disassembly](analysis/disassembly/complete.asm) reconstructs the firmware bytes.

The natural-result display investigations include:

- [Exact radical evaluation and display](analysis/exact-result-trace/README.md), including `(sqrt(998)-sqrt(997))/99`.
- [Recognition of rational multiples of π](analysis/pi-result-trace/README.md).
- [Exact replacements for special trigonometric results](analysis/special-angle-trace/README.md).

To repeat firmware extraction, supply an external Ver.4.00 installer; the extraction script requires Python 3, 7z, and objdump:

```sh
python3 tools/extract_firmware.py --installer /path/to/installer.exe
```

The [extraction notes](doc/firmware-extraction.txt) retain the recorded procedure and validation. The [history rewrite record](doc/history-rewrite.json) maps the preserved research commits to their new IDs.
