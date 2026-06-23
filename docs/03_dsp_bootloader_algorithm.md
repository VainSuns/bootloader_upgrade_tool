# 03 DSP Bootloader Algorithm Requirements

## 1. 模块定位

Codex 生成 DSP bootloader upper-layer algorithm，不生成完整 TI 工程。

建议目录：

```text
dsp/
  bootloader_algorithm/
  user_port_templates/
  tests/
```

## 2. BootIoOps

DSP 侧 IO 抽象：

```c
typedef struct
{
    void *ctx;
    BootIoConnectResult (*connect_master)(void *ctx, uint32_t timeout_ms);
    uint16_t (*get_word)(void *ctx);
    void (*send_word)(void *ctx, uint16_t word);
} BootIoOps;
```

SCI autobaud 在 `connect_master` 内部由用户实现。

## 3. BootFlash 抽象

Codex 声明，用户实现：

```c
typedef uint16_t BootFlashResult;

BootFlashResult BootFlash_CheckAddress(uint32_t address,
                                       uint32_t word_count,
                                       BootFlashOperation op,
                                       BootFlashErrorInfo *error_info);

BootFlashResult BootFlash_EraseBySectorMask(uint32_t sector_mask_low,
                                            uint32_t sector_mask_high,
                                            BootFlashErrorInfo *error_info);

BootFlashResult BootFlash_ProgramBlock(uint32_t address,
                                       const uint16_t *data,
                                       uint16_t word_count,
                                       BootFlashErrorInfo *error_info);

BootFlashResult BootFlash_VerifyBlock(uint32_t address,
                                      const uint16_t *expected,
                                      uint16_t word_count,
                                      BootFlashErrorInfo *error_info);
```

具体签名可在实现阶段微调，但必须满足：

- `BootFlashResult` 是轻量返回值，只表示执行结果，例如 OK / bad address / program failed；
- 不建议通过函数返回值直接返回包含多个字段的大结构体；
- 需要返回的详细错误信息通过输入参数中的结构体指针返回，例如 `BootFlashErrorInfo *error_info`；
- `word_count` 以 16-bit word 为单位；
- `ProgramBlock` 正常接收 8-word 整数倍；
- user API 做最终地址、保护区、对齐和底层 Flash API 检查；
- 详细错误信息至少应能表达 operation、address、length、api_status、fsm_status、extra；
- 如果调用者不需要详细错误，可传入空指针，具体是否允许由最终 API 设计确认。

建议概念结构：

```c
typedef struct
{
    BootFlashOperation operation;
    uint32_t address;
    uint32_t length_words;
    int32_t api_status;
    uint32_t fsm_status;
    uint32_t extra;
} BootFlashErrorInfo;
```

注意：以上结构仅用于说明信息组织方式，最终字段名和类型在详细设计阶段确认。


## 4. BootRam 抽象，Future

RAM 写入由用户 API 决定。与 BootFlash 类似，BootRam 也不建议通过函数返回值返回大结构体；函数返回值只表示执行结果，详细信息通过输入参数中的结构体指针返回。

```c
typedef uint16_t BootRamResult;

BootRamResult BootRam_CheckAddress(uint32_t address,
                                   uint32_t word_count,
                                   BootRamRegionType region_type,
                                   BootRamErrorInfo *error_info);

BootRamResult BootRam_WriteBlock(uint32_t address,
                                 const uint16_t *data,
                                 uint16_t word_count,
                                 BootRamRegionType region_type,
                                 BootRamErrorInfo *error_info);
```

建议概念结构：

```c
typedef struct
{
    BootRamRegionType region_type;
    uint32_t address;
    uint32_t length_words;
    uint32_t extra;
} BootRamErrorInfo;
```

MVP 不实现真实 RAM lib 加载，但协议和源码必须预留。


## 5. 协议状态机

DSP 状态应尽可能小：

```text
program_active
verify_active
current_target
expected_block_count
expected_total_words
received_packet_count
received_word_count
expected_block_index
last_error
```

DSP 不维护完整 Flash 写历史表。

## 6. Program/Verify/RamLoad 数据规则

`ProgramData`、`VerifyData`、`RamLoadData` 中的 `data_words` 必须为 8 的整数倍。不满足时返回 `BOOT_STATUS_BAD_WORD_COUNT`。

Flash Program 失败后结束 program session，要求重新 Program/DFU。Verify 失败后结束 verify session。

## 7. Run / Reset

Algorithm 不直接跳转 App，也不直接 reset。收到 Run 或 Reset 后先返回 OK response，再向用户外层返回 action。

Reset 要求：先发送 OK response，再由外层执行 reset action。
