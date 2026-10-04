/* SPDX-License-Identifier: GPL-3.0-only */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "fx_simulator_engine.h"

static void usage(void)
{
    fputs("High-level C calculator simulator\n"
          "  fx991sim [--mode comp|complex|bin|oct|dec|hex]\n"
          "           [--angle deg|rad|grad] [--linear] EXPRESSION\n"
          "  fx991sim --interactive [settings]\n"
          "Interactive mode reads one expression per line and retains Ans/variables.\n"
          "Use :reset to clear the session, or :quit to exit.\n", stderr);
}

static int setting(const char *text, const char *const *names, unsigned count)
{
    for (unsigned n = 0; n < count; ++n)
        if (!strcmp(text, names[n])) return (int)n;
    return -1;
}

static int read_expression(char *line, size_t capacity, size_t *length)
{
    int c, seen = 0, invalid = 0;
    *length = 0;
    while ((c = getchar()) != EOF && c != '\n') {
        seen = 1;
        if (!c) invalid = -2;
        if (*length + 1 < capacity) line[(*length)++] = (char)c;
        else if (!invalid) invalid = -1;
    }
    line[*length] = 0;
    if (!seen && c == EOF) return 0;
    if (invalid) return invalid;
    while (*length && line[*length - 1] == '\r') line[--*length] = 0;
    return 1;
}

int main(int argc, char **argv)
{
    static const char *const modes[] = {"comp", "complex", "bin", "oct", "dec", "hex"};
    static const char *const angles[] = {"deg", "rad", "grad"};
    unsigned mode = 0, angle = 0, math = 1;
    int interactive = 0, end_options = 0;
    const char *expression = NULL;
    for (int n = 1; n < argc; ++n) {
        if (end_options) {
            if (expression) { usage(); return 2; }
            expression = argv[n];
            continue;
        }
        if (!strcmp(argv[n], "--")) { end_options = 1; continue; }
        if (!strcmp(argv[n], "--help")) { usage(); return 0; }
        if (!strcmp(argv[n], "--interactive")) interactive = 1;
        else if (!strcmp(argv[n], "--linear")) math = 0;
        else if (!strcmp(argv[n], "--mode") || !strcmp(argv[n], "--angle")) {
            if (n + 1 >= argc) { usage(); return 2; }
            int is_mode = !strcmp(argv[n], "--mode");
            int value = is_mode ? setting(argv[++n], modes, 6) : setting(argv[++n], angles, 3);
            if (value < 0) { usage(); return 2; }
            if (is_mode) mode = (unsigned)value; else angle = (unsigned)value;
        } else if (!strncmp(argv[n], "--", 2)) { usage(); return 2; }
        else if (!expression) expression = argv[n];
        else { usage(); return 2; }
    }
    if ((!interactive && !expression) || (interactive && expression)) { usage(); return 2; }
    fx_simulator *simulator = fxsim_create();
    if (!simulator) { fputs("Unable to create calculator session\n", stderr); return 1; }
    char response[32768], line[4097];
    int failed = 0;
    if (!interactive) {
        failed = fxsim_evaluate(simulator, expression, mode, angle, math, response, sizeof response);
        if (!failed) puts(response);
    } else {
        for (;;) {
            size_t length;
            int read_status = read_expression(line, sizeof line, &length);
            if (!read_status) break;
            if (read_status < 0) {
                puts(read_status == -2 ?
                     "{\"status\":\"error\",\"error\":\"Expression contains NUL\"}" :
                     "{\"status\":\"error\",\"error\":\"Expression is too long\"}");
                fflush(stdout);
                continue;
            }
            if (!strcmp(line, ":quit")) break;
            if (!strcmp(line, ":reset")) {
                fxsim_reset(simulator);
                puts("{\"status\":\"ok\",\"reset\":true}");
                continue;
            }
            if (!length) continue;
            failed = fxsim_evaluate(simulator, line, mode, angle, math, response, sizeof response);
            if (failed) { fputs("C engine rejected request\n", stderr); break; }
            puts(response);
            fflush(stdout);
        }
        if (ferror(stdin)) failed = 1;
    }
    fxsim_destroy(simulator);
    if (failed) { fputs("C engine rejected request\n", stderr); return 1; }
    return 0;
}
