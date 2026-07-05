
MEMORY
{
PAGE 0 :
   /* Program Memory */
          /* Memory (RAM/FLASH) blocks can be moved to PAGE1 for data allocation */
          /* BEGIN is used for the "boot to Flash" bootloader mode   */

   BEGIN            : origin = 0x080000, length = 0x000002
   RESET            : origin = 0x3FFFC0, length = 0x000002

  /* Flash sectors */
   BOOT_FLASH_CODE    : origin = 0x080002, length = 0x001FFE	/* on-chip Flash */
   /*FLASHB           : origin = 0x082000, length = 0x002000*/	/* on-chip Flash */
   

   BOOT_DATA       : origin = 0x00C000, length = 0x000800
   BOOT_RAM_CODE   : origin = 0x00C800, length = 0x000800

PAGE 1 :

   RAMM1           : origin = 0x000400, length = 0x0003F8     /* on-chip RAM block M1 */

   CPU2TOCPU1RAM   : origin = 0x03F800, length = 0x000400
   CPU1TOCPU2RAM   : origin = 0x03FC00, length = 0x000400

   CANA_MSG_RAM     : origin = 0x049000, length = 0x000800
   CANB_MSG_RAM     : origin = 0x04B000, length = 0x000800
}


SECTIONS
{
   codestart        : > BEGIN,          PAGE = 0
   .text            : > BOOT_FLASH_CODE,     PAGE = 0
   .cinit           : > BOOT_FLASH_CODE,     PAGE = 0
   .switch          : > BOOT_FLASH_CODE,     PAGE = 0
   .reset           : > RESET,     PAGE = 0, TYPE = DSECT /* not used, */
   .stack           : > RAMM1,     PAGE = 1

#if defined(__TI_EABI__)
   .bss             : > BOOT_DATA,    PAGE = 0
   .bss:output      : > BOOT_DATA,    PAGE = 0
   .init_array      : > BOOT_FLASH_CODE,    PAGE = 0
   .const           : > BOOT_FLASH_CODE,    PAGE = 0
   .data            : > BOOT_DATA,    PAGE = 0
   .sysmem          : > BOOT_DATA,    PAGE = 0
#else
   .pinit           : > BOOT_FLASH_CODE,    PAGE = 0
   .ebss            : > BOOT_DATA,    PAGE = 0
   .econst          : > BOOT_FLASH_CODE,    PAGE = 0
   .esysmem         : > BOOT_DATA,    PAGE = 0
#endif

#ifdef __TI_COMPILER_VERSION__
    #if __TI_COMPILER_VERSION__ >= 15009000
        #if defined(__TI_EABI__)
            .TI.ramfunc : {} LOAD = BOOT_FLASH_CODE,
                                 RUN = BOOT_RAM_CODE,
                                 LOAD_START(RamfuncsLoadStart),
                                 LOAD_SIZE(RamfuncsLoadSize),
                                 LOAD_END(RamfuncsLoadEnd),
                                 RUN_START(RamfuncsRunStart),
                                 RUN_SIZE(RamfuncsRunSize),
                                 RUN_END(RamfuncsRunEnd),
                                 PAGE = 0, ALIGN(8)
        #else
            .TI.ramfunc : {} LOAD = BOOT_FLASH_CODE,
                             RUN = BOOT_RAM_CODE,
                             LOAD_START(_RamfuncsLoadStart),
                             LOAD_SIZE(_RamfuncsLoadSize),
                             LOAD_END(_RamfuncsLoadEnd),
                             RUN_START(_RamfuncsRunStart),
                             RUN_SIZE(_RamfuncsRunSize),
                             RUN_END(_RamfuncsRunEnd),
                             PAGE = 0, ALIGN(8)
        #endif
    #else
   ramfuncs            : LOAD = BOOT_FLASH_CODE,
                         RUN = BOOT_RAM_CODE,
                         LOAD_START(_RamfuncsLoadStart),
                         LOAD_SIZE(_RamfuncsLoadSize),
                         LOAD_END(_RamfuncsLoadEnd),
                         RUN_START(_RamfuncsRunStart),
                         RUN_SIZE(_RamfuncsRunSize),
                         RUN_END(_RamfuncsRunEnd),
                         PAGE = 0, ALIGN(8)
    #endif

#endif


   /* The following section definitions are required when using the IPC API Drivers */
    GROUP : > CPU1TOCPU2RAM, PAGE = 1
    {
        PUTBUFFER
        PUTWRITEIDX
        GETREADIDX
    }

    GROUP : > CPU2TOCPU1RAM, PAGE = 1
    {
        GETBUFFER :    TYPE = DSECT
        GETWRITEIDX :  TYPE = DSECT
        PUTREADIDX :   TYPE = DSECT
    }

}

/*
//===========================================================================
// End of file.
//===========================================================================
*/
