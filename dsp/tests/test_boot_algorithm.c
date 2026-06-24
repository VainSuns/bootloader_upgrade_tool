#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "boot_algorithm.h"
#include "boot_flash_port.h"

_Static_assert(BOOT_FLASH_RESULT_INIT_FAILED == 1U,
               "Flash initialization failure code must stay stable");
_Static_assert(
    _Generic(&BootFlash_EraseBySectorMask,
             BootFlashResult (*)(uint32_t, BootFlashErrorInfo *): 1,
             default: 0),
    "Flash erase must use one uint32 sector mask");

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

static FakeFlash g_flash;

static void FakeFlash_Reset(void)
{
    (void)memset(&g_flash, 0, sizeof(g_flash));
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
    info.feature_flags = BOOT_FEATURE_RUN | BOOT_FEATURE_RESET;
    info.max_payload_words = BOOT_PROTOCOL_MAX_PAYLOAD_WORDS;
    info.max_data_words = 248U;
    info.boot_mode = BOOT_MODE_FLASH_KERNEL;
    info.kernel_layout = BOOT_KERNEL_LAYOUT_MONOLITHIC;
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
    (void)AssertResponse(&fake,
                         0U,
                         BOOT_CMD_GET_DEVICE_INFO,
                         sequence,
                         BOOT_PKT_RESPONSE,
                         BOOT_STATUS_OK,
                         BOOT_DEVICE_INFO_WORDS);
    assert(TxWord(&fake, 10U) == BOOT_DEVICE_F28377D);
    assert(TxWord(&fake, 11U) == BOOT_CPU1);
    assert(TxWord(&fake, 15U) == BOOT_PROTOCOL_VERSION);
    assert(TxWord(&fake, 18U) == BOOT_PROTOCOL_MAX_PAYLOAD_WORDS);
    assert(TxWord(&fake, 19U) == 248U);
    assert(TxWord(&fake, 22U) == 0x5678U);
    assert(TxWord(&fake, 23U) == 0x1234U);
    assert(TxWord(&fake, 24U) == 0xDEF0U);
    assert(TxWord(&fake, 25U) == 0x9ABCU);
}

static void Test_DeviceInfoAndByteResync(void)
{
    static const uint16_t stale_zero[] = {0x00U};
    static const uint16_t stale_autobaud[] = {0x41U, 0x41U, 0x41U};
    static const uint16_t wrong_second_magic[] = {0x5AU, 0x00U};
    static const uint16_t shifted_phase[] = {0xA5U};

    AssertDeviceInfoWithPrefix(NULL, 0U, 1U);
    AssertDeviceInfoWithPrefix(stale_zero, 1U, 2U);
    AssertDeviceInfoWithPrefix(stale_autobaud, 3U, 3U);
    AssertDeviceInfoWithPrefix(wrong_second_magic, 2U, 4U);
    AssertDeviceInfoWithPrefix(shifted_phase, 1U, 5U);
}

static void Test_BadHeaderCrcResync(void)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;

    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    AppendRequest(&fake, BOOT_CMD_PING, 6U, NULL, 0U, 1U, 0U);
    AppendRequest(&fake, BOOT_CMD_GET_DEVICE_INFO, 7U, NULL, 0U, 0U, 0U);

    BootAlgorithm_ProcessOne(&algorithm);
    (void)AssertResponse(&fake,
                         0U,
                         BOOT_CMD_GET_DEVICE_INFO,
                         7U,
                         BOOT_PKT_RESPONSE,
                         BOOT_STATUS_OK,
                         BOOT_DEVICE_INFO_WORDS);
}

static void TestErrorsAndLastError(void)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;
    size_t offset;

    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    AppendRequest(&fake, BOOT_CMD_PING, 1U, NULL, 0U, 0U, 1U);
    AppendRequest(&fake, BOOT_CMD_RAM_LOAD_BEGIN, 2U, NULL, 0U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_GET_LAST_ERROR, 3U, NULL, 0U, 0U, 0U);

    BootAlgorithm_ProcessOne(&algorithm);
    BootAlgorithm_ProcessOne(&algorithm);
    BootAlgorithm_ProcessOne(&algorithm);

    offset = AssertResponse(&fake,
                            0U,
                            BOOT_CMD_PING,
                            1U,
                            BOOT_PKT_ERROR_RESPONSE,
                            BOOT_STATUS_BAD_PAYLOAD_CRC,
                            0U);
    offset = AssertResponse(&fake,
                            offset,
                            BOOT_CMD_RAM_LOAD_BEGIN,
                            2U,
                            BOOT_PKT_ERROR_RESPONSE,
                            BOOT_STATUS_UNSUPPORTED_COMMAND,
                            0U);
    (void)AssertResponse(&fake,
                         offset,
                         BOOT_CMD_GET_LAST_ERROR,
                         3U,
                         BOOT_PKT_RESPONSE,
                         BOOT_STATUS_OK,
                         BOOT_ERROR_DETAIL_WORDS);
    assert(TxWord(&fake, offset + 10U) == BOOT_ERR_OP_NONE);
    assert(TxWord(&fake, offset + 11U) == BOOT_ERR_STAGE_NONE);
    assert(algorithm.last_error.operation == BOOT_ERR_OP_NONE);
    assert(algorithm.last_error.stage == BOOT_ERR_STAGE_NONE);
}

static void TestInitValidation(void)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;

    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    info.max_data_words = 247U;
    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 0U);
    info.max_data_words = 256U;
    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 0U);
}

static void TestEraseCommands(void)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;
    const uint16_t erase_payload[3] = {0x0005U, 0x0000U, 0x0000U};
    size_t offset;

    FakeFlash_Reset();
    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    AppendRequest(&fake, BOOT_CMD_ERASE, 1U, erase_payload, 3U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_ERASE, 2U, erase_payload, 2U, 0U, 0U);

    assert(BootAlgorithm_ProcessOne(&algorithm) == BOOT_ALGORITHM_ACTION_NONE);
    assert(g_flash.init_calls == 1U);
    assert(g_flash.erase_calls == 1U);
    assert(g_flash.erase_mask == 5UL);
    offset = AssertResponse(&fake, 0U, BOOT_CMD_ERASE, 1U,
                            BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);

    assert(BootAlgorithm_ProcessOne(&algorithm) == BOOT_ALGORITHM_ACTION_NONE);
    (void)AssertResponse(&fake, offset, BOOT_CMD_ERASE, 2U,
                         BOOT_PKT_ERROR_RESPONSE,
                         BOOT_STATUS_BAD_PAYLOAD_LENGTH, 0U);
}

static void TestProgramSessionValidation(void)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;
    uint16_t begin[9] = {BOOT_TARGET_FLASH_APP, 1U, 8U, 0U,
                         0U, 8U, 0U, 0U, 0U};
    const uint16_t data[13] = {0U, 8U, 8U, 0U, 0U,
                               1U, 2U, 3U, 4U, 5U, 6U, 7U, 8U};
    uint16_t bad_count[12] = {0U, 8U, 7U, 0U, 0U,
                              1U, 2U, 3U, 4U, 5U, 6U, 7U};
    uint16_t wrong_index[13];
    const uint16_t bad_end[6] = {1U, 0U, 7U, 0U, 0U, 0U};
    size_t offset = 0U;

    (void)memcpy(wrong_index, data, sizeof(data));
    wrong_index[3] = 1U;
    FakeFlash_Reset();
    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);

    AppendRequest(&fake, BOOT_CMD_PROGRAM_DATA, 1U, data, 13U, 0U, 0U);
    begin[0] = BOOT_TARGET_RAM_APP;
    AppendRequest(&fake, BOOT_CMD_PROGRAM_BEGIN, 2U, begin, 9U, 0U, 0U);
    begin[0] = BOOT_TARGET_FLASH_APP;
    AppendRequest(&fake, BOOT_CMD_PROGRAM_BEGIN, 3U, begin, 9U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_PROGRAM_DATA, 4U, bad_count, 12U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_PROGRAM_BEGIN, 5U, begin, 9U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_PROGRAM_DATA, 6U, wrong_index, 13U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_PROGRAM_BEGIN, 7U, begin, 9U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_PROGRAM_DATA, 8U, data, 13U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_PROGRAM_END, 9U, bad_end, 6U, 0U, 0U);

#define PROCESS_AND_ASSERT(command_, sequence_, packet_, status_) \
    do { \
        assert(BootAlgorithm_ProcessOne(&algorithm) == BOOT_ALGORITHM_ACTION_NONE); \
        offset = AssertResponse(&fake, offset, command_, sequence_, packet_, status_, 0U); \
    } while (0)
    PROCESS_AND_ASSERT(BOOT_CMD_PROGRAM_DATA, 1U, BOOT_PKT_ERROR_RESPONSE,
                       BOOT_STATUS_MISSING_BEGIN);
    PROCESS_AND_ASSERT(BOOT_CMD_PROGRAM_BEGIN, 2U, BOOT_PKT_ERROR_RESPONSE,
                       BOOT_STATUS_TARGET_MISMATCH);
    PROCESS_AND_ASSERT(BOOT_CMD_PROGRAM_BEGIN, 3U, BOOT_PKT_RESPONSE,
                       BOOT_STATUS_OK);
    PROCESS_AND_ASSERT(BOOT_CMD_PROGRAM_DATA, 4U, BOOT_PKT_ERROR_RESPONSE,
                       BOOT_STATUS_BAD_WORD_COUNT);
    PROCESS_AND_ASSERT(BOOT_CMD_PROGRAM_BEGIN, 5U, BOOT_PKT_RESPONSE,
                       BOOT_STATUS_OK);
    PROCESS_AND_ASSERT(BOOT_CMD_PROGRAM_DATA, 6U, BOOT_PKT_ERROR_RESPONSE,
                       BOOT_STATUS_BLOCK_INDEX_ERROR);
    PROCESS_AND_ASSERT(BOOT_CMD_PROGRAM_BEGIN, 7U, BOOT_PKT_RESPONSE,
                       BOOT_STATUS_OK);
    PROCESS_AND_ASSERT(BOOT_CMD_PROGRAM_DATA, 8U, BOOT_PKT_RESPONSE,
                       BOOT_STATUS_OK);
    PROCESS_AND_ASSERT(BOOT_CMD_PROGRAM_END, 9U, BOOT_PKT_ERROR_RESPONSE,
                       BOOT_STATUS_TOTAL_COUNT_MISMATCH);
#undef PROCESS_AND_ASSERT
    assert(g_flash.program_calls == 1U);
}

static void TestVerifySessionAndFlashError(void)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;
    const uint16_t begin[9] = {BOOT_TARGET_FLASH_APP, 1U, 8U, 0U,
                               0U, 8U, 0U, 0U, 0U};
    const uint16_t data[13] = {0U, 8U, 8U, 0U, 0U,
                               1U, 2U, 3U, 4U, 5U, 6U, 7U, 8U};
    const uint16_t end[6] = {1U, 0U, 8U, 0U, 0U, 0U};
    size_t offset = 0U;

    FakeFlash_Reset();
    g_flash.verify_result = BOOT_FLASH_RESULT_FAILED;
    g_flash.error_info.address = 0x00080004UL;
    g_flash.error_info.length_words = 8UL;
    g_flash.error_info.api_status = -7;
    g_flash.error_info.fsm_status = 0x12345678UL;
    g_flash.error_info.extra = 0xAABBCCDDUL;
    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    AppendRequest(&fake, BOOT_CMD_VERIFY_DATA, 1U, data, 13U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_VERIFY_BEGIN, 2U, begin, 9U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_VERIFY_DATA, 3U, data, 13U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_GET_LAST_ERROR, 4U, NULL, 0U, 0U, 0U);

    assert(BootAlgorithm_ProcessOne(&algorithm) == BOOT_ALGORITHM_ACTION_NONE);
    offset = AssertResponse(&fake, offset, BOOT_CMD_VERIFY_DATA, 1U,
                            BOOT_PKT_ERROR_RESPONSE,
                            BOOT_STATUS_MISSING_BEGIN, 0U);
    assert(BootAlgorithm_ProcessOne(&algorithm) == BOOT_ALGORITHM_ACTION_NONE);
    offset = AssertResponse(&fake, offset, BOOT_CMD_VERIFY_BEGIN, 2U,
                            BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    assert(BootAlgorithm_ProcessOne(&algorithm) == BOOT_ALGORITHM_ACTION_NONE);
    offset = AssertResponse(&fake, offset, BOOT_CMD_VERIFY_DATA, 3U,
                            BOOT_PKT_ERROR_RESPONSE,
                            BOOT_STATUS_VERIFY_FAILED, 0U);
    assert(BootAlgorithm_ProcessOne(&algorithm) == BOOT_ALGORITHM_ACTION_NONE);
    (void)AssertResponse(&fake, offset, BOOT_CMD_GET_LAST_ERROR, 4U,
                         BOOT_PKT_RESPONSE, BOOT_STATUS_OK,
                         BOOT_ERROR_DETAIL_WORDS);
    assert(algorithm.last_error.operation == BOOT_ERR_OP_VERIFY);
    assert(algorithm.last_error.stage == BOOT_ERR_STAGE_VERIFY);
    assert(algorithm.last_error.address == 0x00080004UL);
    assert(algorithm.last_error.fsm_status == 0x12345678UL);

    FakeFlash_Reset();
    fake = (FakeIo){0};
    ops = Fake_Ops(&fake);
    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    AppendRequest(&fake, BOOT_CMD_VERIFY_BEGIN, 5U, begin, 9U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_VERIFY_DATA, 6U, data, 13U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_VERIFY_END, 7U, end, 6U, 0U, 0U);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    assert(g_flash.verify_calls == 1U);
    assert(algorithm.verify_succeeded == 1U);
}

static void TestRunAndResetActions(void)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;
    uint16_t run[4] = {BOOT_TARGET_RAM_APP, 0U, 8U, 0U};
    const uint16_t reset_payload[1] = {1U};
    size_t offset = 0U;

    FakeFlash_Reset();
    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    AppendRequest(&fake, BOOT_CMD_RUN, 1U, run, 4U, 0U, 0U);
    run[0] = BOOT_TARGET_FLASH_APP;
    run[1] = 2U;
    AppendRequest(&fake, BOOT_CMD_RUN, 2U, run, 4U, 0U, 0U);
    run[1] = 0U;
    AppendRequest(&fake, BOOT_CMD_RUN, 3U, run, 4U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_RUN, 4U, run, 4U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_RESET, 5U, reset_payload, 1U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_RESET, 6U, NULL, 0U, 0U, 0U);

    assert(BootAlgorithm_ProcessOne(&algorithm) == BOOT_ALGORITHM_ACTION_NONE);
    offset = AssertResponse(&fake, offset, BOOT_CMD_RUN, 1U,
                            BOOT_PKT_ERROR_RESPONSE,
                            BOOT_STATUS_TARGET_MISMATCH, 0U);
    assert(BootAlgorithm_ProcessOne(&algorithm) == BOOT_ALGORITHM_ACTION_NONE);
    offset = AssertResponse(&fake, offset, BOOT_CMD_RUN, 2U,
                            BOOT_PKT_ERROR_RESPONSE,
                            BOOT_STATUS_BAD_ALIGNMENT, 0U);
    algorithm.flash_modified = 1U;
    assert(BootAlgorithm_ProcessOne(&algorithm) == BOOT_ALGORITHM_ACTION_NONE);
    offset = AssertResponse(&fake, offset, BOOT_CMD_RUN, 3U,
                            BOOT_PKT_ERROR_RESPONSE,
                            BOOT_STATUS_INVALID_STATE, 0U);
    algorithm.verify_succeeded = 1U;
    assert(BootAlgorithm_ProcessOne(&algorithm) ==
           BOOT_ALGORITHM_ACTION_RUN_FLASH_APP);
    offset = AssertResponse(&fake, offset, BOOT_CMD_RUN, 4U,
                            BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    assert(BootAlgorithm_ProcessOne(&algorithm) == BOOT_ALGORITHM_ACTION_NONE);
    offset = AssertResponse(&fake, offset, BOOT_CMD_RESET, 5U,
                            BOOT_PKT_ERROR_RESPONSE,
                            BOOT_STATUS_BAD_PAYLOAD_LENGTH, 0U);
    assert(BootAlgorithm_ProcessOne(&algorithm) ==
           BOOT_ALGORITHM_ACTION_RESET_DEVICE);
    (void)AssertResponse(&fake, offset, BOOT_CMD_RESET, 6U,
                         BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
}

int main(void)
{
    Test_Crc();
    Test_DeviceInfoAndByteResync();
    Test_BadHeaderCrcResync();
    TestErrorsAndLastError();
    TestInitValidation();
    TestEraseCommands();
    TestProgramSessionValidation();
    TestVerifySessionAndFlashError();
    TestRunAndResetActions();
    puts("DSP host tests passed");
    return 0;
}
