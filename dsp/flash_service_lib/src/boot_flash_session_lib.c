#include "boot_flash_service_private_lib.h"

void BootFlashService_ResetSession(BootFlashServiceSession *session)
{
    session->operation = BOOT_FLASH_SERVICE_SESSION_NONE;
    session->target = 0U;
    session->expected_packet_count = 0UL;
    session->processed_packet_count = 0UL;
    session->expected_total_words = 0UL;
    session->processed_total_words = 0UL;
    session->expected_block_index = 0UL;
    session->entry_point = 0UL;
}
