# 03 DSP Bootloader Algorithm Requirements

## 1. 模块定位

Codex 生成 DSP bootloader upper-layer algorithm，不生成完整 TI 工程。

建议目录：

```text
dsp/
  bootloader_core/
  bootloader_common/
  bootloader_user/
  flash_service_lib/
  tests/
```

### 1.1 当前 CPU1 production baseline

当前已审核并完成 focused hardware validation 的产品路径为：

```text
Target: TMS320F28377D CPU1
Transport: SCI-A / RS232
SCI RX/TX: GPIO64 / GPIO65
word serialization: low byte first, high byte second
autobaud: PC sends ASCII 'A', DSP echoes ASCII 'A'
```

autobaud 属于连接层，不是协议 frame；PC 仍为 master，DSP 仍为 slave。底层
时钟、GPIO、SCI 和器件初始化继续由用户 port 层维护。

## 2. BootIoOps

DSP 侧 IO 抽象：

```c
typedef struct
{
    void *ctx;
    BootIoGetByteFn get_byte;
    BootIoGetWordFn get_word;
    BootIoSendWordFn send_word;
} BootIoOps;
```

`get_byte` 是无 timeout 参数的阻塞 byte IO，仅用于接收同步。SCI autobaud
和连接 timeout 属于用户 connection flow 或更高层状态机，不属于 byte IO，
也不产生协议 timeout status。发送继续使用 `send_word`。

## 3. BootFlash 抽象

Codex 声明，用户实现：

```c
typedef uint16_t BootFlashResult;

BootFlashResult BootFlash_Init(BootFlashErrorInfo *error_info);

BootFlashResult BootFlash_CheckAddress(uint32_t address,
                                       uint32_t word_count,
                                       BootFlashOperation op,
                                       BootFlashErrorInfo *error_info);

BootFlashResult BootFlash_EraseBySectorMask(uint32_t sector_mask,
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
- Flash 初始化失败使用独立的 `BOOT_FLASH_RESULT_INIT_FAILED`；
- F28377D 的 13 个 Flash sector 使用单个 `uint32_t sector_mask`，bit 0–12 有效；
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


## 4. BootRam 抽象

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

当前实现通过 RAM_LOAD、RAM_CHECK_CRC 和 SERVICE_ATTACH 装载、校验并连接
downloaded service。具体 service artifact、底层初始化和 linker placement
仍由用户维护；Flash-resident core 不静态链接 service binary。

## 4.1 DeviceInfo 与器件身份

DSP 内部 `BootDeviceInfo` 包含完整的 `BootDeviceIdentity`：PARTIDL、PARTIDH、
REVID、UID_UNIQUE、UID_CHECKSUM 和 UID_PSRAND0..5。硬件寄存器只能由用户
port 层读取，algorithm core 只消费已经填充的结构。

`GetDeviceInfo v1` 保持 16 words，只导出 REVID 和 UID_UNIQUE。完整 PARTID、
UID_CHECKSUM、UID_PSRAND 的 PC 侧导出属于 Future command，不在当前协议中扩展。

当前 CPU1 production Flash build 报告 `FLASH_KERNEL` / `CORE_RAM_LIB`，只公布
ERASE、PROGRAM、VERIFY、RUN、METADATA 和 MEMORY_READ；不公布 RESET、
RAM_LOAD、APP_UPLOAD、UNLOCK_Z1 或 UNLOCK_Z2。RAM development build 报告
`RAM_KERNEL` / `MONOLITHIC`。最近一次 production readback 为：

```text
device_id      = 0x377D
cpu_id         = 1
boot_mode      = 2
kernel_layout  = 2
protocol_ver   = 1
revision_id    = 3
uid_unique     = 3166767
feature_flags  = 1167 / 0x048F
```

其中 `0x048F = ERASE | PROGRAM | VERIFY | RUN | METADATA | MEMORY_READ`。

用户接口采用输出参数，例如：

```c
uint16_t BootUser_CreateDeviceInfo(BootDeviceInfo *info);
```

## 4.2 DSP-facing 返回值大小规则

DSP-facing API 的函数返回值不得超过 32 bits。小标量或不超过 32 bits 的
小结构可以直接返回；超过 32 bits 的信息必须通过输出指针返回，不得按值
返回大结构体。


## 5. Flash-resident core / RAM service lib 分层

Flash-resident core 只负责：

- IO abstraction；
- protocol receive / response send；
- byte-level magic resync；
- Ping / GetDeviceInfo / GetProtocolInfo / GetLastError；
- RamLoadBegin / RamLoadData / RamLoadEnd skeleton；
- service manager / service activation boundary；
- pending RUN entry point getter。

RAM-resident Flash service lib 负责：

- Erase；
- ProgramBegin / ProgramData / ProgramEnd；
- VerifyBegin / VerifyData / VerifyEnd；
- Flash operation session state；
- `BootFlash_*` 调用；
- Flash error mapping；
- Flash command payload validation。

service lib 不复制 `boot_protocol.c`、`boot_io.c`、协议接收循环、response send
逻辑或 core command dispatcher。当前正式 ABI 由 `BootFlashServiceHeader`
定义，`BOOT_FLASH_SERVICE_ABI_MAJOR = 2`。core 在连接 service 前验证
header/descriptor、ABI、header CRC、immutable image CRC、RAM 地址边界和所需
capabilities，然后通过以下函数类型调用 downloaded service：

```text
BootFlashServiceBootInitFn       -> boot_init
BootFlashServiceHandleCommandFn  -> boot_handle_command
```

Flash Service header/descriptor 地址由 PC 从 service linker map/symbol 解析并经
`SERVICE_ATTACH` 发送；bootloader 不硬编码 PC artifact 中的 descriptor 地址。
`SERVICE_ATTACH` 只执行装载结果与 ABI 的验证和连接，不是实际 Flash command
execution。Flash-resident core 不静态链接 F021 或 `flash_service_lib`。

## 6. 协议状态机

RAM service lib 中的 Flash 状态应尽可能小：

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

## 7. Program/Verify/RamLoad 数据规则

`ProgramData`、`VerifyData` 中的 `data_words` 必须为 8 的整数倍。不满足时返回 `BOOT_STATUS_BAD_WORD_COUNT`。

`RamLoadData` 写入 RAM，不使用 Flash 对齐规则。`data_words` 可以是任意正
16-bit word 数，只要求 payload length 有效、地址区间不回绕，并且完整区间
落在生成的 RAM write region 中。

Flash Program 失败后结束 program session，要求重新 Program/DFU。Verify 失败后结束 verify session。

## 8. Run / Reset

Algorithm 不直接跳转 App，也不直接 reset。收到 Run 或 Reset 后先返回 OK response，再向用户外层返回 action。

Reset 要求：先发送 OK response，再由外层执行 reset action。

Phase 5 使用不超过 32-bit 的 `BootAlgorithmAction` 返回
`RUN_FLASH_APP` / `RESET_DEVICE`。用户外层负责真实跳转或复位；algorithm
core 不包含汇编跳转、看门狗复位或器件寄存器操作。core 保存已校验的
RUN entry point，并通过 `BootAlgorithm_GetPendingEntryPoint()` 供用户外层读取。

Phase 7 后，RUN 的实际跳转仍属于 `bootloader_user`。用户层在跳转前必须
再次校验 entry 是否落在 App Flash 范围内，并使用设备/编译器相关的 branch
式跳转实现。RESET 目前不是已启用生产功能；在确定性 reset 策略完成前，
DeviceInfo 不应公布 RESET capability，GUI 也不应开放 Reset 操作。

## 9. Current CPU1 communication timeout and boot reliability policy

当前 CPU1 production baseline 已实现 communication inactivity timeout，但它
不是 hardware Watchdog peripheral interrupt timer，也不是完整工业级 recovery
framework。timeout source 是 CPU Timer2，当前配置为 15000 ms。

Timer2 只在 GUI autobaud/connection 已建立且 protocol session 初始化成功后
启动。因此，未 confirmed 的 App 在 GUI autobaud 前仍无限等待，不存在
pre-autobaud timeout。每个通过 frame、protocol version、packet type、flags 和
CRC 检查的有效 request frame 恰好重载 Timer2 一次；invalid、noise 或
CRC-invalid input 不重载 timeout。

实际 Flash/metadata command 进入 downloaded service 的外层调用边界时使用
统一 critical guard：

```text
valid Flash Service command
-> disable global interrupts and save prior interrupt state
-> stop CPU Timer2
-> call downloaded service boot_handle_command()
-> reload and restart CPU Timer2
-> restore prior interrupt state
```

guard 不分散到每个 F021 erase/program/verify 调用中，downloaded service 内部
也不重复实现 watchdog/Timer guard。`SERVICE_ATTACH` 不经过该 Flash execution
guard，因为它只验证并连接 service，不执行 Flash command。

CPU Timer2 timeout ISR 的唯一恢复动作是强制 device reset。ISR 不扫描
metadata、不计算 `confirmed_bootable`、不 flush SCI，也不直接跳 App。reset 后
bootloader 从头启动、扫描 fresh metadata、调用统一 authority
`BootUser_IsConfirmedBootable()`，再应用正常启动策略。这避免 GUI session 中
metadata 或 App 状态改变后复用旧缓存。

自动跳 App 的唯一条件保持为：

```text
metadata valid
AND IMAGE_VALID valid
AND BOOT_ATTEMPT exists for current image
AND APP_CONFIRMED valid for current image
AND entry point valid
```

未达到 `confirmed_bootable` 时，bootloader 无限等待 GUI autobaud；达到后只
提供有限 GUI takeover/preempt window，窗口内没有 GUI 接管才跳 App。CPU1 App
self-confirm 已实现：App 通过 retained/downloaded Flash Service contract 请求
写入 `APP_CONFIRMED`。bootloader 仍只读 metadata；所有 Flash/metadata 写入仍由
downloaded Flash Service 完成。

App self-confirm、CommTimeout reset/recovery、GUI Auto-PING 和 production
DeviceInfo readback 的 follow-on CPU1 focused hardware validation 已完成。

以下仍延期：

- production protocol RESET command（当前 disabled，且不 advertise RESET）；
- CPU2 与 W5300/TCP；
- A/B slot rollback policy；
- firmware compatibility policy；
- security、signature、encryption 和 production DCSM policy。
