/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_simulator_input.h"
#include <string.h>

/* No numeric conversion is performed. Extra bytes are closing tokens for
 * powers and groups introduced by the ASCII function spelling. */
#define TOKEN_CAPACITY (FXSIM_INPUT_MAX_BYTES * 2u + 1u)
typedef struct {
    const char *text;
    size_t size, position, used, error;
    unsigned mode, nesting, recursion;
    int status;
    uint8_t tokens[TOKEN_CAPACITY];
} encoder;
typedef struct {
    const char *name;
    uint8_t token, minimum, maximum, form;
} function;
enum { PREFIX, INFIX, POSTFIX };
static const function functions[] = {
    {"sqrt",0x98,1,1,PREFIX}, {"cbrt",0xa8,1,1,PREFIX},
    {"sin",0xa0,1,1,PREFIX}, {"cos",0xa1,1,1,PREFIX}, {"tan",0xa2,1,1,PREFIX},
    {"asin",0xb0,1,1,PREFIX}, {"acos",0xb1,1,1,PREFIX}, {"atan",0xb2,1,1,PREFIX},
    {"sinh",0x70,1,1,PREFIX}, {"cosh",0x71,1,1,PREFIX}, {"tanh",0x72,1,1,PREFIX},
    {"asinh",0x90,1,1,PREFIX}, {"acosh",0x91,1,1,PREFIX}, {"atanh",0x92,1,1,PREFIX},
    {"log",0x68,1,2,PREFIX}, {"log10",0x68,1,1,PREFIX}, {"ln",0xa3,1,1,PREFIX},
    {"exp",0x73,1,1,PREFIX}, {"exp10",0x93,1,1,PREFIX},
    {"abs",0x63,1,1,PREFIX}, {"conj",0x88,1,1,PREFIX}, {"arg",0xc3,1,1,PREFIX},
    {"round",0xb3,1,1,PREFIX}, {"rnd",0xb3,1,1,PREFIX},
    {"not",0x61,1,1,PREFIX}, {"neg",0x62,1,1,PREFIX},
    {"det",0xc0,1,1,PREFIX}, {"trn",0xc1,1,1,PREFIX},
    {"ref",0x5a,1,1,PREFIX}, {"rref",0x5b,1,1,PREFIX},
    {"pol",0x6c,2,2,PREFIX}, {"rec",0x6d,2,2,PREFIX},
    {"ranint",0xc2,2,2,PREFIX}, {"sum",0x69,3,3,PREFIX},
    {"prod",0x5d,3,3,PREFIX}, {"integral",0x6a,3,4,PREFIX},
    {"diff",0x6b,2,3,PREFIX},
    {"frac",0xae,2,2,INFIX}, {"nthroot",0x9f,2,2,INFIX},
    {"npr",0xbe,2,2,INFIX}, {"ncr",0xbf,2,2,INFIX}, {"qrem",0x5f,2,2,INFIX},
    {"square",0x75,1,1,POSTFIX}, {"cube",0x76,1,1,POSTFIX},
    {"inv",0x77,1,1,POSTFIX}
};
static int letter(unsigned char c)
{ return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); }
static int digit(unsigned char c) { return c >= '0' && c <= '9'; }
static unsigned char lower(unsigned char c)
{ return c >= 'A' && c <= 'Z' ? (unsigned char)(c + ('a'-'A')) : c; }
static int space(unsigned char c)
{ return c == ' ' || c == '\t' || c == '\r' || c == '\n' || c == '\f' || c == '\v'; }
static void skip(encoder *p)
{ while (p->position < p->size && space((unsigned char)p->text[p->position])) ++p->position; }
static void fail(encoder *p, size_t position)
{ if (!p->status) { p->status = -1; p->error = position; } }
static void emit(encoder *p, uint8_t token)
{
    if (p->status) return;
    if (p->used == TOKEN_CAPACITY) { fail(p,p->position); return; }
    p->tokens[p->used++] = token;
}
static int name_is(const encoder *p, size_t start, size_t length, const char *name)
{
    size_t i;
    if (strlen(name) != length) return 0;
    for (i=0;i<length;++i)
        if (lower((unsigned char)p->text[start+i]) != (unsigned char)name[i]) return 0;
    return 1;
}
static int enter(encoder *p, size_t start)
{
    if (p->nesting == FXSIM_INPUT_MAX_NESTING) { fail(p,start); return 0; }
    ++p->nesting; return 1;
}
static int variable(unsigned char c)
{
    if (c >= 'A' && c <= 'F') return c;
    if (c == 'X' || c == 'Y') return c;
    if (c == 'M') return 0x54;
    return -1;
}
static int hex_word(const encoder *p, size_t start)
{
    size_t cursor=start;
    while (cursor < p->size && (letter((unsigned char)p->text[cursor]) ||
            digit((unsigned char)p->text[cursor]) || p->text[cursor] == '_')) {
        unsigned char c=lower((unsigned char)p->text[cursor++]);
        if (!digit(c) && !(c >= 'a' && c <= 'f')) return 0;
    }
    return cursor != start;
}
static void expression(encoder *p, unsigned minimum);
static void number(encoder *p)
{
    unsigned points=0, digits=0;
    size_t exponent;
    while (p->position < p->size) {
        unsigned char c=(unsigned char)p->text[p->position];
        if (digit(c)) ++digits;
        else if (c == '.' && p->mode < 2) {
            if (points++) { fail(p,p->position); return; }
        } else if (p->mode == 5 && lower(c) >= 'a' && lower(c) <= 'f') {
            emit(p,(uint8_t)(0xb8 + lower(c)-'a')); ++p->position; ++digits; continue;
        } else break;
        emit(p,c); ++p->position;
    }
    if (p->mode >= 2 || p->position == p->size) return;
    exponent=p->position;
    if (p->text[exponent] != 'e' && p->text[exponent] != 'E') return;
    ++exponent;
    if (exponent < p->size && (p->text[exponent] == '+' || p->text[exponent] == '-')) ++exponent;
    /* Bare lower-case e remains Euler's constant; upper-case E is a variable. */
    if (exponent == p->size || !digit((unsigned char)p->text[exponent])) return;
    if (!digits) { fail(p,p->position); return; }
    emit(p,0x74); ++p->position;
    if (p->text[p->position] == '+' || p->text[p->position] == '-') {
        emit(p,p->text[p->position] == '-' ? 0x60 : '+'); ++p->position;
    }
    digits=0;
    while (p->position < p->size && digit((unsigned char)p->text[p->position])) {
        if (digits++ == 2) { fail(p,p->position); return; }
        emit(p,(uint8_t)p->text[p->position++]);
    }
}
static void call(encoder *p, const function *f, size_t start)
{
    unsigned count=0;
    if (!enter(p,start)) return;
    ++p->position; /* ASCII opening parenthesis, implicit in PREFIX token. */
    if (f->form == PREFIX) emit(p,f->token);
    else { emit(p,'('); if (f->form == INFIX) emit(p,'('); }
    for (;;) {
        skip(p);
        if (p->position == p->size || p->text[p->position] == ')' ||
            p->text[p->position] == ',') { fail(p,p->position); break; }
        expression(p,0); ++count; skip(p);
        if (p->status) break;
        if (p->position < p->size && p->text[p->position] == ',') {
            if (count == f->maximum) { fail(p,p->position); break; }
            ++p->position;
            if (f->form == INFIX) { emit(p,')'); emit(p,f->token); emit(p,'('); }
            else emit(p,',');
        } else {
            if (count < f->minimum || p->position == p->size || p->text[p->position] != ')')
                fail(p,p->position);
            else {
                ++p->position; emit(p,')');
                if (f->form == INFIX) {
                    /* Nth-root's operator also includes an implicit open. */
                    if (f->token == 0x9f) emit(p,')');
                    emit(p,')');
                } else if (f->form == POSTFIX) emit(p,f->token);
            }
            break;
        }
    }
    --p->nesting;
}
static void primary(encoder *p)
{
    size_t start, end, i;
    unsigned char c;
    skip(p); start=p->position;
    if (start == p->size) { fail(p,start); return; }
    c=(unsigned char)p->text[start];
    if (digit(c) || c == '.' || (p->mode == 5 && hex_word(p,start))) {
        number(p); return;
    }
    if (c == '(') {
        if (!enter(p,start)) return;
        ++p->position; emit(p,'('); expression(p,0); skip(p);
        if (!p->status && (p->position == p->size || p->text[p->position] != ')')) fail(p,p->position);
        else if (!p->status) { ++p->position; emit(p,')'); }
        --p->nesting; return;
    }
    if (c == '-' || c == '+') {
        ++p->position; emit(p,c == '-' ? 0x60 : '+'); expression(p,40); return;
    }
    if (!letter(c)) { fail(p,start); return; }
    end=start+1;
    while (end < p->size && (letter((unsigned char)p->text[end]) || digit((unsigned char)p->text[end]) || p->text[end] == '_')) ++end;
    p->position=end; skip(p);
    if (name_is(p,start,end-start,"var")) {
        int token;
        if (p->position == p->size || p->text[p->position] != '(') { fail(p,p->position); return; }
        ++p->position;
        skip(p);
        if (p->position == p->size || (token=variable((unsigned char)p->text[p->position])) < 0) { fail(p,p->position); return; }
        ++p->position; skip(p);
        if (p->position == p->size || p->text[p->position] != ')') { fail(p,p->position); return; }
        ++p->position; emit(p,(uint8_t)token); return;
    }
    if (name_is(p,start,end-start,"pi")) { emit(p,0x82); return; }
    if (name_is(p,start,end-start,"ans")) { emit(p,0x8b); return; }
    if (name_is(p,start,end-start,"preans")) {
        if (p->mode) fail(p,start);
        else emit(p,0xc8);
        return;
    }
    if (end-start == 1 && (c == 'e' || c == 'i' || variable(c) >= 0)) {
        emit(p,c == 'e' ? 0x81 : c == 'i' ? 0x80 : (uint8_t)variable(c)); return;
    }
    if (name_is(p,start,end-start,"rand") || name_is(p,start,end-start,"ran")) {
        if (p->position < p->size && p->text[p->position] == '#') ++p->position;
        skip(p);
        if (p->position < p->size && p->text[p->position] == '(') {
            ++p->position; skip(p);
            if (p->position == p->size || p->text[p->position] != ')') { fail(p,p->position); return; }
            ++p->position;
        }
        emit(p,0x8c); return;
    }
    for (i=0;i<sizeof(functions)/sizeof(functions[0]);++i) {
        if (name_is(p,start,end-start,functions[i].name)) {
            if (p->position == p->size || p->text[p->position] != '(') fail(p,p->position);
            else call(p,&functions[i],start);
            return;
        }
    }
    fail(p,start);
}
static int word_operator(encoder *p, uint8_t *token, unsigned *rank, size_t *end)
{
    static const char *const names[]={"npr","ncr","and","or","xor","xnor"};
    static const uint8_t tokens[]={0xbe,0xbf,0x6e,0x6f,0x7e,0x7f};
    size_t i, start=p->position;
    *end=start;
    while (*end < p->size && letter((unsigned char)p->text[*end])) ++*end;
    for (i=0;i<sizeof(names)/sizeof(names[0]);++i)
        if (name_is(p,start,*end-start,names[i])) {
            if (i >= 2 && p->mode < 2) { fail(p,start); return 0; }
            *token=tokens[i]; *rank=i < 2 ? 25 : i == 2 ? 6 : 5; return 1;
        }
    return 0;
}
static void expression(encoder *p, unsigned minimum)
{
    if (p->status) return;
    if (++p->recursion > 128) { fail(p,p->position); --p->recursion; return; }
    primary(p);
    while (!p->status) {
        uint8_t token=0;
        unsigned rank=0;
        size_t end;
        int implicit=0, power=0;
        unsigned char c;
        skip(p);
        if (p->position == p->size) break;
        c=(unsigned char)p->text[p->position]; end=p->position+1;
        if (c == '!' || c == '%') {
            if (70 < minimum) break;
            ++p->position; emit(p,c == '!' ? 0x57 : 0x25); continue;
        }
        if (c == '-' && end < p->size && p->text[end] == '>') break;
        if (c == '+' || c == '-') { rank=10; token=c; }
        else if (c == '*' || c == '/') { rank=20; token=c == '*' ? 0x4e : 0x4f; }
        else if (c == '^') { rank=65; token=0x5e; power=1; }
        else if (letter(c) && word_operator(p,&token,&rank,&end)) { }
        else if (c == '(' || letter(c)) { rank=30; implicit=1; }
        else break;
        if (p->status || rank < minimum) break;
        if (!implicit) { p->position=end; emit(p,token); }
        expression(p,power ? rank : rank+1);
        if (power) emit(p,')');
    }
    --p->recursion;
}
int fxsim_encode_expression_mode(const char *text, unsigned mode, uint8_t *output,
    size_t capacity, size_t *length, size_t *error_position)
{
    encoder p;
    size_t size;
    if (length) *length=0;
    if (error_position) *error_position=0;
    if (!text || !output || !length || mode > 5) return -1;
    for (size=0;size<=FXSIM_INPUT_MAX_BYTES;++size) if (!text[size]) break;
    if (size > FXSIM_INPUT_MAX_BYTES) {
        if (error_position) *error_position=FXSIM_INPUT_MAX_BYTES;
        return -1;
    }
    memset(&p,0,sizeof(p)); p.text=text; p.size=size; p.mode=mode;
    expression(&p,0); skip(&p);
    if (!p.status && p.position+1 < p.size && text[p.position] == '-' && text[p.position+1] == '>') {
        int token;
        p.position+=2; skip(&p);
        token=p.position < p.size ? variable((unsigned char)text[p.position]) : -1;
        if (token < 0) fail(&p,p.position);
        else {
            static const uint8_t stores[]={0x47,0x48,0x49,0x4a,0x83,0x84};
            unsigned char name=(unsigned char)text[p.position++];
            emit(&p,name >= 'A' && name <= 'F' ? stores[name-'A'] :
                name == 'M' ? 0x4b : name == 'X' ? 0x4c : 0x4d);
            skip(&p);
        }
    }
    if (!p.status && p.position != p.size) fail(&p,p.position);
    if (!p.status) emit(&p,0);
    if (!p.status && p.used > capacity) { p.status=-2; p.error=p.size; }
    if (p.status) { if (error_position) *error_position=p.error; return p.status; }
    memcpy(output,p.tokens,p.used); *length=p.used; return 0;
}
int fxsim_encode_expression(const char *text, uint8_t *output, size_t capacity,
    size_t *length, size_t *error_position)
{ return fxsim_encode_expression_mode(text,0,output,capacity,length,error_position); }
