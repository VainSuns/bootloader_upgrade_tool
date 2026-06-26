#include "F28x_Project.h"
#include "boot_flash_port.h"
#include "F021_F2837xD_C28x.h"
#include "flash_programming_c28.h"
#include "boot_user_address_limit.h"


uint16_t BootFlash_FindSector(uint32_t index, uint32_t *start_address, uint16_t *size_u32length)
{
    switch (index)
    {
    case 1:
        *start_address = Bzero_SectorA_start;
        *size_u32length = Bzero_16KSector_u32length;
        return 1;
    case 2:
        *start_address = Bzero_SectorB_start;
        *size_u32length = Bzero_16KSector_u32length;
        return 1;
    case 3:
        *start_address = Bzero_SectorC_start;
        *size_u32length = Bzero_16KSector_u32length;
        return 1;
    case 4:
        *start_address = Bzero_SectorD_start;
        *size_u32length = Bzero_16KSector_u32length;
        return 1;
    case 5:
        *start_address = Bzero_SectorE_start;
        *size_u32length = Bzero_64KSector_u32length;
        return 1;
    case 6:
        *start_address = Bzero_SectorF_start;
        *size_u32length = Bzero_64KSector_u32length;
        return 1;
    case 7:
        *start_address = Bzero_SectorG_start;
        *size_u32length = Bzero_64KSector_u32length;
        return 1;
    case 8:
        *start_address = Bzero_SectorH_start;
        *size_u32length = Bzero_64KSector_u32length;
        return 1;
    case 9:
        *start_address = Bzero_SectorI_start;
        *size_u32length = Bzero_64KSector_u32length;
        return 1;
    case 10:
        *start_address = Bzero_SectorJ_start;
        *size_u32length = Bzero_64KSector_u32length;
        return 1;
    case 11:
        *start_address = Bzero_SectorK_start;
        *size_u32length = Bzero_16KSector_u32length;
        return 1;
    case 12:
        *start_address = Bzero_SectorL_start;
        *size_u32length = Bzero_16KSector_u32length;
        return 1;
    case 13:
        *start_address = Bzero_SectorM_start;
        *size_u32length = Bzero_16KSector_u32length;
        return 1;
    case 14:
        *start_address = Bzero_SectorN_start;
        *size_u32length = Bzero_16KSector_u32length;
        return 1;
    default:
        *start_address = 0U;
        *size_u32length = 0U;
        return 0;
    }
}

uint16_t BootFlash_FindSectorByAddress(uint32_t address, uint32_t *start_address, uint16_t *size_u16length)
{
    if((address >= Bzero_SectorA_start) && (address <= Bzero_SectorA_End))
    {
        *start_address = Bzero_SectorA_start;
        *size_u16length = Bzero_SectorA_End - Bzero_SectorA_start;
        return 1;
    }
    else if((address >= Bzero_SectorB_start) && (address <= Bzero_SectorB_End))
    {
        *start_address = Bzero_SectorB_start;
        *size_u16length = Bzero_SectorB_End - Bzero_SectorB_start;
        return 1;
    }
    else if((address >= Bzero_SectorC_start) && (address <= Bzero_SectorC_End))
    {
        *start_address = Bzero_SectorC_start;
        *size_u16length = Bzero_SectorC_End - Bzero_SectorC_start;
        return 1;
    }
    else if((address >= Bzero_SectorD_start) && (address <= Bzero_SectorD_End))
    {
        *start_address = Bzero_SectorD_start;
        *size_u16length = Bzero_SectorD_End - Bzero_SectorD_start;
        return 1;
    }
    else if((address >= Bzero_SectorE_start) && (address <= Bzero_SectorE_End))
    {
        *start_address = Bzero_SectorE_start;
        *size_u16length = Bzero_SectorE_End - Bzero_SectorE_start;
        return 1;
    }
    else if((address >= Bzero_SectorF_start) && (address <= Bzero_SectorF_End))
    {
        *start_address = Bzero_SectorF_start;
        *size_u16length = Bzero_SectorF_End - Bzero_SectorF_start;
        return 1;
    }
    else if((address >= Bzero_SectorG_start) && (address <= Bzero_SectorG_End))
    {
        *start_address = Bzero_SectorG_start;
        *size_u16length = Bzero_SectorG_End - Bzero_SectorG_start;
        return 1;
    }
    else if((address >= Bzero_SectorH_start) && (address <= Bzero_SectorH_End))
    {
        *start_address = Bzero_SectorH_start;
        *size_u16length = Bzero_SectorH_End - Bzero_SectorH_start;
        return 1;
    }
    else if((address >= Bzero_SectorI_start) && (address <= Bzero_SectorI_End))
    {
        *start_address = Bzero_SectorI_start;
        *size_u16length = Bzero_SectorI_End - Bzero_SectorI_start;
        return 1;
    }
    else if((address >= Bzero_SectorJ_start) && (address <= Bzero_SectorJ_End))
    {
        *start_address = Bzero_SectorJ_start;
        *size_u16length = Bzero_SectorJ_End - Bzero_SectorJ_start;
        return 1;
    }
    else if((address >= Bzero_SectorK_start) && (address <= Bzero_SectorK_End))
    {
        *start_address = Bzero_SectorK_start;
        *size_u16length = Bzero_SectorK_End - Bzero_SectorK_start;
        return 1;
    }
    else if((address >= Bzero_SectorL_start) && (address <= Bzero_SectorL_End))
    {
        *start_address = Bzero_SectorL_start;
        *size_u16length = Bzero_SectorL_End - Bzero_SectorL_start;
        return 1;
    }
    else if((address >= Bzero_SectorM_start) && (address <= Bzero_SectorM_End))
    {
        *start_address = Bzero_SectorM_start;
        *size_u16length = Bzero_SectorM_End - Bzero_SectorM_start;
        return 1;
    }
    else if((address >= Bzero_SectorN_start) && (address <= Bzero_SectorN_End))
    {
        *start_address = Bzero_SectorN_start;
        *size_u16length = Bzero_SectorN_End - Bzero_SectorN_start;
        return 1;
    }
    else
    {
        *start_address = 0;
        *size_u16length = 0;
        return 0;
    }
}

BootFlashResult BootFlash_Init(BootFlashErrorInfo *error_info)
{
    Fapi_StatusType oReturnCheck;
    
    
    EALLOW;
    #ifdef CPU1
        while (FlashPumpSemaphoreRegs.PUMPREQUEST.bit.PUMP_OWNERSHIP != 0x2)
        {
            FlashPumpSemaphoreRegs.PUMPREQUEST.all = IPC_PUMP_KEY | 0x2;
        }
    #elif defined(CPU2)
        while (FlashPumpSemaphoreRegs.PUMPREQUEST.bit.PUMP_OWNERSHIP != 0x1)
        {
            FlashPumpSemaphoreRegs.PUMPREQUEST.all = IPC_PUMP_KEY | 0x1;
        }
    #endif

    #ifdef CPU_FRQ_200MHZ
    oReturnCheck = Fapi_initializeAPI(F021_CPU0_BASE_ADDRESS, 200);
    #elif defined(CPU_FRQ_150MHZ)
    oReturnCheck = Fapi_initializeAPI(F021_CPU0_BASE_ADDRESS, 150);
    #else
    oReturnCheck = Fapi_initializeAPI(F021_CPU0_BASE_ADDRESS, 100);
    #endif
    if(oReturnCheck != Fapi_Status_Success)
    {
        error_info->operation = BOOT_FLASH_OP_NONE;
        error_info->address = 0U;
        error_info->length_words = 0U;
        error_info->api_status = (int32_t)oReturnCheck;
        error_info->fsm_status = Fapi_getFsmStatus();
        EDIS;
        return BOOT_FLASH_RESULT_INIT_FAILED;
    }

    oReturnCheck = Fapi_setActiveFlashBank(Fapi_FlashBank0);
    if(oReturnCheck != Fapi_Status_Success)
    {
        error_info->operation = BOOT_FLASH_OP_NONE;
        error_info->address = 0U;
        error_info->length_words = 0U;
        error_info->api_status = (int32_t)oReturnCheck;
        error_info->fsm_status = Fapi_getFsmStatus();
        EDIS;
        return BOOT_FLASH_RESULT_INIT_FAILED;
    }

    EDIS;
    return BOOT_FLASH_RESULT_OK;
}

BootFlashResult BootFlash_CheckAddress(uint32_t address,
                                       uint32_t word_count,
                                       BootFlashOperation operation,
                                       BootFlashErrorInfo *error_info)
{
    uint16_t size_u16length;
    uint32_t start_address;
    BootFlashResult result = BOOT_FLASH_RESULT_OK;

    do{
        if (BootFlash_FindSectorByAddress(address, &start_address, &size_u16length) != 1)
        {
            result = BOOT_FLASH_RESULT_BAD_ADDRESS;
            break;
        }

        if (address + word_count * sizeof(uint16_t) > start_address + size_u16length)
        {
            result = BOOT_FLASH_RESULT_BAD_ADDRESS;
            break;
        }

        if ((address < BOOT_USER_APP_FLASH_START) || (address + word_count > BOOT_USER_APP_FLASH_END))
        {
            result = BOOT_FLASH_RESULT_BAD_ADDRESS;
            break;
        }

        if (operation == BOOT_FLASH_OP_PROGRAM)
        {
            if ((address % 8UL) != 0UL || (word_count % 8UL) != 0UL)
            {
                result = BOOT_FLASH_RESULT_BAD_ADDRESS;
                break;
            }
        }
    }while (0);
    
    if (result != BOOT_FLASH_RESULT_OK)
    {
        error_info->operation = operation;
        error_info->address = address;
        error_info->length_words = word_count;
        error_info->api_status = -1;
        error_info->fsm_status = (uint32_t)-1;
    }

    return result;
}

BootFlashResult BootFlash_EraseBySectorMask(uint32_t sector_mask,
                                            BootFlashErrorInfo *error_info)
{
    uint32_t start_address;
    uint16_t sector_size;
    Fapi_FlashStatusWordType flash_statusWord;
    Fapi_StatusType oReturnCheck;
    Fapi_FlashStatusType oFlashStatus;
    uint32_t i;

    if (sector_mask & ~BOOT_USER_ALLOWED_ERASE_MASK)
    {
        error_info->operation = BOOT_FLASH_OP_ERASE;
        error_info->address = 0U;
        error_info->length_words = 0U;
        error_info->api_status = -1;
        error_info->fsm_status = (uint32_t)-1;
        return BOOT_FLASH_RESULT_BAD_ADDRESS;
    }
    
    EALLOW;
    for (i = 0; i < 32; i++)
    {
        if ((sector_mask & (1U << i)) != 0U)
        {
            if (BootFlash_FindSector(i + 1, &start_address, &sector_size) == 0U)
            {
                error_info->operation = BOOT_FLASH_OP_ERASE;
                error_info->address = start_address;
                error_info->length_words = sector_size;
                error_info->api_status = -1;
                error_info->fsm_status = (uint32_t)-1;
                EDIS;
                return BOOT_FLASH_RESULT_BAD_ADDRESS;
            }

            oReturnCheck = Fapi_issueAsyncCommandWithAddress(Fapi_EraseSector, (uint32 *)start_address);
            oFlashStatus = Fapi_getFsmStatus();
            if (oReturnCheck != Fapi_Status_Success)
            {
                error_info->operation = BOOT_FLASH_OP_ERASE;
                error_info->address = start_address;
                error_info->length_words = sector_size;
                error_info->api_status = (int32_t)oReturnCheck;
                error_info->fsm_status = oFlashStatus;
                EDIS;
                return BOOT_FLASH_RESULT_FAILED;
            }

            while(Fapi_checkFsmForReady() == Fapi_Status_FsmBusy);
            oReturnCheck = Fapi_doBlankCheck((uint32 *)start_address,
                                                             sector_size,
                                                             &flash_statusWord);
            oFlashStatus = Fapi_getFsmStatus();
            if (oReturnCheck != Fapi_Status_Success || oFlashStatus != 0)
            {
                error_info->operation = BOOT_FLASH_OP_ERASE;
                error_info->address = flash_statusWord.au32StatusWord[0];
                error_info->length_words = sector_size;
                error_info->api_status = (int32_t)oReturnCheck;
                error_info->fsm_status = oFlashStatus;
                EDIS;
                return BOOT_FLASH_RESULT_FAILED;
            }
        }
    }
    EDIS;
    return BOOT_FLASH_RESULT_OK;
}

BootFlashResult BootFlash_Program_128Bits(uint32_t address,
                                       const uint16_t *data,
                                       BootFlashErrorInfo *error_info)
{
    Fapi_StatusType oReturnCheck;
    Fapi_FlashStatusType oFlashStatus;
    EALLOW;
    oReturnCheck = Fapi_issueProgrammingCommand((uint32 *)address,
                                                (uint16*)data,
                                                           8,
                                                           0,
                                                           0,
                                                           Fapi_AutoEccGeneration);
    while(Fapi_checkFsmForReady() == Fapi_Status_FsmBusy);
    oFlashStatus = Fapi_getFsmStatus();
    EDIS;
    if (oReturnCheck != Fapi_Status_Success || oFlashStatus != 0)
    {
        error_info->operation = BOOT_FLASH_OP_PROGRAM;
        error_info->address = address;
        error_info->length_words = 8;
        error_info->api_status = (int32_t)oReturnCheck;
        error_info->fsm_status = oFlashStatus;
        return BOOT_FLASH_RESULT_FAILED;
    }

    return BOOT_FLASH_RESULT_OK;
}

BootFlashResult BootFlash_ProgramBlock(uint32_t address,
                                       const uint16_t *data,
                                       uint16_t word_count,
                                       BootFlashErrorInfo *error_info)
{
    uint16_t i;
    for (i = 0; i < word_count; i += 8)
    {
        BootFlashResult result = BootFlash_Program_128Bits(address + i, data + i, error_info);
        if (result != BOOT_FLASH_RESULT_OK)
        {
            return result;
        }
    }
    
    return BOOT_FLASH_RESULT_OK;
}

BootFlashResult BootFlash_VerifyBlock(uint32_t address,
                                      const uint16_t *expected,
                                      uint16_t word_count,
                                      BootFlashErrorInfo *error_info)
{
    Fapi_StatusType oReturnCheck;
    Fapi_FlashStatusWordType oFlashStatusWord;
    Fapi_FlashStatusType oFlashStatus;

    if ((address % 8UL) != 0UL || (word_count % 8UL) != 0UL)
    {
        error_info->operation = BOOT_FLASH_OP_VERIFY;
        error_info->address = address;
        error_info->length_words = word_count;
        error_info->api_status = -1;
        error_info->fsm_status = (uint32_t)-1;
        return BOOT_FLASH_RESULT_BAD_ADDRESS;
    }

    EALLOW;

    while(Fapi_checkFsmForReady() == Fapi_Status_FsmBusy);

    oReturnCheck = Fapi_doVerify((uint32 *)address,
                                word_count >> 1,
                                (uint32 *)expected,
                                &oFlashStatusWord);

    oFlashStatus = Fapi_getFsmStatus();
    EDIS;
    if (oReturnCheck != Fapi_Status_Success || oFlashStatus != 0)
    {
        error_info->operation = BOOT_FLASH_OP_VERIFY;
        error_info->address = oFlashStatusWord.au32StatusWord[0];
        error_info->length_words = word_count;
        error_info->api_status = (int32_t)oReturnCheck;
        error_info->fsm_status = oFlashStatus;
        return BOOT_FLASH_RESULT_FAILED;
    }
    return BOOT_FLASH_RESULT_OK;
}
