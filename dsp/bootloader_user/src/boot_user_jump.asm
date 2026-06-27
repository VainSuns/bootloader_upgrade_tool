        .sect   ".text"
        .global _BootUser_JumpToEntryAsm
        .ref    _g_boot_user_jump_entry

_BootUser_JumpToEntryAsm:
        MOVW    DP, #_g_boot_user_jump_entry
        MOVL    XAR7, @_g_boot_user_jump_entry
        LB      *XAR7
