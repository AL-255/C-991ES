The dynamic constant token `8C` (category6/value66) selects table entry `27DA + 2*(66-41)` and calls `13DB8`. `C2` is `RanInt#(` (category1/value128) and calls the prepared two-bound wrapper `13EBE`.

The persistent seed is the ten-byte numeric record at `821C..8225`. Reset `1D6EC..1D6FA` clears it. The independently implemented key wait increments the **little-endian binary word** at `8224` when no key is pending; this can create any raw exponent/sign pair, while retaining the first eight mantissa bytes. A seed is therefore not validated as an ordinary decimal value before use.

`13DB8` copies the seed and retains its old byte8. It replaces the copied exponent/sign with `99,00`, selecting a positive fraction from the existing mantissa. It converts the old exponent byte as an unsigned **binary** integer, then also sets that record's exponent/sign to `99,00`. For example old byte`99` is binary153, whose selected decimal mantissa is `.153`. The generic operation `1C6A4` is **addition**. If its status is an error or its value classifies zero, the caller retries with the selected mantissa of1 (`.1`) plus the same addend.

After another positive fractional-mantissa selection, the generator multiplies by the ROM constant4294967295 (`2^32-1`, external bytes`04294967295000000901` at`2AAA`). `08078` repeatedly divides by256 and extracts three low bytes, then extracts the fourth high byte. The finite decimal operations are preserved; a direct host numeric cast would bypass them. The resulting integer passes through:

```c
x ^= x << 13;
x ^= x >> 17;
x ^= x << 5;
```

`080F4` reconstructs a decimal integer exactly. The caller divides it by4294967295 and takes the fractional part. It stores that full fifteen-digit record at821C before changing the output. Ran# then shifts bythree decimal places, truncates towardzero, and shifts back bythree. Thus the first zero-seed result is output`.499`, with seed`.499987918068652`.

`13EBE` prepares lower and upper scalar records separately. It checks both with `CAA8`, which requires an integral value within the original ten-digit exponent gate, then checks `upper-lower` by the same gate and requires a strictly positive result. Equal bounds fail. It addsone only after this validation, so `0..9999999999` is accepted even though its width is10000000000. Rejected bounds export F8/Argument8 and retain the seed.

Accepted bounds call Ran#, then fetch the **full new seed**, rather than its three-place output. They compute `(upper-lower+1)*seed+lower`, truncate towardzero and subtractone if the original result was negative and changed. The public result contains value, next seed and native status. Input records are copied before writing result, including exact and partial aliases.

The native fixture corpus also retains forged8x seed records. Reset, key wait and returned random generation do not create these headers. Their generic exact arithmetic sometimes retains a compact result and sometimes becomes decimal or an error. That unchecked policy is an explicit implementation gap, with `UNIMPLEMENTED` and untouched result. It is not replaced by a default seed or counted as successful value parity. Similarly, proven native raw-decimal magnitude-ordering cycles remain explicit boundaries.

The test oracle runs the unmodified extracted ROM. Its C implementation never calls the oracle, executes a ROM instruction, samples a host RNG or uses floating point.
