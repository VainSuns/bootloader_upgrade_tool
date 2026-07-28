#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "boot_algorithm.h"
#include "boot_crc32.h"
#include "boot_flash_port.h"
#include "boot_flash_service_lib.h"
#include "boot_metadata.h"
#include "boot_ram_port.h"
#include "boot_user_config.h"

#define TEST_BUFFER_WORDS 2048U
#define TEST_SERVICE_WORDS 0x0100U
#define TEST_IMMUTABLE_OFFSET 0x0080U

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
    uint16_t metadata_program_calls;
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
static uint16_t g_metadata[BOOT_METADATA_SLOT_A_WORDS];
static uint16_t g_service_words[TEST_SERVICE_WORDS];
static uint32_t g_publish_write_addresses[8];
static uint16_t g_publish_write_values[8];
static uint16_t g_publish_write_count;
static uint16_t g_fail_boot_init;
static uint16_t g_boot_init_calls;
static uint16_t g_expect_invalid_publish_on_ram_write;
static uint32_t g_memory_read_addresses[8];
static uint16_t g_memory_read_calls;
static const uint32_t g_service_boot_init_address = 0x00013090UL;
static const uint32_t g_service_handler_address = 0x000130A0UL;
static const uint32_t g_oversize_handler_address = 0x000130B0UL;

static uint16_t OversizeService_HandleCommand(const BootProtocolFrame *request,
                                              uint16_t *response_payload,
                                              uint16_t *response_payload_words,
                                              BootErrorDetail *error);

static uint16_t Test_ServiceBootInit(uint16_t device_id,
                                     uint16_t cpu_id,
                                     uint16_t max_data_words)
{
    ++g_boot_init_calls;
    return (g_fail_boot_init != 0U) ? BOOT_STATUS_INVALID_STATE :
           BootFlashService_BootInit(device_id, cpu_id, max_data_words);
}

uint16_t Test_ReadFlashWord(uint32_t address)
{
    if ((address >= BOOT_METADATA_SLOT_A_START) &&
        (address < (BOOT_METADATA_SLOT_A_START + BOOT_METADATA_SLOT_A_WORDS)))
    {
        return g_metadata[address - BOOT_METADATA_SLOT_A_START];
    }
    return 0xFFFFU;
}

static uint16_t Test_MemoryValue(uint32_t address)
{
    return (uint16_t)((address ^ (address >> 16U) ^ 0x5AA5UL) & 0xFFFFUL);
}

uint16_t Test_ReadMemoryWord(uint32_t address)
{
    assert(g_memory_read_calls < 8U);
    g_memory_read_addresses[g_memory_read_calls++] = address;
    return Test_MemoryValue(address);
}

uint16_t Test_ServiceReadWord(uint32_t address)
{
    uint32_t offset = address - BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS;
    assert(address >= BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS);
    assert(offset < TEST_SERVICE_WORDS);
    return g_service_words[offset];
}

void Test_ServiceWriteWord(uint32_t address, uint16_t value)
{
    uint32_t offset = address - BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS;
    assert(offset < TEST_SERVICE_WORDS);
    assert(g_publish_write_count < 8U);
    g_publish_write_addresses[g_publish_write_count] = address;
    g_publish_write_values[g_publish_write_count] = value;
    ++g_publish_write_count;
    g_service_words[offset] = value;
}

BootFlashServiceBootInitFn Test_ServiceBootInitFromAddress(uint32_t address)
{
    return (address == g_service_boot_init_address) ? Test_ServiceBootInit : NULL;
}

BootFlashServiceHandleCommandFn Test_ServiceHandleCommandFromAddress(uint32_t address)
{
    if (address == g_service_handler_address)
    {
        return BootFlashService_BootHandleCommand;
    }
    return (address == g_oversize_handler_address) ?
           OversizeService_HandleCommand : NULL;
}

static void FakeFlash_Reset(void)
{
    (void)memset(&g_flash, 0, sizeof(g_flash));
}

static void FakeRam_Reset(void)
{
    (void)memset(&g_ram, 0, sizeof(g_ram));
}

static void Metadata_Reset(void)
{
    size_t index;
    for (index = 0U; index < BOOT_METADATA_SLOT_A_WORDS; index++)
    {
        g_metadata[index] = 0xFFFFU;
    }
}

static uint16_t *Metadata_RecordAt(uint16_t index)
{
    return &g_metadata[(uint32_t)index * BOOT_METADATA_RECORD_WORDS];
}

static void Metadata_PrepareRunAttempt(void)
{
    BootMetadataSummary summary;

    Metadata_Reset();
    BootMetadata_BuildImageValidRecord(Metadata_RecordAt(0U),
                                       1UL,
                                       BOOT_METADATA_SLOT_A_APP_START,
                                       16UL,
                                       0UL,
                                       0U,
                                       0U,
                                       0U,
                                       0UL,
                                       BOOT_METADATA_SLOT_A_APP_START + 16UL,
                                       BOOT_DEVICE_F28377D,
                                       BOOT_CPU1);
    BootMetadata_ScanRecords(g_metadata, BOOT_METADATA_SLOT_A_WORDS, &summary);
    assert(summary.metadata_valid == 1U);
    BootMetadata_BuildBootAttemptRecord(Metadata_RecordAt(1U), 2UL, &summary, 1U);
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

BootFlashResult BootFlash_ProgramMetadataRecord(uint32_t address,
                                                const uint16_t *data,
                                                uint16_t word_count,
                                                BootFlashErrorInfo *error_info)
{
    (void)data;
    ++g_flash.metadata_program_calls;
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
    if (g_expect_invalid_publish_on_ram_write != 0U)
    {
        uint16_t expected_valid = (g_expect_invalid_publish_on_ram_write == 1U) ?
                                  BOOT_FLASH_SERVICE_PUBLISH_INVALID :
                                  BOOT_FLASH_SERVICE_PUBLISH_VALID;
        uint16_t expected_inverse = (g_expect_invalid_publish_on_ram_write == 1U) ?
                                    BOOT_FLASH_SERVICE_PUBLISH_INVALID :
                                    BOOT_FLASH_SERVICE_PUBLISH_VALID_INVERSE;
        assert(g_service_words[BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS -
                               BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS] ==
               expected_valid);
        assert(g_service_words[BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS + 1UL -
                               BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS] ==
               expected_inverse);
    }
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

static void Service_WriteU32(uint16_t offset, uint32_t value)
{
    g_service_words[offset] = (uint16_t)(value & 0xFFFFUL);
    g_service_words[offset + 1U] = (uint16_t)(value >> 16U);
}

static void PrepareServiceHeader(uint32_t handler_address)
{
    uint16_t index;

    (void)memset(g_service_words, 0, sizeof(g_service_words));
    for (index = TEST_IMMUTABLE_OFFSET; index < TEST_SERVICE_WORDS; ++index)
    {
        g_service_words[index] = (uint16_t)(0x4000U + index);
    }
    Service_WriteU32(0U, BOOT_FLASH_SERVICE_HEADER_MAGIC);
    g_service_words[2] = BOOT_FLASH_SERVICE_HEADER_VERSION;
    g_service_words[3] = BOOT_FLASH_SERVICE_HEADER_WORDS;
    g_service_words[4] = BOOT_FLASH_SERVICE_ABI_MAJOR;
    g_service_words[5] = BOOT_FLASH_SERVICE_ABI_MINOR;
    Service_WriteU32(6U, BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS +
                          TEST_IMMUTABLE_OFFSET);
    Service_WriteU32(8U, BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS +
                          TEST_SERVICE_WORDS);
    Service_WriteU32(10U, BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS);
    Service_WriteU32(12U, BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS + 2UL);
    Service_WriteU32(14U, BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS + 0x60UL);
    Service_WriteU32(16U, g_service_boot_init_address);
    Service_WriteU32(18U, handler_address);
    Service_WriteU32(20U, BOOT_SERVICE_REQUIRED_CAPABILITIES);
    g_service_words[22] = BOOT_FLASH_SERVICE_CRC32_IEEE;
    Service_WriteU32(24U,
                     BootCrc32_CalcWords(&g_service_words[TEST_IMMUTABLE_OFFSET],
                                         TEST_SERVICE_WORDS -
                                         TEST_IMMUTABLE_OFFSET));
    Service_WriteU32(26U, BootCrc32_CalcWords(g_service_words, 26UL));
    g_publish_write_count = 0U;
    g_fail_boot_init = 0U;
    g_boot_init_calls = 0U;
}

static void RefreshServiceHeaderCrc(void)
{
    Service_WriteU32(26U, BootCrc32_CalcWords(g_service_words, 26UL));
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
    const uint16_t begin[9] = {BOOT_TARGET_RAM_APP, 1U, 3U, 0U, 1U, 8U, 0U, 0U, 0U};
    const uint16_t data[8] = {1U, 8U, 3U, 0U, 0U, 1U, 2U, 3U};
    const uint16_t end[6] = {1U, 0U, 3U, 0U, 0U, 0U};
    const uint16_t crc_words[3] = {1U, 2U, 3U};
    uint32_t crc32 = BootCrc32_CalcWords(crc_words, 3UL);
    uint16_t check_crc[5];
    const uint16_t run_ram[3] = {0U, 0U, 0U};
    size_t offset = 0U;

    check_crc[0] = (uint16_t)(crc32 & 0xFFFFUL);
    check_crc[1] = (uint16_t)(crc32 >> 16U);
    check_crc[2] = 3U;
    check_crc[3] = 0U;
    check_crc[4] = 0U;

    FakeRam_Reset();
    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    AppendRequest(&fake, BOOT_CMD_PING, 1U, NULL, 0U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_ERASE, 2U, erase_payload, 3U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_RAM_LOAD_BEGIN, 3U, begin, 9U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_RAM_LOAD_DATA, 4U, data, 8U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_RAM_LOAD_END, 5U, end, 6U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_RAM_CHECK_CRC, 6U, check_crc, 5U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_RUN_RAM, 7U, run_ram, 3U, 0U, 0U);

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
    offset = AssertResponse(&fake, offset, BOOT_CMD_RAM_LOAD_END, 5U,
                            BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    offset = AssertResponse(&fake, offset, BOOT_CMD_RAM_CHECK_CRC, 6U,
                            BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    assert(BootAlgorithm_ProcessOne(&algorithm) == BOOT_ALGORITHM_ACTION_RUN_RAM_APP);
    (void)AssertResponse(&fake, offset, BOOT_CMD_RUN_RAM, 7U,
                         BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    assert(BootAlgorithm_GetPendingEntryPoint(&algorithm) == 0x00080001UL);
    assert(g_ram.check_calls == 2U);
    assert(g_ram.write_calls == 1U);
    assert(g_ram.last_address == 0x00080001UL);
    assert(g_ram.last_word_count == 1U);
    assert(algorithm.ram_load.image_ready == 1U);
    assert(algorithm.ram_load.crc_checked == 1U);
}

static void Test_MemoryReadCommand(void)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;
    const uint16_t request[4] = {0x5678U, 0x1234U, 3U, 0U};
    const uint32_t start_address = 0x12345678UL;
    uint16_t index;

    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    AppendRequest(&fake, BOOT_CMD_MEMORY_READ, 1U, request, 4U, 0U, 0U);
    g_memory_read_calls = 0U;
    (void)BootAlgorithm_ProcessOne(&algorithm);

#if BOOT_ENABLE_MEMORY_READ
    (void)AssertResponse(&fake, 0U, BOOT_CMD_MEMORY_READ, 1U,
                         BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 6U);
    assert(TxWord(&fake, 10U) == request[0]);
    assert(TxWord(&fake, 11U) == request[1]);
    assert(TxWord(&fake, 12U) == request[2]);
    assert(g_memory_read_calls == request[2]);
    for (index = 0U; index < request[2]; ++index)
    {
        assert(g_memory_read_addresses[index] == start_address + (uint32_t)index);
        assert(TxWord(&fake, 13U + index) ==
               Test_MemoryValue(start_address + (uint32_t)index));
    }
#else
    (void)index;
    (void)start_address;
    (void)AssertResponse(&fake, 0U, BOOT_CMD_MEMORY_READ, 1U,
                         BOOT_PKT_ERROR_RESPONSE,
                         BOOT_STATUS_UNKNOWN_COMMAND, 0U);
    assert(g_memory_read_calls == 0U);
#endif
}

static void AssertPublishState(uint16_t valid, uint16_t valid_inverse)
{
    assert(g_service_words[BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS -
                           BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS] == valid);
    assert(g_service_words[BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS + 1UL -
                           BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS] == valid_inverse);
}

static void AssertServiceValidationFails(const BootDeviceInfo *info)
{
    BootFlashServiceHandleCommandFn handler = BootFlashService_BootHandleCommand;
    assert(BootAlgorithm_ValidateFlashService(info, &handler) != BOOT_STATUS_OK);
    assert(handler == NULL);
    AssertPublishState(BOOT_FLASH_SERVICE_PUBLISH_INVALID,
                       BOOT_FLASH_SERVICE_PUBLISH_INVALID);
}

static void Test_ServiceValidationAndPublish(void)
{
    BootDeviceInfo info = Test_DeviceInfo();
    BootFlashServiceHandleCommandFn handler = NULL;

    FakeRam_Reset();
    PrepareServiceHeader(g_service_handler_address);
    assert(BootAlgorithm_ValidateFlashService(&info, &handler) == BOOT_STATUS_OK);
    assert(handler == BootFlashService_BootHandleCommand);
    assert(g_boot_init_calls == 1U);
    AssertPublishState(BOOT_FLASH_SERVICE_PUBLISH_VALID,
                       BOOT_FLASH_SERVICE_PUBLISH_VALID_INVERSE);
    assert(g_publish_write_count == 4U);
    assert(g_publish_write_addresses[2] ==
           BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS + 1UL);
    assert(g_publish_write_values[2] ==
           BOOT_FLASH_SERVICE_PUBLISH_VALID_INVERSE);
    assert(g_publish_write_addresses[3] ==
           BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS);
    assert(g_publish_write_values[3] == BOOT_FLASH_SERVICE_PUBLISH_VALID);

    PrepareServiceHeader(g_service_handler_address);
    g_service_words[0] ^= 1U;
    AssertServiceValidationFails(&info);

    PrepareServiceHeader(g_service_handler_address);
    g_service_words[26] ^= 1U;
    AssertServiceValidationFails(&info);

    PrepareServiceHeader(g_service_handler_address);
    g_service_words[TEST_IMMUTABLE_OFFSET] ^= 1U;
    AssertServiceValidationFails(&info);

    PrepareServiceHeader(g_service_handler_address);
    g_service_words[4] = (uint16_t)(BOOT_FLASH_SERVICE_ABI_MAJOR + 1U);
    RefreshServiceHeaderCrc();
    AssertServiceValidationFails(&info);

    PrepareServiceHeader(g_service_handler_address);
    Service_WriteU32(20U, BOOT_SERVICE_CAP_ERASE);
    RefreshServiceHeaderCrc();
    AssertServiceValidationFails(&info);

    PrepareServiceHeader(g_service_handler_address);
    g_fail_boot_init = 1U;
    AssertServiceValidationFails(&info);

    PrepareServiceHeader(g_service_handler_address);
    Service_WriteU32(16U, BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS + 0x40UL);
    RefreshServiceHeaderCrc();
    AssertServiceValidationFails(&info);
}

static void Test_ServiceHeaderGlobalSymbols(void)
{
    assert(g_boot_flash_service_header.boot_init == BootFlashService_BootInit);
    assert(g_boot_flash_service_header.boot_handle_command ==
           BootFlashService_BootHandleCommand);
    assert(g_boot_flash_service_app_export.confirm_current_image ==
           BootFlashService_ConfirmCurrentImage);
}

static void Test_ServiceAttachCommand(void)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;
    const uint32_t loaded_words = TEST_SERVICE_WORDS;
    const uint32_t image_crc32 = 0x12345678UL;
    uint16_t attach_payload[7];
    const uint16_t erase_payload[3] = {5U, 0U, 0U};
    size_t offset = 0U;

    FakeFlash_Reset();
    PrepareServiceHeader(g_service_handler_address);
    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    algorithm.ram_load.image_ready = 1U;
    algorithm.ram_load.crc_checked = 1U;
    algorithm.ram_load.loaded_start = BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS;
    algorithm.ram_load.loaded_end_exclusive =
        BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS + loaded_words;
    algorithm.ram_load.crc32 = image_crc32;
    algorithm.ram_load.expected_total_words = loaded_words;

    attach_payload[0] = (uint16_t)(BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS & 0xFFFFUL);
    attach_payload[1] = (uint16_t)(BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS >> 16U);
    attach_payload[2] = (uint16_t)(image_crc32 & 0xFFFFUL);
    attach_payload[3] = (uint16_t)(image_crc32 >> 16U);
    attach_payload[4] = (uint16_t)(loaded_words & 0xFFFFUL);
    attach_payload[5] = (uint16_t)(loaded_words >> 16U);
    attach_payload[6] = 0U;

    AppendRequest(&fake, BOOT_CMD_GET_SERVICE_STATUS, 1U, NULL, 0U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_SERVICE_ATTACH, 2U, attach_payload, 7U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_GET_SERVICE_STATUS, 3U, NULL, 0U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_ERASE, 4U, erase_payload, 3U, 0U, 0U);

    (void)BootAlgorithm_ProcessOne(&algorithm);
    offset = AssertResponse(&fake, offset, BOOT_CMD_GET_SERVICE_STATUS, 1U,
                            BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 12U);
    assert(TxWord(&fake, 10U) == BOOT_SERVICE_STATE_DETACHED);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    offset = AssertResponse(&fake, offset, BOOT_CMD_SERVICE_ATTACH, 2U,
                            BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    assert(algorithm.service_active == 1U);
    assert(algorithm.service_state.state == BOOT_SERVICE_STATE_ATTACHED);
    assert(g_boot_init_calls == 1U);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    offset = AssertResponse(&fake, offset, BOOT_CMD_GET_SERVICE_STATUS, 3U,
                            BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 12U);
    assert(TxWord(&fake, offset - 13U) == BOOT_SERVICE_STATE_ATTACHED);
    assert(TxWord(&fake, offset - 10U) == 0U);
    assert(TxWord(&fake, offset - 9U) == 0U);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    (void)AssertResponse(&fake, offset, BOOT_CMD_ERASE, 4U,
                         BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    assert(g_flash.erase_calls == 1U);

    PrepareServiceHeader(g_service_handler_address);
    fake = (FakeIo){0};
    ops = Fake_Ops(&fake);
    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    algorithm.ram_load.image_ready = 1U;
    algorithm.ram_load.crc_checked = 1U;
    algorithm.ram_load.loaded_start = BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS;
    algorithm.ram_load.loaded_end_exclusive =
        BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS + loaded_words;
    algorithm.ram_load.crc32 = image_crc32;
    algorithm.ram_load.expected_total_words = loaded_words;
    attach_payload[2] ^= 1U;
    AppendRequest(&fake, BOOT_CMD_SERVICE_ATTACH, 1U, attach_payload, 7U, 0U, 0U);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    (void)AssertResponse(&fake, 0U, BOOT_CMD_SERVICE_ATTACH, 1U,
                         BOOT_PKT_ERROR_RESPONSE,
                         BOOT_STATUS_VERIFY_MISMATCH, 0U);
    assert(g_boot_init_calls == 0U);
    AssertPublishState(BOOT_FLASH_SERVICE_PUBLISH_INVALID,
                       BOOT_FLASH_SERVICE_PUBLISH_INVALID);
    attach_payload[2] ^= 1U;

    PrepareServiceHeader(g_service_handler_address);
    g_service_words[0] ^= 1U;
    fake = (FakeIo){0};
    ops = Fake_Ops(&fake);
    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    algorithm.ram_load.image_ready = 1U;
    algorithm.ram_load.crc_checked = 1U;
    algorithm.ram_load.loaded_start = BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS;
    algorithm.ram_load.loaded_end_exclusive =
        BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS + loaded_words;
    algorithm.ram_load.crc32 = image_crc32;
    algorithm.ram_load.expected_total_words = loaded_words;
    AppendRequest(&fake, BOOT_CMD_SERVICE_ATTACH, 1U, attach_payload, 7U, 0U, 0U);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    (void)AssertResponse(&fake, 0U, BOOT_CMD_SERVICE_ATTACH, 1U,
                         BOOT_PKT_ERROR_RESPONSE,
                         BOOT_STATUS_METADATA_INVALID, 0U);
    assert(algorithm.service_active == 0U);
    AssertPublishState(BOOT_FLASH_SERVICE_PUBLISH_INVALID,
                       BOOT_FLASH_SERVICE_PUBLISH_INVALID);
}

static void AssertInvalidAttachPreservesService(uint16_t payload_words,
                                                uint16_t flags,
                                                uint16_t mismatch_crc,
                                                uint16_t expected_status)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;
    const uint32_t image_crc32 = 0x12345678UL;
    const uint32_t service_crc32 = 0x89ABCDEFUL;
    const uint32_t service_words = 0x5678UL;
    const uint32_t service_capabilities = BOOT_SERVICE_REQUIRED_CAPABILITIES;
    uint16_t attach_payload[7];

    PrepareServiceHeader(g_service_handler_address);
    g_service_words[BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS -
                    BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS] =
        BOOT_FLASH_SERVICE_PUBLISH_VALID;
    g_service_words[BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS + 1UL -
                    BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS] =
        BOOT_FLASH_SERVICE_PUBLISH_VALID_INVERSE;
    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    algorithm.ram_load.image_ready = 1U;
    algorithm.ram_load.crc_checked = 1U;
    algorithm.ram_load.loaded_start = BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS;
    algorithm.ram_load.loaded_end_exclusive =
        BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS + TEST_SERVICE_WORDS;
    algorithm.ram_load.crc32 = image_crc32;
    algorithm.ram_load.expected_total_words = TEST_SERVICE_WORDS;
    algorithm.service_command_handler = BootFlashService_BootHandleCommand;
    algorithm.service_active = 1U;
    algorithm.service_state.state = BOOT_SERVICE_STATE_ATTACHED;
    algorithm.service_state.capabilities = service_capabilities;
    algorithm.service_state.loaded_crc32 = service_crc32;
    algorithm.service_state.loaded_words = service_words;

    attach_payload[0] = (uint16_t)BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS;
    attach_payload[1] = (uint16_t)(BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS >> 16U);
    attach_payload[2] = (uint16_t)image_crc32;
    attach_payload[3] = (uint16_t)(image_crc32 >> 16U);
    attach_payload[4] = TEST_SERVICE_WORDS;
    attach_payload[5] = 0U;
    attach_payload[6] = flags;
    if (mismatch_crc != 0U)
    {
        attach_payload[2] ^= 1U;
    }

    AppendRequest(&fake, BOOT_CMD_SERVICE_ATTACH, 1U,
                  attach_payload, payload_words, 0U, 0U);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    (void)AssertResponse(&fake, 0U, BOOT_CMD_SERVICE_ATTACH, 1U,
                         BOOT_PKT_ERROR_RESPONSE, expected_status, 0U);
    assert(algorithm.service_active == 1U);
    assert(algorithm.service_command_handler ==
           BootFlashService_BootHandleCommand);
    assert(algorithm.service_state.state == BOOT_SERVICE_STATE_ATTACHED);
    assert(algorithm.service_state.capabilities == service_capabilities);
    assert(algorithm.service_state.loaded_crc32 == service_crc32);
    assert(algorithm.service_state.loaded_words == service_words);
    assert(algorithm.service_state.last_attach_status == expected_status);
    AssertPublishState(BOOT_FLASH_SERVICE_PUBLISH_VALID,
                       BOOT_FLASH_SERVICE_PUBLISH_VALID_INVERSE);
    assert(g_boot_init_calls == 0U);
}

static void Test_InvalidServiceAttachPreservesActiveService(void)
{
    AssertInvalidAttachPreservesService(6U, 0U, 0U,
                                        BOOT_STATUS_BAD_PAYLOAD_LENGTH);
    AssertInvalidAttachPreservesService(7U, 1U, 0U, BOOT_STATUS_BAD_FLAGS);
    AssertInvalidAttachPreservesService(7U, 0U, 1U,
                                        BOOT_STATUS_VERIFY_MISMATCH);
}

static uint16_t OversizeService_HandleCommand(const BootProtocolFrame *request,
                                              uint16_t *response_payload,
                                              uint16_t *response_payload_words,
                                              BootErrorDetail *error)
{
    (void)request;
    (void)response_payload;
    BootErrorDetail_Clear(error);
    *response_payload_words = (uint16_t)(BOOT_PROTOCOL_MAX_PAYLOAD_WORDS + 1U);
    return BOOT_STATUS_OK;
}

static void Test_CoreRejectsOversizeServicePayload(void)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;
    uint16_t attach_payload[7];
    const uint32_t image_crc32 = 0x12345678UL;
    const uint16_t erase_payload[3] = {5U, 0U, 0U};
    size_t offset;

    FakeRam_Reset();
    PrepareServiceHeader(g_oversize_handler_address);
    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    algorithm.ram_load.image_ready = 1U;
    algorithm.ram_load.crc_checked = 1U;
    algorithm.ram_load.loaded_start = BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS;
    algorithm.ram_load.loaded_end_exclusive =
        BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS + TEST_SERVICE_WORDS;
    algorithm.ram_load.crc32 = image_crc32;
    algorithm.ram_load.expected_total_words = TEST_SERVICE_WORDS;
    attach_payload[0] = (uint16_t)BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS;
    attach_payload[1] = (uint16_t)(BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS >> 16U);
    attach_payload[2] = (uint16_t)image_crc32;
    attach_payload[3] = (uint16_t)(image_crc32 >> 16U);
    attach_payload[4] = TEST_SERVICE_WORDS;
    attach_payload[5] = 0U;
    attach_payload[6] = 0U;
    AppendRequest(&fake, BOOT_CMD_SERVICE_ATTACH, 1U, attach_payload, 7U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_ERASE, 2U, erase_payload, 3U, 0U, 0U);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    offset = AssertResponse(&fake, 0U, BOOT_CMD_SERVICE_ATTACH, 1U,
                            BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    (void)AssertResponse(&fake, offset, BOOT_CMD_ERASE, 2U,
                         BOOT_PKT_ERROR_RESPONSE,
                         BOOT_STATUS_BAD_PAYLOAD_LENGTH, 0U);
}

static void AssertRamWritePublishBehavior(uint32_t address,
                                          uint16_t expect_invalidation)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;
    uint16_t begin[9] = {BOOT_TARGET_RAM_APP, 1U, 1U, 0U, 0U, 0U, 0U, 0U, 0U};
    uint16_t data[6] = {0U, 0U, 1U, 0U, 0U, 0x1234U};
    const uint16_t end[6] = {1U, 0U, 1U, 0U, 0U, 0U};
    uint16_t check_crc[5];
    const uint32_t ram_crc32 = BootCrc32_CalcWords(&data[5], 1UL);
    const uint32_t service_crc32 = 0x89ABCDEFUL;
    const uint32_t service_words = 0x1234UL;
    const uint32_t service_capabilities = BOOT_SERVICE_REQUIRED_CAPABILITIES;
    size_t offset;

    begin[4] = (uint16_t)address;
    begin[5] = (uint16_t)(address >> 16U);
    data[0] = (uint16_t)address;
    data[1] = (uint16_t)(address >> 16U);
    check_crc[0] = (uint16_t)ram_crc32;
    check_crc[1] = (uint16_t)(ram_crc32 >> 16U);
    check_crc[2] = 1U;
    check_crc[3] = 0U;
    check_crc[4] = 0U;
    FakeRam_Reset();
    PrepareServiceHeader(g_service_handler_address);
    g_service_words[BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS -
                    BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS] =
        BOOT_FLASH_SERVICE_PUBLISH_VALID;
    g_service_words[BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS + 1UL -
                    BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS] =
        BOOT_FLASH_SERVICE_PUBLISH_VALID_INVERSE;
    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    algorithm.service_command_handler = BootFlashService_BootHandleCommand;
    algorithm.service_active = 1U;
    algorithm.service_state.state = BOOT_SERVICE_STATE_ATTACHED;
    algorithm.service_state.capabilities = service_capabilities;
    algorithm.service_state.loaded_crc32 = service_crc32;
    algorithm.service_state.loaded_words = service_words;
    g_expect_invalid_publish_on_ram_write =
        (expect_invalidation != 0U) ? 1U : 2U;

    AppendRequest(&fake, BOOT_CMD_RAM_LOAD_BEGIN, 1U, begin, 9U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_RAM_LOAD_DATA, 2U, data, 6U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_RAM_LOAD_END, 3U, end, 6U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_RAM_CHECK_CRC, 4U, check_crc, 5U, 0U, 0U);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    offset = AssertResponse(&fake, 0U, BOOT_CMD_RAM_LOAD_BEGIN, 1U,
                            BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    assert(algorithm.service_active == 1U);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    offset = AssertResponse(&fake, offset, BOOT_CMD_RAM_LOAD_DATA, 2U,
                            BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    offset = AssertResponse(&fake, offset, BOOT_CMD_RAM_LOAD_END, 3U,
                            BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    (void)BootAlgorithm_ProcessOne(&algorithm);
    (void)AssertResponse(&fake, offset, BOOT_CMD_RAM_CHECK_CRC, 4U,
                         BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    assert(algorithm.service_active ==
           ((expect_invalidation != 0U) ? 0U : 1U));
    assert(algorithm.service_command_handler ==
           ((expect_invalidation != 0U) ? NULL :
            BootFlashService_BootHandleCommand));
    if (expect_invalidation != 0U)
    {
        AssertPublishState(BOOT_FLASH_SERVICE_PUBLISH_INVALID,
                           BOOT_FLASH_SERVICE_PUBLISH_INVALID);
    }
    else
    {
        assert(algorithm.service_state.state == BOOT_SERVICE_STATE_ATTACHED);
        assert(algorithm.service_state.capabilities == service_capabilities);
        assert(algorithm.service_state.loaded_crc32 == service_crc32);
        assert(algorithm.service_state.loaded_words == service_words);
        AssertPublishState(BOOT_FLASH_SERVICE_PUBLISH_VALID,
                           BOOT_FLASH_SERVICE_PUBLISH_VALID_INVERSE);
    }
    assert(algorithm.ram_load.image_ready == 1U);
    assert(algorithm.ram_load.crc_checked == 1U);
    assert(algorithm.ram_load.crc32 == ram_crc32);
    assert(algorithm.ram_load.expected_total_words == 1UL);
    g_expect_invalid_publish_on_ram_write = 0U;
}

static void Test_RamWriteInvalidatesOnlyServiceHeader(void)
{
    AssertRamWritePublishBehavior(BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS, 1U);
}

static void Test_OrdinaryRamDownloadPreservesFlashService(void)
{
    AssertRamWritePublishBehavior(BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS +
                                  BOOT_FLASH_SERVICE_HEADER_RESERVED_WORDS, 0U);
}

static void Test_RunResetAndPendingEntry(void)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;
    uint16_t run[4] = {BOOT_TARGET_FLASH_APP, 0x2400U, 0x0008U, 0U};
    size_t offset = 0U;

    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    Metadata_PrepareRunAttempt();
    AppendRequest(&fake, BOOT_CMD_RUN, 1U, run, 4U, 0U, 0U);
    AppendRequest(&fake, BOOT_CMD_RESET, 2U, NULL, 0U, 0U, 0U);
    assert(BootAlgorithm_ProcessOne(&algorithm) == BOOT_ALGORITHM_ACTION_RUN_FLASH_APP);
    offset = AssertResponse(&fake, offset, BOOT_CMD_RUN, 1U,
                            BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
    assert(BootAlgorithm_GetPendingEntryPoint(&algorithm) == BOOT_METADATA_SLOT_A_APP_START);
    assert(BootAlgorithm_ProcessOne(&algorithm) == BOOT_ALGORITHM_ACTION_RESET_DEVICE);
    (void)AssertResponse(&fake, offset, BOOT_CMD_RESET, 2U,
                         BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 0U);
}

static void Test_ServiceProgramVerifyValidation(void)
{
    BootDeviceInfo info = Test_DeviceInfo();
    uint16_t response_payload[BOOT_PROTOCOL_MAX_PAYLOAD_WORDS];
    uint16_t response_words;
    BootErrorDetail error;
    uint16_t begin[9] = {BOOT_TARGET_FLASH_APP, 1U, 8U, 0U, 0U, 8U, 0U, 0U, 0x1234U};
    const uint16_t data[13] = {0U, 8U, 8U, 0U, 0U, 1U, 2U, 3U, 4U, 5U, 6U, 7U, 8U};
    const uint16_t end[6] = {1U, 0U, 8U, 0U, 0U, 0U};
    BootProtocolFrame frame;

    FakeFlash_Reset();
    assert(BootFlashService_BootInit(info.device_id,
                                    info.cpu_id,
                                    info.max_data_words) == BOOT_STATUS_OK);

    frame = RequestFrame(BOOT_CMD_PROGRAM_DATA, data, 13U);
    assert(BootFlashService_BootHandleCommand(&frame, response_payload,
                                              &response_words, &error) ==
           BOOT_STATUS_MISSING_BEGIN);
    assert(error.operation == BOOT_ERR_OP_PROGRAM);

    frame = RequestFrame(BOOT_CMD_PROGRAM_BEGIN, begin, 9U);
    assert(BootFlashService_BootHandleCommand(&frame, response_payload,
                                              &response_words, &error) ==
           BOOT_STATUS_OK);
    frame = RequestFrame(BOOT_CMD_PROGRAM_DATA, data, 13U);
    assert(BootFlashService_BootHandleCommand(&frame, response_payload,
                                              &response_words, &error) ==
           BOOT_STATUS_OK);
    frame = RequestFrame(BOOT_CMD_PROGRAM_END, end, 6U);
    assert(BootFlashService_BootHandleCommand(&frame, response_payload,
                                              &response_words, &error) ==
           BOOT_STATUS_OK);
    assert(g_flash.program_calls == 1U);

    g_flash.verify_result = BOOT_FLASH_RESULT_FAILED;
    g_flash.error_info.address = 0x00080004UL;
    g_flash.error_info.length_words = 8UL;
    g_flash.error_info.api_status = -7;
    g_flash.error_info.fsm_status = 0x12345678UL;
    frame = RequestFrame(BOOT_CMD_VERIFY_BEGIN, begin, 9U);
    assert(BootFlashService_BootHandleCommand(&frame, response_payload,
                                              &response_words, &error) ==
           BOOT_STATUS_OK);
    frame = RequestFrame(BOOT_CMD_VERIFY_DATA, data, 13U);
    assert(BootFlashService_BootHandleCommand(&frame, response_payload,
                                              &response_words, &error) ==
           BOOT_STATUS_VERIFY_FAILED);
    assert(error.operation == BOOT_ERR_OP_VERIFY);
    assert(error.stage == BOOT_ERR_STAGE_VERIFY);
    assert(error.address == 0x00080004UL);
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
    Test_MemoryReadCommand();
    Test_ServiceValidationAndPublish();
    Test_ServiceHeaderGlobalSymbols();
    Test_ServiceAttachCommand();
    Test_InvalidServiceAttachPreservesActiveService();
    Test_CoreRejectsOversizeServicePayload();
    Test_RamWriteInvalidatesOnlyServiceHeader();
    Test_OrdinaryRamDownloadPreservesFlashService();
    Test_RunResetAndPendingEntry();
    Test_ServiceProgramVerifyValidation();
    puts("DSP host tests passed");
    return 0;
}
