#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "boot_algorithm.h"
#include "boot_flash_port.h"
#include "boot_flash_service_lib.h"
#include "boot_ram_port.h"

#define TEST_BUFFER_WORDS 2048U

typedef struct
{
    BootFlashResult init_result;
    BootFlashResult check_result;
    BootFlashResult erase_result;
    BootFlashResult program_result;
    BootFlashResult verify_result;
    BootFlashErrorInfo error_info;
    uint32_t erase_mask;
    uint32_t last_address;
    uint16_t last_word_count;
    uint16_t init_calls;
    uint16_t check_calls;
    uint16_t erase_calls;
    uint16_t program_calls;
    uint16_t verify_calls;
} FakeFlash;

typedef struct
{
    BootRamResult check_result;
    BootRamResult write_result;
    uint32_t last_address;
    uint16_t last_word_count;
    uint16_t check_calls;
    uint16_t write_calls;
} FakeRam;

static FakeFlash g_flash;
static FakeRam g_ram;
static BootErrorDetail g_service_error;

static void FakeFlash_Reset(void)
{
    (void)memset(&g_flash, 0, sizeof(g_flash));
}

static void FakeRam_Reset(void)
{
    (void)memset(&g_ram, 0, sizeof(g_ram));
}

static void FakeFlash_CopyError(BootFlashErrorInfo *error_info)
{
    if (error_info != NULL)
    {
        *error_info = g_flash.error_info;
    }
}

BootFlashResult BootFlash_Init(BootFlashErrorInfo *error_info)
{
    ++g_flash.init_calls;
    FakeFlash_CopyError(error_info);
    return g_flash.init_result;
}

BootFlashResult BootFlash_CheckAddress(uint32_t address,
                                       uint32_t word_count,
                                       BootFlashOperation operation,
                                       BootFlashErrorInfo *error_info)
{
    (void)operation;
    ++g_flash.check_calls;
    g_flash.last_address = address;
    g_flash.last_word_count = (uint16_t)word_count;
    FakeFlash_CopyError(error_info);
    return g_flash.check_result;
}

BootFlashResult BootFlash_EraseBySectorMask(uint32_t sector_mask,
                                            BootFlashErrorInfo *error_info)
{
    ++g_flash.erase_calls;
    g_flash.erase_mask = sector_mask;
    FakeFlash_CopyError(error_info);
    return g_flash.erase_result;
}

BootFlashResult BootFlash_ProgramBlock(uint32_t address,
                                       const uint16_t *data,
                                       uint16_t word_count,
                                       BootFlashErrorInfo *error_info)
{
    (void)data;
    ++g_flash.program_calls;
    g_flash.last_address = address;
    g_flash.last_word_count = word_count;
    FakeFlash_CopyError(error_info);
    return g_flash.program_result;
}

BootFlashResult BootFlash_VerifyBlock(uint32_t address,
                                      const uint16_t *expected,
                                      uint16_t word_count,
                                      BootFlashErrorInfo *error_info)
{
    (void)expected;
    ++g_flash.verify_calls;
    g_flash.last_address = address;
    g_flash.last_word_count = word_count;
    FakeFlash_CopyError(error_info);
    return g_flash.verify_result;
}

BootRamResult BootRam_CheckAddress(uint32_t address,
                                   uint32_t word_count,
                                   BootRamRegionType region_type,
                                   BootRamErrorInfo *error_info)
{
    (void)region_type;
    (void)error_info;
    ++g_ram.check_calls;
    g_ram.last_address = address;
    g_ram.last_word_count = (uint16_t)word_count;
    return g_ram.check_result;
}

BootRamResult BootRam_WriteBlock(uint32_t address,
                                 const uint16_t *data,
                                 uint16_t word_count,
                                 BootRamRegionType region_type,
                                 BootRamErrorInfo *error_info)
{
    (void)data;
    (void)region_type;
    (void)error_info;
    ++g_ram.write_calls;
    g_ram.last_address = address;
    g_ram.last_word_count = word_count;
    return g_ram.write_result;
}

typedef struct
{
    uint16_t rx[TEST_BUFFER_WORDS];
    size_t rx_count;
    size_t rx_index;
    uint16_t tx[TEST_BUFFER_WORDS];
    size_t tx_count;
} FakeIo;

static uint16_t Fake_GetByte(void *ctx)
{
    FakeIo *io = (FakeIo *)ctx;
    assert(io->rx_index < io->rx_count);
    return io->rx[io->rx_index++];
}

static void Fake_SendByte(void *ctx, uint16_t byte_value)
{
    FakeIo *io = (FakeIo *)ctx;
    assert(io->tx_count < TEST_BUFFER_WORDS);
    io->tx[io->tx_count++] = (uint16_t)(byte_value & 0x00FFU);
}

static uint16_t Fake_GetWord(void *ctx)
{
    uint16_t low = Fake_GetByte(ctx);
    uint16_t high = Fake_GetByte(ctx);
    return (uint16_t)(low | (uint16_t)(high << 8U));
}

static void Fake_SendWord(void *ctx, uint16_t word)
{
    Fake_SendByte(ctx, word & 0x00FFU);
    Fake_SendByte(ctx, (uint16_t)(word >> 8U));
}

static BootIoOps Fake_Ops(FakeIo *io)
{
    BootIoOps ops;
    ops.ctx = io;
    ops.get_byte = Fake_GetByte;
    ops.get_word = Fake_GetWord;
    ops.send_word = Fake_SendWord;
    return ops;
}

static BootDeviceInfo Test_DeviceInfo(void)
{
    BootDeviceInfo info = {0};
    info.device_id = BOOT_DEVICE_F28377D;
    info.cpu_id = BOOT_CPU1;
    info.kernel_ver_major = 1U;
    info.kernel_ver_minor = 2U;
    info.kernel_ver_patch = 3U;
    info.protocol_ver = BOOT_PROTOCOL_VERSION;
    info.feature_flags = BOOT_FEATURE_RUN | BOOT_FEATURE_RESET | BOOT_FEATURE_RAM_LOAD;
    info.max_payload_words = BOOT_PROTOCOL_MAX_PAYLOAD_WORDS;
    info.max_data_words = 248U;
    info.boot_mode = BOOT_MODE_FLASH_KERNEL;
    info.kernel_layout = BOOT_KERNEL_LAYOUT_CORE_RAM_LIB;
    info.identity.revision_id = 0x12345678UL;
    info.identity.uid_unique = 0x9ABCDEF0UL;
    return info;
}

static void AppendByte(FakeIo *io, uint16_t byte_value)
{
    assert(io->rx_count < TEST_BUFFER_WORDS);
    io->rx[io->rx_count++] = (uint16_t)(byte_value & 0x00FFU);
}

static void AppendWord(FakeIo *io, uint16_t word)
{
    AppendByte(io, word & 0x00FFU);
    AppendByte(io, (uint16_t)(word >> 8U));
}

static uint16_t TxWord(const FakeIo *io, size_t word_index)
{
    size_t byte_index = word_index * 2U;
    assert(byte_index + 1U < io->tx_count);
    return (uint16_t)(io->tx[byte_index] | (uint16_t)(io->tx[byte_index + 1U] << 8U));
}

static void AppendRequest(FakeIo *io,
                          uint16_t command,
                          uint16_t sequence,
                          const uint16_t *payload,
                          uint16_t payload_words,
                          uint16_t corrupt_header_crc,
                          uint16_t corrupt_payload_crc)
{
    uint16_t header[9];
    uint16_t index;
    uint16_t crc;

    header[0] = BOOT_PROTOCOL_MAGIC0;
    header[1] = BOOT_PROTOCOL_MAGIC1;
    header[2] = BOOT_PROTOCOL_VERSION;
    header[3] = BOOT_PKT_REQUEST;
    header[4] = command;
    header[5] = sequence;
    header[6] = 0U;
    header[7] = 0U;
    header[8] = payload_words;
    for (index = 0U; index < 9U; ++index)
    {
        AppendWord(io, header[index]);
    }
    crc = BootProtocol_CrcWords(header, 9U);
    AppendWord(io, corrupt_header_crc != 0U ? (uint16_t)(crc ^ 1U) : crc);
    for (index = 0U; index < payload_words; ++index)
    {
        AppendWord(io, payload[index]);
    }
    crc = BootProtocol_CrcWords(payload, payload_words);
    AppendWord(io, corrupt_payload_crc != 0U ? (uint16_t)(crc ^ 1U) : crc);
}

static size_t AssertResponse(const FakeIo *io,
                             size_t offset,
                             uint16_t command,
                             uint16_t sequence,
                             uint16_t packet_type,
                             uint16_t status,
                             uint16_t payload_words)
{
    size_t total_words = (size_t)BOOT_PROTOCOL_HEADER_WORDS + payload_words + 1U;
    uint16_t words[BOOT_PROTOCOL_HEADER_WORDS + BOOT_PROTOCOL_MAX_PAYLOAD_WORDS + 1U];
    size_t index;

    assert((offset + total_words) * 2U <= io->tx_count);
    for (index = 0U; index < total_words; ++index)
    {
        words[index] = TxWord(io, offset + index);
    }
    assert(words[0] == BOOT_PROTOCOL_MAGIC0);
    assert(words[1] == BOOT_PROTOCOL_MAGIC1);
    assert(words[2] == BOOT_PROTOCOL_VERSION);
    assert(words[3] == packet_type);
    assert(words[4] == command);
    assert(words[5] == sequence);
    assert(words[6] == 0U);
    assert(words[7] == status);
    assert(words[8] == payload_words);
    assert(words[9] == BootProtocol_CrcWords(words, 9U));
    assert(words[10U + payload_words] ==
           BootProtocol_CrcWords(&words[10], payload_words));
    return offset + total_words;
}

static BootProtocolFrame RequestFrame(uint16_t command,
                                      const uint16_t *payload,
                                      uint16_t payload_words)
{
    BootProtocolFrame frame = {0};
    frame.protocol_ver = BOOT_PROTOCOL_VERSION;
    frame.packet_type = BOOT_PKT_REQUEST;
    frame.command = command;
    frame.payload_words = payload_words;
    if ((payload != NULL) && (payload_words != 0U))
    {
        (void)memcpy(frame.payload, payload, (size_t)payload_words * sizeof(uint16_t));
    }
    return frame;
}

static void Core_SetLastError(void *ctx, const BootErrorDetail *error)
{
    (void)ctx;
    g_service_error = *error;
}

static uint16_t Core_CheckRamRange(void *ctx, uint32_t address, uint32_t word_count)
{
    (void)ctx;
    (void)address;
    (void)word_count;
    return 1U;
}

static BootCoreServices Test_CoreServices(const BootDeviceInfo *info)
{
    BootCoreServices services;
    services.abi_major = BOOT_SERVICE_ABI_MAJOR;
    services.abi_minor = BOOT_SERVICE_ABI_MINOR;
    services.size = (uint16_t)sizeof(BootCoreServices);
    services.device_info = info;
    services.set_last_error = Core_SetLastError;
    services.check_ram_range = Core_CheckRamRange;
    services.ctx = NULL;
    return services;
}

static void Test_Crc(void)
{
    const uint16_t header[9] = {
        0xA55AU, 0x5AA5U, 0x0001U, 0x0001U, 0x0001U,
        0x0001U, 0x0000U, 0x0000U, 0x0002U
    };
    const uint16_t payload[2] = {0x1234U, 0xABCDU};

    assert(BootProtocol_CrcWords(NULL, 0U) == 0xFFFFU);
    assert(BootProtocol_CrcWords(header, 9U) == 0x8CEBU);
    assert(BootProtocol_CrcWords(payload, 2U) == 0x2B52U);
}

static void AssertDeviceInfoWithPrefix(const uint16_t *prefix,
                                       size_t prefix_bytes,
                                       uint16_t sequence)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;
    size_t index;

    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    for (index = 0U; index < prefix_bytes; ++index)
    {
        AppendByte(&fake, prefix[index]);
    }
    AppendRequest(&fake, BOOT_CMD_GET_DEVICE_INFO, sequence, NULL, 0U, 0U, 0U);

    BootAlgorithm_ProcessOne(&algorithm);
    (void)AssertResponse(&fake, 0U, BOOT_CMD_GET_DEVICE_INFO, sequence,
                         BOOT_PKT_RESPONSE, BOOT_STATUS_OK,
                         BOOT_DEVICE_INFO_WORDS);
    assert(TxWord(&fake, 22U) == 0x5678U);
    assert(TxWord(&fake, 23U) == 0x1234U);
    assert(TxWord(&fake, 24U) == 0xDEF0U);
    assert(TxWord(&fake, 25U) == 0x9ABCU);
}

static void Test_DeviceInfoAndByteResync(void)
{
    static const uint16_t wrong_second_magic[] = {0x5AU, 0x00U};
    static const uint16_t shifted_phase[] = {0xA5U};

    AssertDeviceInfoWithPrefix(NULL, 0U, 1U);
    AssertDeviceInfoWithPrefix(wrong_second_magic, 2U, 2U);
    AssertDeviceInfoWithPrefix(shifted_phase, 1U, 3U);
}

static void Test_CoreWithoutServiceAndRamLoad(void)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;
    const uint16_t erase_payload[3] = {1U, 0U, 0U};
    const uint16_t begin[9] = {BOOT_TARGET_RAM_APP, 1U, 8U, 0U, 0U, 8U, 0U, 0U, 0U};
    const uint16_t data[13] = {0U, 8U, 8U, 0U, 0U, 1U, 2U, 3U, 4U, 5U, 6U, 7U, 8U};
    const uint16_t end[6] = {1U, 0U, 8U, 0U, 0U, 0U};
    size_t offset = 0U;

    FakeRam_Reset();
    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    AppendRequest(&fake, BOOT_CMD_PING, 1U, NULL, 0U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_ERASE, 2U, erase_payload, 3U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_RAM_LOAD_BEGIN, 3U, begin, 9U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_RAM_LOAD_DATA, 4U, data, 13U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_RAM_LOAD_END, 5U, end, 6U, 0U, 0U);

    (void)BootAlgorithm_ProcessOne(&algorithm);
    offset = AssertResponse(&fake, offset, BOOT_CMD_PING, 1U,
                            BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    offset = AssertResponse(&fake, offset, BOOT_CMD_ERASE, 2U,
                            BOOT_PKT_ERROR_RESPONSE,
                            BOOT_STATUS_UNSUPPORTED_FEATURE, 0U);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    offset = AssertResponse(&fake, offset, BOOT_CMD_RAM_LOAD_BEGIN, 3U,
                            BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    offset = AssertResponse(&fake, offset, BOOT_CMD_RAM_LOAD_DATA, 4U,
                            BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    (void)AssertResponse(&fake, offset, BOOT_CMD_RAM_LOAD_END, 5U,
                         BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    assert(g_ram.check_calls == 1U);
    assert(g_ram.write_calls == 1U);
    assert(algorithm.service_image_ready == 1U);
}

static void Test_CoreForwardsToActiveService(void)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;
    const uint16_t erase_payload[3] = {5U, 0U, 0U};

    FakeFlash_Reset();
    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    assert(BootAlgorithm_AttachService(&algorithm, BootFlashServiceLib_GetApi()) == 1U);
    AppendRequest(&fake, BOOT_CMD_ERASE, 1U, erase_payload, 3U, 0U, 0U);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    (void)AssertResponse(&fake, 0U, BOOT_CMD_ERASE, 1U,
                         BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    assert(g_flash.init_calls == 1U);
    assert(g_flash.erase_calls == 1U);
    assert(g_flash.erase_mask == 5UL);
}

static void Test_RunResetAndPendingEntry(void)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;
    uint16_t run[4] = {BOOT_TARGET_FLASH_APP, 0U, 8U, 1U};
    size_t offset = 0U;

    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    AppendRequest(&fake, BOOT_CMD_RUN, 1U, run, 4U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_RESET, 2U, NULL, 0U, 0U, 0U);
    assert(BootAlgorithm_ProcessOne(&algorithm) == BOOT_ALGORITHM_ACTION_RUN_FLASH_APP);
    offset = AssertResponse(&fake, offset, BOOT_CMD_RUN, 1U,
                            BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    assert(BootAlgorithm_GetPendingEntryPoint(&algorithm) == 0x00080000UL);
    assert(BootAlgorithm_ProcessOne(&algorithm) == BOOT_ALGORITHM_ACTION_RESET_DEVICE);
    (void)AssertResponse(&fake, offset, BOOT_CMD_RESET, 2U,
                         BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
}

static void Test_ServiceProgramVerifyValidation(void)
{
    BootDeviceInfo info = Test_DeviceInfo();
    BootCoreServices services = Test_CoreServices(&info);
    const BootServiceApi *api = BootFlashServiceLib_GetApi();
    uint16_t response_payload[BOOT_PROTOCOL_MAX_PAYLOAD_WORDS];
    uint16_t response_words;
    BootErrorDetail error;
    uint16_t begin[9] = {BOOT_TARGET_FLASH_APP, 1U, 8U, 0U, 0U, 8U, 0U, 0U, 0x1234U};
    const uint16_t data[13] = {0U, 8U, 8U, 0U, 0U, 1U, 2U, 3U, 4U, 5U, 6U, 7U, 8U};
    const uint16_t end[6] = {1U, 0U, 8U, 0U, 0U, 0U};
    BootProtocolFrame frame;

    FakeFlash_Reset();
    BootErrorDetail_Clear(&g_service_error);
    assert(api->init(&services) == 1U);

    frame = RequestFrame(BOOT_CMD_PROGRAM_DATA, data, 13U);
    assert(api->handle_command(&frame, response_payload, &response_words, &error) ==
           BOOT_STATUS_MISSING_BEGIN);
    assert(error.operation == BOOT_ERR_OP_PROGRAM);

    frame = RequestFrame(BOOT_CMD_PROGRAM_BEGIN, begin, 9U);
    assert(api->handle_command(&frame, response_payload, &response_words, &error) ==
           BOOT_STATUS_OK);
    frame = RequestFrame(BOOT_CMD_PROGRAM_DATA, data, 13U);
    assert(api->handle_command(&frame, response_payload, &response_words, &error) ==
           BOOT_STATUS_OK);
    frame = RequestFrame(BOOT_CMD_PROGRAM_END, end, 6U);
    assert(api->handle_command(&frame, response_payload, &response_words, &error) ==
           BOOT_STATUS_OK);
    assert(g_flash.program_calls == 1U);

    g_flash.verify_result = BOOT_FLASH_RESULT_FAILED;
    g_flash.error_info.address = 0x00080004UL;
    g_flash.error_info.length_words = 8UL;
    g_flash.error_info.api_status = -7;
    g_flash.error_info.fsm_status = 0x12345678UL;
    frame = RequestFrame(BOOT_CMD_VERIFY_BEGIN, begin, 9U);
    assert(api->handle_command(&frame, response_payload, &response_words, &error) ==
           BOOT_STATUS_OK);
    frame = RequestFrame(BOOT_CMD_VERIFY_DATA, data, 13U);
    assert(api->handle_command(&frame, response_payload, &response_words, &error) ==
           BOOT_STATUS_VERIFY_FAILED);
    assert(error.operation == BOOT_ERR_OP_VERIFY);
    assert(error.stage == BOOT_ERR_STAGE_VERIFY);
    assert(g_service_error.address == 0x00080004UL);
    (void)api->deinit();
}

int main(void)
{
    _Static_assert(BOOT_FLASH_RESULT_INIT_FAILED == 1U,
                   "Flash initialization failure code must stay stable");
    _Static_assert(
        _Generic(&BootFlash_EraseBySectorMask,
                 BootFlashResult (*)(uint32_t, BootFlashErrorInfo *): 1,
                 default: 0),
        "Flash erase must use one uint32 sector mask");

    Test_Crc();
    Test_DeviceInfoAndByteResync();
    Test_CoreWithoutServiceAndRamLoad();
    Test_CoreForwardsToActiveService();
    Test_RunResetAndPendingEntry();
    Test_ServiceProgramVerifyValidation();
    puts("DSP host tests passed");
    return 0;
}
