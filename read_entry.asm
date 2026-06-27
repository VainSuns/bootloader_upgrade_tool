;***************************************************************
;* TMS320C2000 G3 C/C++ Codegen                               PC v22.6.1.LTS *
;* Date/Time created: Sun Jun 28 02:02:48 2026                 *
;***************************************************************
	.compiler_opts --abi=coffabi --float_support=softlib --hll_source=on --mem_model:code=flat --mem_model:data=large --object_format=coff --silicon_errata_fpu1_workaround=on --silicon_version=28 --symdebug:dwarf --symdebug:dwarf_version=3 
	.asg	XAR2, FP

$C$DW$CU	.dwtag  DW_TAG_compile_unit
	.dwattr $C$DW$CU, DW_AT_name(".\.ti-check\read_entry.c")
	.dwattr $C$DW$CU, DW_AT_producer("TI TMS320C2000 G3 C/C++ Codegen PC v22.6.1.LTS Copyright (c) 1996-2018 Texas Instruments Incorporated")
	.dwattr $C$DW$CU, DW_AT_TI_version(0x01)
	.dwattr $C$DW$CU, DW_AT_comp_dir("D:\Codes\DSP28377D\bootloader_upgrade_tool")
	.global	_g_boot_user_jump_entry
_g_boot_user_jump_entry:	.usect	".ebss",2,1,1
$C$DW$1	.dwtag  DW_TAG_variable
	.dwattr $C$DW$1, DW_AT_name("g_boot_user_jump_entry")
	.dwattr $C$DW$1, DW_AT_TI_symbol_name("_g_boot_user_jump_entry")
	.dwattr $C$DW$1, DW_AT_location[DW_OP_addr _g_boot_user_jump_entry]
	.dwattr $C$DW$1, DW_AT_type(*$C$DW$T$21)
	.dwattr $C$DW$1, DW_AT_external

	.sblock	".ebss"
;	E:\CodeComposerStudio\CCS12.7\ccs\tools\compiler\ti-cgt-c2000_22.6.1.LTS\bin\ac2000.exe -@D:\\Sun\\Temps\\{8A55A3B0-0591-4446-8248-8500B03328FA} 
	.sect	".text"
	.clink
	.global	_read_entry

$C$DW$2	.dwtag  DW_TAG_subprogram
	.dwattr $C$DW$2, DW_AT_name("read_entry")
	.dwattr $C$DW$2, DW_AT_low_pc(_read_entry)
	.dwattr $C$DW$2, DW_AT_high_pc(0x00)
	.dwattr $C$DW$2, DW_AT_TI_symbol_name("_read_entry")
	.dwattr $C$DW$2, DW_AT_external
	.dwattr $C$DW$2, DW_AT_type(*$C$DW$T$19)
	.dwattr $C$DW$2, DW_AT_TI_begin_file(".\.ti-check\read_entry.c")
	.dwattr $C$DW$2, DW_AT_TI_begin_line(0x03)
	.dwattr $C$DW$2, DW_AT_TI_begin_column(0x0a)
	.dwattr $C$DW$2, DW_AT_TI_max_frame_size(-2)
	.dwpsn	file ".\.ti-check\read_entry.c",line 3,column 27,is_stmt,address _read_entry,isa 0

	.dwfde $C$DW$CIE, _read_entry

;***************************************************************
;* FNAME: _read_entry                   FR SIZE:   0           *
;*                                                             *
;* FUNCTION ENVIRONMENT                                        *
;*                                                             *
;* FUNCTION PROPERTIES                                         *
;*                            0 Parameter,  0 Auto,  0 SOE     *
;***************************************************************

_read_entry:
	.dwcfi	cfa_offset, -2
	.dwcfi	save_reg_to_mem, 26, 0
	.dwpsn	file ".\.ti-check\read_entry.c",line 3,column 29,is_stmt,isa 0
;----------------------------------------------------------------------
;   3 | uint32_t read_entry(void) { return g_boot_user_jump_entry; }           
;----------------------------------------------------------------------
        MOVW      DP,#_g_boot_user_jump_entry ; [CPU_ARAU] 
        MOVL      ACC,@_g_boot_user_jump_entry ; [CPU_ALU] |3| 
	.dwpsn	file ".\.ti-check\read_entry.c",line 3,column 60,is_stmt,isa 0
$C$DW$3	.dwtag  DW_TAG_TI_branch
	.dwattr $C$DW$3, DW_AT_low_pc(0x00)
	.dwattr $C$DW$3, DW_AT_TI_return

        LRETR     ; [CPU_ALU] 
        ; return occurs ; [] 
	.dwattr $C$DW$2, DW_AT_TI_end_file(".\.ti-check\read_entry.c")
	.dwattr $C$DW$2, DW_AT_TI_end_line(0x03)
	.dwattr $C$DW$2, DW_AT_TI_end_column(0x3c)
	.dwendentry
	.dwendtag $C$DW$2


;***************************************************************
;* TYPE INFORMATION                                            *
;***************************************************************
$C$DW$T$2	.dwtag  DW_TAG_unspecified_type
	.dwattr $C$DW$T$2, DW_AT_name("void")

$C$DW$T$4	.dwtag  DW_TAG_base_type
	.dwattr $C$DW$T$4, DW_AT_encoding(DW_ATE_boolean)
	.dwattr $C$DW$T$4, DW_AT_name("bool")
	.dwattr $C$DW$T$4, DW_AT_byte_size(0x01)

$C$DW$T$5	.dwtag  DW_TAG_base_type
	.dwattr $C$DW$T$5, DW_AT_encoding(DW_ATE_signed_char)
	.dwattr $C$DW$T$5, DW_AT_name("signed char")
	.dwattr $C$DW$T$5, DW_AT_byte_size(0x01)

$C$DW$T$6	.dwtag  DW_TAG_base_type
	.dwattr $C$DW$T$6, DW_AT_encoding(DW_ATE_unsigned_char)
	.dwattr $C$DW$T$6, DW_AT_name("unsigned char")
	.dwattr $C$DW$T$6, DW_AT_byte_size(0x01)

$C$DW$T$7	.dwtag  DW_TAG_base_type
	.dwattr $C$DW$T$7, DW_AT_encoding(DW_ATE_signed_char)
	.dwattr $C$DW$T$7, DW_AT_name("wchar_t")
	.dwattr $C$DW$T$7, DW_AT_byte_size(0x01)

$C$DW$T$8	.dwtag  DW_TAG_base_type
	.dwattr $C$DW$T$8, DW_AT_encoding(DW_ATE_signed)
	.dwattr $C$DW$T$8, DW_AT_name("short")
	.dwattr $C$DW$T$8, DW_AT_byte_size(0x01)

$C$DW$T$9	.dwtag  DW_TAG_base_type
	.dwattr $C$DW$T$9, DW_AT_encoding(DW_ATE_unsigned)
	.dwattr $C$DW$T$9, DW_AT_name("unsigned short")
	.dwattr $C$DW$T$9, DW_AT_byte_size(0x01)

$C$DW$T$10	.dwtag  DW_TAG_base_type
	.dwattr $C$DW$T$10, DW_AT_encoding(DW_ATE_signed)
	.dwattr $C$DW$T$10, DW_AT_name("int")
	.dwattr $C$DW$T$10, DW_AT_byte_size(0x01)

$C$DW$T$11	.dwtag  DW_TAG_base_type
	.dwattr $C$DW$T$11, DW_AT_encoding(DW_ATE_unsigned)
	.dwattr $C$DW$T$11, DW_AT_name("unsigned int")
	.dwattr $C$DW$T$11, DW_AT_byte_size(0x01)

$C$DW$T$12	.dwtag  DW_TAG_base_type
	.dwattr $C$DW$T$12, DW_AT_encoding(DW_ATE_signed)
	.dwattr $C$DW$T$12, DW_AT_name("long")
	.dwattr $C$DW$T$12, DW_AT_byte_size(0x02)

$C$DW$T$13	.dwtag  DW_TAG_base_type
	.dwattr $C$DW$T$13, DW_AT_encoding(DW_ATE_unsigned)
	.dwattr $C$DW$T$13, DW_AT_name("unsigned long")
	.dwattr $C$DW$T$13, DW_AT_byte_size(0x02)

$C$DW$T$19	.dwtag  DW_TAG_typedef
	.dwattr $C$DW$T$19, DW_AT_name("uint32_t")
	.dwattr $C$DW$T$19, DW_AT_type(*$C$DW$T$13)
	.dwattr $C$DW$T$19, DW_AT_language(DW_LANG_C)

$C$DW$4	.dwtag  DW_TAG_TI_far_type
	.dwattr $C$DW$4, DW_AT_type(*$C$DW$T$19)

$C$DW$T$21	.dwtag  DW_TAG_volatile_type
	.dwattr $C$DW$T$21, DW_AT_type(*$C$DW$4)

$C$DW$T$14	.dwtag  DW_TAG_base_type
	.dwattr $C$DW$T$14, DW_AT_encoding(DW_ATE_signed)
	.dwattr $C$DW$T$14, DW_AT_name("long long")
	.dwattr $C$DW$T$14, DW_AT_byte_size(0x04)

$C$DW$T$15	.dwtag  DW_TAG_base_type
	.dwattr $C$DW$T$15, DW_AT_encoding(DW_ATE_unsigned)
	.dwattr $C$DW$T$15, DW_AT_name("unsigned long long")
	.dwattr $C$DW$T$15, DW_AT_byte_size(0x04)

$C$DW$T$16	.dwtag  DW_TAG_base_type
	.dwattr $C$DW$T$16, DW_AT_encoding(DW_ATE_float)
	.dwattr $C$DW$T$16, DW_AT_name("float")
	.dwattr $C$DW$T$16, DW_AT_byte_size(0x02)

$C$DW$T$17	.dwtag  DW_TAG_base_type
	.dwattr $C$DW$T$17, DW_AT_encoding(DW_ATE_float)
	.dwattr $C$DW$T$17, DW_AT_name("double")
	.dwattr $C$DW$T$17, DW_AT_byte_size(0x02)

$C$DW$T$18	.dwtag  DW_TAG_base_type
	.dwattr $C$DW$T$18, DW_AT_encoding(DW_ATE_float)
	.dwattr $C$DW$T$18, DW_AT_name("long double")
	.dwattr $C$DW$T$18, DW_AT_byte_size(0x04)

	.dwattr $C$DW$CU, DW_AT_language(DW_LANG_C)

;***************************************************************
;* DWARF CIE ENTRIES                                           *
;***************************************************************

$C$DW$CIE	.dwcie 26
	.dwcfi	cfa_register, 20
	.dwcfi	cfa_offset, 0
	.dwcfi	same_value, 28
	.dwcfi	same_value, 6
	.dwcfi	same_value, 7
	.dwcfi	same_value, 8
	.dwcfi	same_value, 9
	.dwcfi	same_value, 10
	.dwcfi	same_value, 11
	.dwendentry

;***************************************************************
;* DWARF REGISTER MAP                                          *
;***************************************************************

$C$DW$5	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$5, DW_AT_name("AL")
	.dwattr $C$DW$5, DW_AT_location[DW_OP_reg0]

$C$DW$6	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$6, DW_AT_name("AH")
	.dwattr $C$DW$6, DW_AT_location[DW_OP_reg1]

$C$DW$7	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$7, DW_AT_name("PL")
	.dwattr $C$DW$7, DW_AT_location[DW_OP_reg2]

$C$DW$8	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$8, DW_AT_name("PH")
	.dwattr $C$DW$8, DW_AT_location[DW_OP_reg3]

$C$DW$9	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$9, DW_AT_name("SP")
	.dwattr $C$DW$9, DW_AT_location[DW_OP_reg20]

$C$DW$10	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$10, DW_AT_name("XT")
	.dwattr $C$DW$10, DW_AT_location[DW_OP_reg21]

$C$DW$11	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$11, DW_AT_name("T")
	.dwattr $C$DW$11, DW_AT_location[DW_OP_reg22]

$C$DW$12	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$12, DW_AT_name("ST0")
	.dwattr $C$DW$12, DW_AT_location[DW_OP_reg23]

$C$DW$13	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$13, DW_AT_name("ST1")
	.dwattr $C$DW$13, DW_AT_location[DW_OP_reg24]

$C$DW$14	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$14, DW_AT_name("PC")
	.dwattr $C$DW$14, DW_AT_location[DW_OP_reg25]

$C$DW$15	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$15, DW_AT_name("RPC")
	.dwattr $C$DW$15, DW_AT_location[DW_OP_reg26]

$C$DW$16	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$16, DW_AT_name("FP")
	.dwattr $C$DW$16, DW_AT_location[DW_OP_reg28]

$C$DW$17	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$17, DW_AT_name("DP")
	.dwattr $C$DW$17, DW_AT_location[DW_OP_reg29]

$C$DW$18	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$18, DW_AT_name("SXM")
	.dwattr $C$DW$18, DW_AT_location[DW_OP_reg30]

$C$DW$19	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$19, DW_AT_name("PM")
	.dwattr $C$DW$19, DW_AT_location[DW_OP_reg31]

$C$DW$20	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$20, DW_AT_name("OVM")
	.dwattr $C$DW$20, DW_AT_location[DW_OP_regx 0x20]

$C$DW$21	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$21, DW_AT_name("PAGE0")
	.dwattr $C$DW$21, DW_AT_location[DW_OP_regx 0x21]

$C$DW$22	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$22, DW_AT_name("AMODE")
	.dwattr $C$DW$22, DW_AT_location[DW_OP_regx 0x22]

$C$DW$23	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$23, DW_AT_name("EALLOW")
	.dwattr $C$DW$23, DW_AT_location[DW_OP_regx 0x4e]

$C$DW$24	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$24, DW_AT_name("INTM")
	.dwattr $C$DW$24, DW_AT_location[DW_OP_regx 0x23]

$C$DW$25	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$25, DW_AT_name("IFR")
	.dwattr $C$DW$25, DW_AT_location[DW_OP_regx 0x24]

$C$DW$26	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$26, DW_AT_name("IER")
	.dwattr $C$DW$26, DW_AT_location[DW_OP_regx 0x25]

$C$DW$27	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$27, DW_AT_name("V")
	.dwattr $C$DW$27, DW_AT_location[DW_OP_regx 0x26]

$C$DW$28	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$28, DW_AT_name("PSEUDOH")
	.dwattr $C$DW$28, DW_AT_location[DW_OP_regx 0x4c]

$C$DW$29	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$29, DW_AT_name("VOL")
	.dwattr $C$DW$29, DW_AT_location[DW_OP_regx 0x4d]

$C$DW$30	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$30, DW_AT_name("AR0")
	.dwattr $C$DW$30, DW_AT_location[DW_OP_reg4]

$C$DW$31	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$31, DW_AT_name("XAR0")
	.dwattr $C$DW$31, DW_AT_location[DW_OP_reg5]

$C$DW$32	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$32, DW_AT_name("AR1")
	.dwattr $C$DW$32, DW_AT_location[DW_OP_reg6]

$C$DW$33	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$33, DW_AT_name("XAR1")
	.dwattr $C$DW$33, DW_AT_location[DW_OP_reg7]

$C$DW$34	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$34, DW_AT_name("AR2")
	.dwattr $C$DW$34, DW_AT_location[DW_OP_reg8]

$C$DW$35	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$35, DW_AT_name("XAR2")
	.dwattr $C$DW$35, DW_AT_location[DW_OP_reg9]

$C$DW$36	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$36, DW_AT_name("AR3")
	.dwattr $C$DW$36, DW_AT_location[DW_OP_reg10]

$C$DW$37	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$37, DW_AT_name("XAR3")
	.dwattr $C$DW$37, DW_AT_location[DW_OP_reg11]

$C$DW$38	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$38, DW_AT_name("AR4")
	.dwattr $C$DW$38, DW_AT_location[DW_OP_reg12]

$C$DW$39	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$39, DW_AT_name("XAR4")
	.dwattr $C$DW$39, DW_AT_location[DW_OP_reg13]

$C$DW$40	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$40, DW_AT_name("AR5")
	.dwattr $C$DW$40, DW_AT_location[DW_OP_reg14]

$C$DW$41	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$41, DW_AT_name("XAR5")
	.dwattr $C$DW$41, DW_AT_location[DW_OP_reg15]

$C$DW$42	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$42, DW_AT_name("AR6")
	.dwattr $C$DW$42, DW_AT_location[DW_OP_reg16]

$C$DW$43	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$43, DW_AT_name("XAR6")
	.dwattr $C$DW$43, DW_AT_location[DW_OP_reg17]

$C$DW$44	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$44, DW_AT_name("AR7")
	.dwattr $C$DW$44, DW_AT_location[DW_OP_reg18]

$C$DW$45	.dwtag  DW_TAG_TI_assign_register
	.dwattr $C$DW$45, DW_AT_name("XAR7")
	.dwattr $C$DW$45, DW_AT_location[DW_OP_reg19]

	.dwendtag $C$DW$CU

