# C-991ES

Research into the Casio fx-991ES Plus firmware and an ongoing implementation in readable, high-level C.

The [browser calculator](https://al-255.github.io/C-991ES/) retains the original fx-991ES PLUS C LCD and keypad layout with authored flat SVG, HTML and CSS. All 49 matrix keys drive a persistent C runtime through WebAssembly. Its LCD renders actual matrix pixels and 18 status indicators. The [device route](https://al-255.github.io/C-991ES/device/) presents the same calculator. See the [simulator guide](simulator/README.md) for builds, keyboard shortcuts and verification limits.

The [C implementation guide](csrc/README.md) describes the subsystems, native builds and differential tests. The project remains incomplete; documented instruction understanding and successful UI tests do not establish full firmware parity. The [website verification record](doc/website.md) binds the C-991ES branding to its actual Pages build and browser checks. The published engine and pending working-tree audit are distinguished in [AGENTS.md](AGENTS.md).

Useful reverse-engineered knowledge is retained in [doc/reverse-engineering](doc/reverse-engineering/README.md):

- [Natural display](doc/reverse-engineering/natural-display/README.md): exact radicals, rational/π recognition, special trigonometric replacements, and EQN versus SOLVE display policy.
- [Arithmetic and parser](doc/reverse-engineering/arithmetic/README.md): records, stacks, numeric kernels and corrected interpretations.
- [Runtime and LCD](doc/reverse-engineering/runtime/README.md): controllers, scheduling, indicator controls and parity limits.
- [Firmware lineage](doc/reverse-engineering/firmware-lineage/README.md): related images and original host behavior.

Raw disassembly, traces, screenshots, fixtures and generated reports remain in the local ignored `analysis/` directory. The external `eps-emu/` checkout and editor settings in `.vscode/` are also local-only. These directories were removed from Git history and are absent from fresh clones. Native/WASM builds use tracked sources and firmware data; original differential tests additionally require their local analysis inputs.

Firmware images and provenance are recorded in [firmware/extraction.json](firmware/extraction.json). To repeat extraction, supply an external Ver.4.00 installer and install Python 3, 7z and objdump:

```sh
python3 tools/extract_firmware.py --installer /path/to/installer.exe
```

The [extraction notes](doc/firmware-extraction.txt) retain the procedure and validation. [History cleanup](doc/history-cleanup.json) records this artifact removal; [the earlier rewrite](doc/history-rewrite.json) records the previous original-history cleanup. Progress plotting has been retired.
