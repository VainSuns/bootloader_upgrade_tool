#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include "boot_algorithm.h"

#define TEST_BUFFER_WORDS 2048U

typedef struct
{
    uint16_t rx[TEST_BUFFER_WORDS];
    size_t rx_count;
    size_t rx_index;
    uint16_t tx[TEST_BUFFER_WORDS];
    size_t tx_count;
    uint32_t connect_timeout_ms;
} FakeIo;

static BootIoConnectResult Fake_Connect(void *ctx, uint32_t timeout_ms)
{
    FakeIo *io = (FakeIo *)ctx;
    io->connect_timeout_ms = timeout_ms;
    return BOOT_IO_CONNECT_OK;
}

static uint16_t Fake_GetWord(void *ctx)
{
    FakeIo *io = (FakeIo *)ctx;
    assert(io->rx_index < io->rx_count);
    return io->rx[io->rx_index++];
}

static void Fake_SendWord(void *ctx, uint16_t word)
{
    FakeIo *io = (FakeIo *)ctx;
    assert(io->tx_count < TEST_BUFFER_WORDS);
    io->tx[io->tx_count++] = word;
}

static BootIoOps Fake_Ops(FakeIo *io)
{
    BootIoOps ops;
    ops.ctx = io;
    ops.connect_master = Fake_Connect;
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
    return info;
}

static void AppendWord(FakeIo *io, uint16_t word)
{
    assert(io->rx_count < TEST_BUFFER_WORDS);
    io->rx[io->rx_count++] = word;
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
    assert(offset + total_words <= io->tx_count);
    assert(io->tx[offset + 0U] == BOOT_PROTOCOL_MAGIC0);
    assert(io->tx[offset + 1U] == BOOT_PROTOCOL_MAGIC1);
    assert(io->tx[offset + 2U] == BOOT_PROTOCOL_VERSION);
    assert(io->tx[offset + 3U] == packet_type);
    assert(io->tx[offset + 4U] == command);
    assert(io->tx[offset + 5U] == sequence);
    assert(io->tx[offset + 6U] == 0U);
    assert(io->tx[offset + 7U] == status);
    assert(io->tx[offset + 8U] == payload_words);
    assert(io->tx[offset + 9U] == BootProtocol_CrcWords(&io->tx[offset], 9U));
    assert(io->tx[offset + 10U + payload_words] ==
           BootProtocol_CrcWords(&io->tx[offset + 10U], payload_words));
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

static void Test_DeviceInfoAndResync(void)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;

    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    AppendWord(&fake, 0x1111U);
    AppendWord(&fake, BOOT_PROTOCOL_MAGIC0);
    AppendWord(&fake, 0x2222U);
    AppendRequest(&fake, BOOT_CMD_PING, 7U, NULL, 0U, 1U, 0U);
    AppendRequest(&fake, BOOT_CMD_GET_DEVICE_INFO, 8U, NULL, 0U, 0U, 0U);

    BootAlgorithm_ProcessOne(&algorithm);
    (void)AssertResponse(&fake,
                         0U,
                         BOOT_CMD_GET_DEVICE_INFO,
                         8U,
                         BOOT_PKT_RESPONSE,
                         BOOT_STATUS_OK,
                         BOOT_DEVICE_INFO_WORDS);
    assert(fake.tx[10U] == BOOT_DEVICE_F28377D);
    assert(fake.tx[11U] == BOOT_CPU1);
    assert(fake.tx[15U] == BOOT_PROTOCOL_VERSION);
    assert(fake.tx[18U] == BOOT_PROTOCOL_MAX_PAYLOAD_WORDS);
    assert(fake.tx[19U] == 248U);
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
    AppendRequest(&fake, BOOT_CMD_PROGRAM_BEGIN, 2U, NULL, 0U, 0U, 0U);
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
                            BOOT_CMD_PROGRAM_BEGIN,
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
    assert(fake.tx[offset + 10U] == BOOT_ERR_OP_FRAME);
    assert(fake.tx[offset + 11U] == BOOT_ERR_STAGE_STATE);
    assert(algorithm.last_error.operation == BOOT_ERR_OP_FRAME);
    assert(algorithm.last_error.stage == BOOT_ERR_STAGE_STATE);
}

static void TestConnectAndInitValidation(void)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;

    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    assert(BootAlgorithm_ConnectMaster(&algorithm, 1234UL) == BOOT_IO_CONNECT_OK);
    assert(fake.connect_timeout_ms == 1234UL);

    info.max_data_words = 247U;
    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 0U);
}

int main(void)
{
    Test_Crc();
    Test_DeviceInfoAndResync();
    TestErrorsAndLastError();
    TestConnectAndInitValidation();
    puts("DSP host tests passed");
    return 0;
}
