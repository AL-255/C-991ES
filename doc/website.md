# C-991ES website

Repository: https://github.com/AL-255/C-991ES

Public calculator: https://al-255.github.io/C-991ES/

Device route: https://al-255.github.io/C-991ES/device/

The repository was renamed on 2026-10-06. Both webpage titles, accessibility
labels, authored SVG casing and local server branding use **C-991ES**.
Historical manufacturer references remain in repository research documentation.

The branded source is commit `d8632d6e523eaae8d6a5bba15f25c39f53f2a128`.
[Pages run 37520088656](https://github.com/AL-255/C-991ES/actions/runs/37520088656)
built and deployed it successfully. Its 281 input pins and 13 output artifacts
match the isolated local build. The WASM engine retains SHA-256
`8e918dbf1649887a561b3860e91eea55e16ceb3503fe3267a52746fb4f11d473`:
130 committed firmware units plus five browser adapters. Pending 144-module
audit work remains uncommitted and is separate from this release.

Actual public HTTP checks matched every exposed build artifact and found no
case-insensitive Casio text in served frontend assets. Browser checks passed on
both routes at desktop and 320px widths: titles, DOM text/attributes, SVG brand
fit, all 50 hit targets, cold/ON reset, `1+2=3`, division-by-zero error and AC
cancellation. LCD pixels/indicators match the actual C snapshots; all seven
loaded resources match CI and no browser errors occurred. This is UI verification,
not a new original-firmware execution or full parity claim.

Raw reports and screenshots are local-only under
`analysis/build/c991es-branding-20261006/`. The CI build-report SHA-256 is
`e1a3e80b7fbb8eaa2ea90abfa5d2954e28141863f8e07799a4e8be7778709457`.
