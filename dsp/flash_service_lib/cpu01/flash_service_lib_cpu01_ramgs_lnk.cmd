MEMORY
{
PAGE 0 :
	RESET            : origin = 0x3FFFC0, length = 0x000002

    SERVICE_DESC       : origin = 0x013000, length = 0x000014
    SERVICE_CRC_PATCH  : origin = 0x013014, length = 0x000002
    SERVICE_HEADER_RSV : origin = 0x013016, length = 0x00000A
    SERVICE_API        : origin = 0x013020, length = 0x000060

    SERVICE_CODE       : origin = 0x013080, length = 0x002A80
    SERVICE_DATA       : origin = 0x015B00, length = 0x000500
PAGE 1 :

   RAMM1           : origin = 0x000400, length = 0x0003F8     /* on-chip RAM block M1 */
}

SECTIONS
{
    .flash_service_descriptor : > SERVICE_DESC, PAGE = 0
    .flash_service_crc_patch  : > SERVICE_CRC_PATCH, PAGE = 0
    .flash_service_api        : > SERVICE_API, PAGE = 0

   .text            : > SERVICE_CODE,     PAGE = 0
   .cinit           : > SERVICE_DATA,     PAGE = 0 /* not used, */
   .switch          : > SERVICE_CODE,     PAGE = 0
   .reset           : > RESET,     PAGE = 0, TYPE = DSECT /* not used, */
   .stack           : > RAMM1,     PAGE = 1 /* not used, */

#if defined(__TI_EABI__)
   .bss             : > SERVICE_DATA,    PAGE = 0
   .bss:output      : > SERVICE_DATA,    PAGE = 0
   .init_array      : > SERVICE_DATA,    PAGE = 0
   .const           : > SERVICE_DATA,    PAGE = 0
   .data            : > SERVICE_DATA,    PAGE = 0
   .sysmem          : > SERVICE_DATA,    PAGE = 0
#else
   .pinit           : > SERVICE_DATA,    PAGE = 0
   .ebss            : > SERVICE_DATA,    PAGE = 0
   .econst          : > SERVICE_DATA,    PAGE = 0
   .esysmem         : > SERVICE_DATA,    PAGE = 0
#endif

#ifdef __TI_COMPILER_VERSION__
   #if __TI_COMPILER_VERSION__ >= 15009000
    .TI.ramfunc : {} > SERVICE_CODE,      PAGE = 0
   #else
    ramfuncs    : > SERVICE_CODE      PAGE = 0
   #endif
#endif
}
