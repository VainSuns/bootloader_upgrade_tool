MEMORY
{
PAGE 0 :
	RESET                 : origin = 0x3FFFC0, length = 0x000002

    SERVICE_HEADER        : origin = 0x013000, length = 0x000020
    SERVICE_PUBLISH_STATE : origin = 0x013020, length = 0x000002
    SERVICE_RUNTIME_STATE : origin = 0x013022, length = 0x00003E
    SERVICE_FRONT_RSV     : origin = 0x013060, length = 0x000020
    SERVICE_APP_EXPORT    : origin = 0x013080, length = 0x000002
    SERVICE_IMMUTABLE     : origin = 0x013082, length = 0x002A7E
    SERVICE_DATA          : origin = 0x015B00, length = 0x000500
PAGE 1 :

   RAMM1           : origin = 0x000400, length = 0x0003F8     /* on-chip RAM block M1 */
}

SECTIONS
{
    .flash_service_header        : > SERVICE_HEADER,        PAGE = 0
    .flash_service_publish_state : > SERVICE_PUBLISH_STATE, PAGE = 0
    .flash_service_runtime_state : > SERVICE_RUNTIME_STATE, PAGE = 0
    .flash_service_app_export    : > SERVICE_APP_EXPORT,    PAGE = 0

   .text            : > SERVICE_IMMUTABLE, PAGE = 0
   .cinit           : > SERVICE_DATA,      PAGE = 0 /* not used, */
   .switch          : > SERVICE_IMMUTABLE, PAGE = 0
   .reset           : > RESET,             PAGE = 0, TYPE = DSECT /* not used, */
   .stack           : > RAMM1,             PAGE = 1 /* not used, */

#if defined(__TI_EABI__)
   .bss             : > SERVICE_DATA, PAGE = 0
   .bss:output      : > SERVICE_DATA, PAGE = 0
   .init_array      : > SERVICE_DATA, PAGE = 0
   .const           : > SERVICE_IMMUTABLE, PAGE = 0
   .data            : > SERVICE_DATA, PAGE = 0
   .sysmem          : > SERVICE_DATA, PAGE = 0
#else
   .pinit           : > SERVICE_DATA, PAGE = 0
   .ebss            : > SERVICE_DATA, PAGE = 0
   .econst          : > SERVICE_IMMUTABLE, PAGE = 0
   .esysmem         : > SERVICE_DATA, PAGE = 0
#endif

#ifdef __TI_COMPILER_VERSION__
   #if __TI_COMPILER_VERSION__ >= 15009000
    .TI.ramfunc : {} > SERVICE_IMMUTABLE, PAGE = 0
   #else
    ramfuncs    : > SERVICE_IMMUTABLE PAGE = 0
   #endif
#endif
}
