#include <assert.h>
#include <stdio.h>

#include "boot_flash_service_app.h"
#include "boot_flash_service_app_contract.h"

#define TEST_CONFIRM_ERROR_STATUS ((uint16_t)0x0804U)

BootFlashServicePublishState g_test_publish_state;
BootFlashServiceAppExport g_test_app_export;

static uint16_t g_confirm_status;
static uint16_t g_confirm_call_count;

static uint16_t Test_ConfirmCurrentImage(void)
{
    ++g_confirm_call_count;
    return g_confirm_status;
}

static void SetPublishState(uint16_t valid, uint16_t valid_inverse)
{
    g_test_publish_state.valid = valid;
    g_test_publish_state.valid_inverse = valid_inverse;
    g_confirm_call_count = 0U;
}

static void Test_InvalidPublishState(void)
{
    static const uint16_t states[][2] = {
        {0U, 0U},
        {BOOT_FLASH_SERVICE_PUBLISH_VALID, 0U},
        {0U, BOOT_FLASH_SERVICE_PUBLISH_VALID_INVERSE},
        {0xFFFFU, 0xFFFFU}
    };
    unsigned int index;

    for (index = 0U; index < sizeof(states) / sizeof(states[0]); ++index)
    {
        SetPublishState(states[index][0], states[index][1]);
        assert(BootFlashServiceApp_IsAvailable() == 0U);
        assert(BootFlashServiceApp_ConfirmCurrentImage() ==
               BOOT_FLASH_SERVICE_APP_STATUS_UNAVAILABLE);
        assert(g_confirm_call_count == 0U);
    }
}

static void Test_ConfirmStatusPassThrough(uint16_t status)
{
    SetPublishState(BOOT_FLASH_SERVICE_PUBLISH_VALID,
                    BOOT_FLASH_SERVICE_PUBLISH_VALID_INVERSE);
    g_confirm_status = status;

    assert(BootFlashServiceApp_IsAvailable() == 1U);
    assert(BootFlashServiceApp_ConfirmCurrentImage() == status);
    assert(g_confirm_call_count == 1U);
}

int main(void)
{
    g_test_app_export.confirm_current_image = Test_ConfirmCurrentImage;

    Test_InvalidPublishState();
    Test_ConfirmStatusPassThrough(BOOT_FLASH_SERVICE_APP_STATUS_OK);
    Test_ConfirmStatusPassThrough(TEST_CONFIRM_ERROR_STATUS);

    puts("App flash service tests passed");
    return 0;
}
