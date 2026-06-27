typedef unsigned long uint32_t;
volatile uint32_t g_boot_user_jump_entry;
uint32_t read_entry(void) { return g_boot_user_jump_entry; }
