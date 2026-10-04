/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_SIMULATOR_INPUT_H
#define FX_SIMULATOR_INPUT_H
#include <stddef.h>
#include <stdint.h>

#define FXSIM_INPUT_MAX_BYTES 4096u
#define FXSIM_INPUT_MAX_NESTING 32u

/* Encode ASCII notation without evaluating it. Mode0=COMP,1=CMPLX,
 * 2=BIN,3=OCT,4=DEC,5=HEX. The ordinary entry selects COMP.
 *
 * Success0: output is terminated by native token0; length includes that
 * terminator, error_position is0. Failure-1: invalid arguments/mode, unsupported
 * text or malformed syntax. Failure-2: insufficient output capacity. On failure
 * output is unchanged, length is0, and error_position is an ASCII byte offset
 * (end-of-input for missing delimiters/capacity). error_position may be NULL;
 * expression, output and length must be non-NULL. The size output objects must
 * be separate from expression/output. Expression and output may overlap.
 *
 * Source is bounded to4096 bytes excluding NUL. Explicit/function nesting is
 * at most32; recursive unary/power syntax is additionally bounded to128 levels.
 * ASCII space/tab/CR/LF/formfeed/vertical-tab are ignored between tokens.
 * Function/word-operator names, pi, Ans and PreAns are case-insensitive.
 * PreAns is available only in COMP, matching the native C8 token override.
 * Single-letter
 * lowercase e/i are constants; uppercase A-F/X/Y/M are variables. HEX mode
 * interprets A-F/a-f as digits; var(A)..var(F) explicitly loads those variables.
 * Digits are transported even when outside the selected radix: native syntax
 * and mathematical admission remain the evaluator's responsibility.
 *
 * Operators: + - * / ^ ! %, implicit multiplication, nPr/nCr, and BASE-N
 * and/or/xor/xnor. Powers are right-associative and each native implicit power
 * group is closed explicitly. Native implicit multiplication precedence is
 * retained. Scientific e/E notation uses one/two decimal exponent digits.
 * Terminal ->A..F/X/Y/M stores are supported.
 *
 * Functions require parentheses. Scalar functions include sqrt,cbrt,sin,cos,
 * tan,asin,acos,atan,sinh,cosh,tanh,asinh,acosh,atanh,log,ln,exp,exp10,abs,
 * conj,arg,round/Rnd,Not,Neg,square,cube,inv. log accepts (value) or (base,value).
 * frac/nthroot/nPr/nCr/qrem take two arguments; nthroot(degree,radicand).
 * Pol/Rec,RanInt take two; sum/prod take three; integral three/four; diff two/
 * three. Rand/Ran# optionally takes empty parentheses. det,trn,ref,rref are
 * transported; their evaluator mode/type admission is not promised here.
 */
int fxsim_encode_expression(const char *expression, uint8_t *output,
    size_t capacity, size_t *length, size_t *error_position);
int fxsim_encode_expression_mode(const char *expression, unsigned mode,
    uint8_t *output, size_t capacity, size_t *length, size_t *error_position);
#endif
