#include "fx_render_context.h"

uint8_t fx_display_setup_item(const fx_render *render)
{
    uint8_t mode = render->memory[0x80fa];
    if (mode >= 4 && render->memory[0x8137]) mode = (uint8_t)(mode + 4);
    uint16_t address = (uint16_t)(0x2ac4 + 5 * (uint8_t)(mode - 1)
                                + render->memory[0x80fd]);
    return address < render->rom_size ? render->rom[address] : 0;
}

int fx_display_is_special_view(const fx_render *render)
{
    uint8_t context = render->memory[0x80fc], submode = render->memory[0x80fd];
    if ((context & 0x80) && submode == 2) return 1;
    if (context == 9) return fx_display_setup_item(render) != 9;
    return context == 6 && submode >= 1 && submode <= 3;
}

int fx_display_has_formula_view(const fx_render *render)
{
    return !(render->memory[0x80fc] & 0x10) && !fx_display_is_special_view(render);
}

int fx_display_has_natural_input(const fx_render *render)
{
    return fx_display_has_formula_view(render) && render->memory[0x8106]
        && (render->memory[0x80f9] & 0x80);
}

int fx_display_has_natural_result(const fx_render *render)
{
    if (!fx_display_has_formula_view(render)) return 0;
    uint8_t selection = render->memory[0x8100] & 15;
    return selection == 14 || selection == 15
        || (render->memory[0x8106] && (render->memory[0x80f9] & 0x40));
}
