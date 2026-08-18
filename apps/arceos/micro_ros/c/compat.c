#include <stdarg.h>
#include <stddef.h>
#include <stdio.h>

enum {
    CTYPE_UPPER = 0x0100,
    CTYPE_LOWER = 0x0200,
    CTYPE_ALPHA = 0x0400,
    CTYPE_DIGIT = 0x0800,
    CTYPE_XDIGIT = 0x1000,
    CTYPE_SPACE = 0x2000,
    CTYPE_PRINT = 0x4000,
    CTYPE_GRAPH = 0x8000,
    CTYPE_BLANK = 0x0001,
    CTYPE_CNTRL = 0x0002,
    CTYPE_PUNCT = 0x0004,
    CTYPE_ALNUM = 0x0008,
};

const unsigned short **__ctype_b_loc(void)
{
    static unsigned short table[384];
    static const unsigned short *characters = &table[128];
    static int initialized;

    if (!initialized) {
        for (int character = 0; character < 128; ++character) {
            unsigned short flags = 0;
            if (character < 32 || character == 127) {
                flags |= CTYPE_CNTRL;
            }
            if (character == ' ' || character == '\t') {
                flags |= CTYPE_BLANK;
            }
            if (character == ' ' || (character >= '\t' && character <= '\r')) {
                flags |= CTYPE_SPACE;
            }
            if (character >= 32 && character <= 126) {
                flags |= CTYPE_PRINT;
            }
            if (character >= 33 && character <= 126) {
                flags |= CTYPE_GRAPH;
            }
            if (character >= 'A' && character <= 'Z') {
                flags |= CTYPE_UPPER | CTYPE_ALPHA | CTYPE_ALNUM;
            }
            if (character >= 'a' && character <= 'z') {
                flags |= CTYPE_LOWER | CTYPE_ALPHA | CTYPE_ALNUM;
            }
            if (character >= '0' && character <= '9') {
                flags |= CTYPE_DIGIT | CTYPE_ALNUM | CTYPE_XDIGIT;
            }
            if ((character >= 'A' && character <= 'F') ||
                (character >= 'a' && character <= 'f')) {
                flags |= CTYPE_XDIGIT;
            }
            if ((flags & CTYPE_GRAPH) && !(flags & CTYPE_ALNUM)) {
                flags |= CTYPE_PUNCT;
            }
            table[128 + character] = flags;
        }
        initialized = 1;
    }
    return &characters;
}

int __vsnprintf_chk(char *buffer, size_t buffer_size, int flags, size_t object_size,
                    const char *format, va_list arguments)
{
    (void)flags;
    (void)object_size;
    return vsnprintf(buffer, buffer_size, format, arguments);
}

int __snprintf_chk(char *buffer, size_t buffer_size, int flags, size_t object_size,
                   const char *format, ...)
{
    va_list arguments;
    int result;

    (void)flags;
    (void)object_size;
    va_start(arguments, format);
    result = vsnprintf(buffer, buffer_size, format, arguments);
    va_end(arguments);
    return result;
}
