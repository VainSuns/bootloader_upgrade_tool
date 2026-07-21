# Phase 10.8A PC Operation Library 需求冻结清单

## 1. 阶段目标

Phase 10.8A 的目标是新增一套 PC 侧 operation library，供后续 GUI 调用，并为 persistent session、W5300/TCP、CPU2 适配预留清晰边界。

本阶段只做 PC 侧新库分层重构，不替换原 `cpu1_upgrade.py`，不删除原 `UpgradeWorkflow`。

本阶段必须满足：

1. 新增分层库。
2. 保留原 `cpu1_upgrade.py`。
3. 保留原 `UpgradeWorkflow`。
4. 有当前实现可参考的功能，必须优先参考当前实现迁移或封装。
5. GUI 后续调用 operation 层，不调用 protocol primitive。
6. `service attach` 作为 Flash 操作内部细节，不作为 public operation。
7. `verify_flash_image()` 只执行 verify，不写 `IMAGE_VALID`。
8. `IMAGE_VALID -> BOOT_ATTEMPT -> APP_CONFIRMED` 必须按顺序写入。
9. metadata 写入遵循当前 summary 状态、attempt limit 和幂等规则。
10. Image 与当前 metadata 中 App 信息的比较放在 `images/identity.py`，不作为 operation。
11. 本阶段不实现正式 GUI。
12. 本阶段不迁移旧 CLI。
13. 本阶段不实现真实 CPU2 升级流程。
14. 本阶段不实现真实 W5300/TCP transport。

---

## 2. 必须参考的现有文件

实现时必须优先参考以下文件：

```text
pc/src/bootloader_upgrade_tool/core/workflow.py
pc/src/bootloader_upgrade_tool/tools/cpu1_upgrade.py
pc/src/bootloader_upgrade_tool/io/serial_device.py
pc/src/bootloader_upgrade_tool/core/client.py
pc/src/bootloader_upgrade_tool/firmware/
pc/src/bootloader_upgrade_tool/firmware/flash_layout.py
docs/27_app_slot_metadata_header_design.md
dsp/bootloader_common/include/boot_metadata.h
```

参考要求：

1. `erase / program / verify / metadata write` 参考 `workflow.py` 和 `cpu1_upgrade.py`。
2. SCI transport 参考 `serial_device.py`。
3. frame 接收逻辑参考 `core/client.py`。
4. image 解析、service patch、CRC、sector mask 逻辑参考 `firmware/` 和 `firmware/flash_layout.py`。
5. service reuse / service attach 参考当前 `ensure_service_attached()` 和 `UpgradeWorkflow.load_and_attach_service()`。
6. metadata 格式参考 `docs/27_app_slot_metadata_header_design.md` 和 `dsp/bootloader_common/include/boot_metadata.h`。

---

## 3. 禁止修改项

本阶段禁止修改：

```text
DSP bootloader
flash_service_lib DSP 代码
linker cmd
F28377D 底层初始化
Flash sector layout
SCI-A GPIO64/GPIO65 设定
confirmed-only boot policy
原 UpgradeWorkflow
原 cpu1_upgrade.py
```

本阶段禁止执行：

```text
真实串口连接
真实 autobaud
真实 Flash erase
真实 Flash program
真实 Flash verify
真实 metadata write
DSP reset
真实硬件 LED 观察
```

---

## 4. 目录结构

新增或调整后的 PC 侧目录结构如下：

```text
pc/src/bootloader_upgrade_tool/
├─ transport/
│  ├─ __init__.py
│  ├─ base.py
│  └─ serial_transport.py
│
├─ protocol/
│  ├─ frame.py
│  ├─ frame_reader.py
│  ├─ boot_protocol_client.py
│  ├─ command_timeouts.py
│  ├─ constants.py
│  └─ models.py
│
├─ session/
│  ├─ __init__.py
│  └─ session.py
│
├─ targets/
│  ├─ __init__.py
│  ├─ command_sets.py
│  ├─ memory_map.py
│  ├─ profiles.py
│  ├─ cpu1.py
│  └─ cpu2.py
│
├─ images/
│  ├─ __init__.py
│  ├─ models.py
│  ├─ identity.py
│  ├─ flash_image.py
│  ├─ ram_image.py
│  └─ service_image.py
│
└─ operations/
   ├─ __init__.py
   ├─ context.py
   ├─ results.py
   ├─ status_ops.py
   ├─ flash_ops.py
   ├─ metadata_ops.py
   ├─ ram_ops.py
   ├─ execution_ops.py
   ├─ _service_runtime.py
   ├─ _flash_protocol.py
   └─ _ram_protocol.py
```

`tcp_transport.py` 本阶段不做，除非后续单独确认只放 skeleton。

---

## 5. Transport 层

### 5.1 `transport/base.py`

#### 类和异常

```python
class TransportError(RuntimeError): ...
class TransportTimeoutError(TransportError): ...
class TransportClosedError(TransportError): ...

class ByteTransport(Protocol):
    def open(
        self,
        cancellation: CancellationToken | None = None,
    ) -> TransportOpenResult: ...
    def close(self) -> None: ...
    def write_all(self, data: bytes) -> None: ...
    def read_some(self, max_bytes: int) -> bytes: ...
```

#### 要求

`ByteTransport` 只提供 byte stream 能力。

---

### 5.2 `transport/serial_transport.py`

#### 类

```python
@dataclass(frozen=True)
class SerialTransportConfig:
    port: str
    baudrate: int = 9600
    tx_timeout_ms: int = 1000
    rx_timeout_ms: int = 1000
    autobaud_timeout_ms: int = 5000


class SerialTransport(ByteTransport):
    def __init__(
        self,
        config: SerialTransportConfig,
        serial_factory: SerialFactory | None = None,
    ) -> None:
        ...

    def open(
        self,
        cancellation: CancellationToken | None = None,
    ) -> TransportOpenResult: ...
    def close(self) -> None: ...
    def write_all(self, data: bytes) -> None: ...
    def read_some(self, max_bytes: int) -> bytes: ...
```

#### 内部常量

```python
_AUTOBAUD_INTERVAL_MS = 50
_POST_AUTOBAUD_DELAY_MS = 100
_OPEN_SETTLE_MS = 500
```

#### 要求

1. 默认 baudrate 为 `9600`。
2. `autobaud_timeout_ms` 对外暴露，默认 `5000 ms`，允许调整。
3. `autobaud interval / post delay / open settle` 使用内部常量，不作为 public config。
4. `SerialTransport.open()` 内部执行 SCI autobaud。
5. SCI autobaud 使用 ASCII `'A'`，等待 DSP echo `'A'`。
6. pySerial 参数、DTR/RTS 设置、open 后延时参考当前 `SerialIoDevice`。
7. `write_all()` 必须完整写入并 flush。
8. `read_some()` 允许短读。

---

## 6. Protocol 层

### 6.1 `protocol/frame_reader.py`

#### 类

```python
class FrameReader:
    def __init__(self, transport: ByteTransport) -> None:
        ...

    def read_frame(self) -> Frame:
        ...
```

#### 要求

从当前 `ProtocolClient._read_response_frame()` 迁移，不重新设计。

必须保留：

```text
magic sync
dirty byte discard
partial frame buffering
odd byte handling
header CRC check
payload length check
decode_frame
```

---

### 6.2 `protocol/boot_protocol_client.py`

#### 类

```python
class BootProtocolClient:
    def __init__(
        self,
        transport: ByteTransport,
        frame_reader: FrameReader,
    ) -> None:
        ...

    def transact(
        self,
        command: int,
        payload: Sequence[int] = (),
        *,
        timeout_ms: int | None = None,
    ) -> tuple[int, ...]:
        ...
```

#### Command 方法

第一版至少提供：

```python
def ping(self) -> tuple[int, ...]: ...
def get_device_info(self) -> DeviceInfo: ...
def get_protocol_info(self) -> ProtocolInfo: ...
def get_last_error(self) -> ErrorDetail: ...
def get_metadata_summary(self) -> MetadataSummary: ...

def get_service_status(self) -> ServiceStatus: ...
def service_attach(...): ...

def ram_load_begin(...): ...
def ram_load_data(...): ...
def ram_load_end(...): ...
def ram_check_crc(...): ...

def erase(...): ...

def program_begin(...): ...
def program_data(...): ...
def program_end(...): ...

def verify_begin(...): ...
def verify_data(...): ...
def verify_end(...): ...

def metadata_append_image_valid(...): ...
def metadata_append_boot_attempt(...): ...
def metadata_append_app_confirmed(...): ...

def run(...): ...
def reset(...): ...
def run_ram(...): ...
```

#### 要求

1. 发送 frame bytes。
2. 使用 `FrameReader` 接收 response frame。
3. command timeout 使用 `command_timeouts.py`。
4. 方法语义参考当前 `core/client.py`。
5. 不实现 Flash workflow。
6. 不实现 service reuse 判断。
7. 文件命名为 `boot_protocol_client.py`，避免和 session、GUI、tool client 混淆。

---

### 6.3 `protocol/command_timeouts.py`

#### 常量

```python
DEFAULT_COMMAND_TIMEOUT_MS: dict[int, int]
```

#### 要求

从当前 `UpgradeWorkflow._COMMAND_TIMEOUT_MS` 迁移。

本阶段不新增大型 timeout 配置体系。

---

## 7. Session 层

### 7.1 `session/session.py`

#### 类

```python
@dataclass
class UpgradeSessionConfig:
    transport: ByteTransport


class UpgradeSession:
    def __init__(self, config: UpgradeSessionConfig) -> None:
        ...

    def connect(
        self,
        cancellation: CancellationToken | None = None,
    ) -> TransportOpenResult:
        ...

    def disconnect(self) -> None:
        ...

    @property
    def client(self) -> BootProtocolClient:
        ...
```

#### 要求

1. `connect()` 调用 `transport.open()`。
2. `disconnect()` 调用 `transport.close()`。
3. `UpgradeSession` 创建并持有 `BootProtocolClient`。
4. SCI autobaud 不在 session 中单独实现，属于 `SerialTransport.open()`。
5. `UpgradeSession` 不提供 `flash / upgrade / program / verify / run / confirm` 方法。

---

## 8. Targets 层

### 8.1 `targets/memory_map.py`

#### `AddressRange`

```python
@dataclass(frozen=True)
class AddressRange:
    start: int
    end_exclusive: int

    def contains(self, address: int) -> bool: ...
    def contains_range(self, start: int, word_count: int) -> bool: ...
```

地址单位固定为 **C28x word address**。

---

#### `FlashLayout`

```python
@dataclass(frozen=True)
class FlashLayout:
    app_ranges: tuple[AddressRange, ...]
    allowed_erase_mask: int
    forbidden_erase_mask: int
    metadata_sector_mask: int
```

字段含义：

```text
app_ranges:
  允许 Flash App 放置的地址范围。

allowed_erase_mask:
  允许擦除的 Flash sector mask。

forbidden_erase_mask:
  禁止擦除的 Flash sector mask，例如 bootloader / Sector A。

metadata_sector_mask:
  metadata 所在 sector mask。
  当前 App 和 metadata 共用 sector 时，erase_flash_image_area() 使用该字段先擦共用 sector。
```

---

#### `RamLayout`

```python
@dataclass(frozen=True)
class RamLayout:
    service_ranges: tuple[AddressRange, ...]
    ram_app_ranges: tuple[AddressRange, ...]
    reserved_ranges: tuple[AddressRange, ...]
```

字段含义：

```text
service_ranges:
  downloaded flash_service_lib 允许加载的 RAM 范围。

ram_app_ranges:
  RAM App / RUN_RAM image 允许加载和运行的 RAM 范围。

reserved_ranges:
  不允许 RAM image 覆盖的 RAM 范围。
```

---

#### `MetadataLayout`

```python
@dataclass(frozen=True)
class MetadataLayout:
    range: AddressRange
    sector_mask: int
    record_alignment_words: int
```

字段含义：

```text
range:
  metadata record 所在地址范围。

sector_mask:
  metadata 所在 Flash sector mask。

record_alignment_words:
  metadata record 对齐要求。
```

---

#### `TargetMemoryMap`

```python
@dataclass(frozen=True)
class TargetMemoryMap:
    flash: FlashLayout | None = None
    ram: RamLayout | None = None
    metadata: MetadataLayout | None = None
```

---

### 8.2 `targets/command_sets.py`

#### 类

```python
@dataclass(frozen=True)
class CommandSet:
    ping: int | None = None
    get_device_info: int | None = None
    get_protocol_info: int | None = None
    get_last_error: int | None = None
    get_service_status: int | None = None
    service_attach: int | None = None

    ram_load_begin: int | None = None
    ram_load_data: int | None = None
    ram_load_end: int | None = None
    ram_check_crc: int | None = None
    run_ram: int | None = None

    erase: int | None = None
    program_begin: int | None = None
    program_data: int | None = None
    program_end: int | None = None
    verify_begin: int | None = None
    verify_data: int | None = None
    verify_end: int | None = None

    get_metadata_summary: int | None = None
    metadata_append_record: int | None = None

    run: int | None = None
    reset: int | None = None
    boot_cpu2_run_cpu1: int | None = None
    boot_cpu2_reset_cpu1: int | None = None
```

#### Helper

```python
class UnsupportedOperationError(RuntimeError):
    pass


def require_command(command_set: CommandSet, field_name: str) -> int:
    ...
```

`require_command()` 行为：

```text
1. 从 command_set 读取指定字段。
2. 如果字段为 None，抛 UnsupportedOperationError。
3. 如果字段存在，返回 int command id。
```

---

### 8.3 `targets/profiles.py`

#### 类

```python
@dataclass(frozen=True)
class TargetProfile:
    name: str
    cpu_id: int
    command_set: CommandSet
    memory_map: TargetMemoryMap
```

---

### 8.4 `targets/cpu1.py`

#### 内容

```python
CPU1_COMMAND_SET: CommandSet
CPU1_MEMORY_MAP: TargetMemoryMap
CPU1_PROFILE: TargetProfile
```

#### 要求

CPU1 profile 使用当前 TMS320F28377D CPU1 Flash / RAM / metadata 规则。

---

### 8.5 `targets/cpu2.py`

#### 内容

```python
CPU2_COMMAND_SET: CommandSet
CPU2_MEMORY_MAP: TargetMemoryMap
CPU2_PROFILE: TargetProfile
```

#### 要求

CPU2 本阶段只做 skeleton，不实现真实 CPU2 升级流程。

---

## 9. Images 层

### 9.1 `images/models.py`

#### 类

```python
@dataclass(frozen=True)
class ImageIdentity:
    entry_point: int
    image_size_words: int
    image_crc32: int
    app_end: int


@dataclass(frozen=True)
class PreparedFlashImage:
    image: FirmwareImage
    identity: ImageIdentity
    sector_mask: int
    generated_sci8_txt: str | None = None


@dataclass(frozen=True)
class PreparedRamImage:
    image: FirmwareImage
    entry_point: int
    total_words: int
    image_crc32: int
    generated_sci8_txt: str | None = None


@dataclass(frozen=True)
class PreparedServiceImage:
    image: FirmwareImage
    descriptor_address: int
    api_table_address: int
    crc_patch_address: int
    total_words: int
    expected_crc32: int
    required_capabilities: int
```

---

### 9.2 `images/identity.py`

#### 类

```python
@dataclass(frozen=True)
class ImageMetadataComparison:
    same_image: bool
    metadata_valid: bool
    mismatches: tuple[str, ...]
    reason: str | None = None
```

#### 函数

```python
def compare_image_identity_with_metadata(
    image_identity: ImageIdentity,
    metadata_summary: MetadataSummary,
) -> ImageMetadataComparison:
    ...


def compare_flash_image_with_metadata(
    image: PreparedFlashImage,
    metadata_summary: MetadataSummary,
) -> ImageMetadataComparison:
    ...
```

#### 对比规则

```text
1. 如果 metadata_summary.metadata_valid == 0:
   same_image = False
   reason = "METADATA_INVALID"

2. 必须比较 entry_point。
3. 必须比较 image_size_words。
4. 必须比较 image_crc32。
5. 如果 target_device_id / target_cpu_id 可用，也可以比较。
6. 不比较 app_end。
7. 所有必选字段一致:
   same_image = True
   reason = None
8. 任一必选字段不一致:
   same_image = False
   reason = "IMAGE_IDENTITY_MISMATCH"
   mismatches 记录字段名。
```

#### 重要说明

metadata record 和 C summary struct 中存在 `app_end`，但当前 `GET_METADATA_SUMMARY` payload 没有暴露 `app_end`，当前 PC `MetadataSummary` model 也没有 `app_end` 字段。因此 Phase 10.8A 不修改 DSP protocol payload，PC 侧 image/metadata 比较不比较 `app_end`。

---

### 9.3 `images/flash_image.py`

#### 函数

```python
def prepare_flash_app_image(
    app_image_path: str | Path,
    *,
    target: TargetProfile,
    hex2000: str | None = None,
    sci8_txt: str | Path | None = None,
    keep_sci8_txt: bool = False,
) -> PreparedFlashImage:
    ...
```

#### 要求

参考当前：

```text
_load_image()
calculate_app_identity()
calculate_app_sector_mask()
validate_sector_mask_for_image()
```

必须使用：

```text
target.memory_map.flash
target.memory_map.metadata
```

完成：

```text
Flash App 地址范围校验
entry point 校验
sector_mask 计算
forbidden sector 校验
metadata sector 规则检查
```

---

### 9.4 `images/ram_image.py`

#### 函数

```python
def prepare_ram_app_image(
    ram_image_path: str | Path,
    *,
    target: TargetProfile,
    hex2000: str | None = None,
    sci8_txt: str | Path | None = None,
    keep_sci8_txt: bool = False,
) -> PreparedRamImage:
    ...
```

#### 要求

参考当前 RAM image 解析和 `validate_ram_firmware_image()` 逻辑。

必须使用：

```text
target.memory_map.ram
```

完成：

```text
RAM App load range 校验
RAM App entry point 校验
reserved RAM 覆盖检查
service RAM 冲突检查
RAM image CRC 计算
```

---

### 9.5 `images/service_image.py`

#### 函数

```python
def prepare_service_image(
    service_image_path: str | Path,
    service_map_path: str | Path,
    *,
    target: TargetProfile,
    descriptor_symbol: str = "g_boot_flash_service_descriptor",
    hex2000: str | None = None,
    required_capabilities: int = int(SERVICE_REQUIRED_CAPABILITIES),
) -> PreparedServiceImage:
    ...
```

#### 要求

参考当前：

```text
_prepare_service_image()
parse_flash_service_symbols_from_map()
patch_flash_service_image()
calculate_service_ram_load_crc32_descriptor_last()
```

必须使用：

```text
target.memory_map.ram
```

完成：

```text
flash_service_lib service_ranges 校验
descriptor address 合法性校验
reserved RAM 覆盖检查
descriptor patch
expected_crc32 计算
```

`required_capabilities` 不从 map 文件猜测。默认使用当前仓库已有的 `SERVICE_REQUIRED_CAPABILITIES`。`PreparedServiceImage` 保存 `required_capabilities`，`ensure_service_attached()` 使用 `ctx.service.required_capabilities` 校验 attached service。

---

## 10. Operations 层

### 10.1 `operations/context.py`

#### 类

```python
@dataclass
class OperationContext:
    session: UpgradeSession
    target: TargetProfile
    progress: ProgressCallback | None = None
    cancellation: CancellationToken | None = None


@dataclass
class FlashOperationContext(OperationContext):
    service: PreparedServiceImage
    force_service_attach: bool = False
```

#### 要求

1. 不定义 `RamOperationContext`。
2. RAM ops 直接使用 `OperationContext`。
3. image 信息放在 Request 中，不放在 Context 中。
4. `FlashOperationContext.service` 是 Flash 操作必要输入。
5. GUI/CLI 不直接调用 service attach。

---

### 10.2 `operations/results.py`

#### 类

```python
@dataclass(frozen=True)
class OperationErrorInfo:
    code: str
    message: str
    stage: str
    recoverable: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OperationResult:
    ok: bool
    operation: str
    target: str
    stage: str
    summary: dict[str, Any]
    details: dict[str, Any] = field(default_factory=dict)
    service: dict[str, Any] | None = None
    warning: dict[str, Any] | None = None
    error: OperationErrorInfo | None = None
    completion: OperationCompletion | None = None
    cancellation: OperationCancellationInfo | None = None


@dataclass(frozen=True)
class ProgressEvent:
    operation: str
    target: str
    stage: str
    message: str
    current_words: int | None = None
    total_words: int | None = None
    chunk_words: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    cancellation_supported: bool = False
```

#### Helper

```python
def operation_result_to_dict(result: OperationResult) -> dict[str, Any]:
    ...
```

#### `OperationResult` 成功要求

1. 所有 public ops 返回 `OperationResult`。
2. `summary` 放 GUI/CLI 常用结果。
3. `details` 放 mask、packet、block 等调试细节。
4. `service` 放内部 service attach/reuse 摘要。
5. 成功时 `error = None`。
6. metadata ops 的 `summary` 必须体现 `written / already_exists / reason`。

#### `OperationResult` 错误要求

以下属于 known fatal error：

```text
transport open/read/write 失败
protocol transact 失败
DSP 返回错误 status
service attach 失败
service ABI / capability 校验失败
erase/program/verify command 失败
metadata append command 失败
forbidden sector 校验失败
unsupported command
```

known fatal error 时：

```text
1. 当前 operation 不继续执行后续步骤。
2. public operation 捕获已知 typed exception。
3. 返回 OperationResult(ok=False, error=OperationErrorInfo(...))。
4. unknown programming error 不强行吞掉，可以继续抛出。
```

#### 非错误业务状态

以下情况返回 `ok=True`：

```text
IMAGE_VALID_ALREADY_EXISTS
APP_CONFIRMED_ALREADY_EXISTS
IMAGE_VALID_REQUIRED
BOOT_ATTEMPT_REQUIRED
BOOT_ATTEMPT_LIMIT_REACHED
IMAGE_IDENTITY_MISMATCH
METADATA_INVALID
```

这些是业务状态，不是 transport/protocol 执行错误。

---

### 10.3 `operations/status_ops.py`

#### 函数

```python
def get_device_info(ctx: OperationContext) -> OperationResult: ...
def get_protocol_info(ctx: OperationContext) -> OperationResult: ...
def get_last_error(ctx: OperationContext) -> OperationResult: ...
def get_metadata_summary(ctx: OperationContext) -> OperationResult: ...
```

#### 要求

1. `get_metadata_summary()` 保持在 `status_ops.py`。
2. `get_metadata_summary()` 不需要注入 flash_lib。
3. `get_metadata_summary()` 是 bootloader resident protocol 的只读状态查询。
4. 不提供 `get_service_status_for_diagnostics()`。

---

### 10.4 `operations/flash_ops.py`

#### Request 类

```python
@dataclass(frozen=True)
class EraseFlashImageAreaRequest:
    image: PreparedFlashImage


@dataclass(frozen=True)
class EraseSectorMaskRequest:
    sector_mask: int


@dataclass(frozen=True)
class ProgramFlashImageRequest:
    image: PreparedFlashImage


@dataclass(frozen=True)
class VerifyFlashImageRequest:
    image: PreparedFlashImage
```

#### 函数

```python
def erase_flash_image_area(
    ctx: FlashOperationContext,
    request: EraseFlashImageAreaRequest,
) -> OperationResult:
    ...


def erase_sector_mask(
    ctx: FlashOperationContext,
    request: EraseSectorMaskRequest,
) -> OperationResult:
    ...


def program_flash_image(
    ctx: FlashOperationContext,
    request: ProgramFlashImageRequest,
) -> OperationResult:
    ...


def verify_flash_image(
    ctx: FlashOperationContext,
    request: VerifyFlashImageRequest,
) -> OperationResult:
    ...
```

#### 行为要求

```text
erase_flash_image_area:
  ensure_service_attached()
  固定先擦 metadata/App 共用 sector
  再擦 App 其它 sector
  不 program
  不 verify
  不写 metadata

erase_sector_mask:
  ensure_service_attached()
  按指定 sector_mask 擦除
  保护 forbidden sector

program_flash_image:
  ensure_service_attached()
  PROGRAM_BEGIN / PROGRAM_DATA / PROGRAM_END
  不 erase
  不 verify
  不写 IMAGE_VALID

verify_flash_image:
  ensure_service_attached()
  VERIFY_BEGIN / VERIFY_DATA / VERIFY_END
  不写 IMAGE_VALID
```

`verify_flash_image()` 会调用 flash API，因此必须 attach service。

---

### 10.5 `operations/metadata_ops.py`

#### Request 类

```python
@dataclass(frozen=True)
class AppendImageValidRequest:
    image: PreparedFlashImage


@dataclass(frozen=True)
class AppendBootAttemptRequest:
    pass


@dataclass(frozen=True)
class AppendAppConfirmedRequest:
    pass
```

#### 函数

```python
def append_image_valid(
    ctx: FlashOperationContext,
    request: AppendImageValidRequest,
) -> OperationResult:
    ...


def append_boot_attempt(
    ctx: FlashOperationContext,
    request: AppendBootAttemptRequest,
) -> OperationResult:
    ...


def append_app_confirmed(
    ctx: FlashOperationContext,
    request: AppendAppConfirmedRequest,
) -> OperationResult:
    ...
```

#### 通用要求

1. 三者都必须 `ensure_service_attached()`。
2. 三者都只写对应 metadata record。
3. 三者都不自动写其它 metadata record。
4. 三者都不 run。
5. `metadata_ops.py` 不包含 `get_metadata_summary()`。
6. `metadata_ops.py` 不包含 `compare_image_with_metadata()`。
7. metadata 写入顺序为：

```text
IMAGE_VALID -> BOOT_ATTEMPT -> APP_CONFIRMED
```

#### `append_image_valid()` 行为

```text
1. ensure_service_attached()
2. get_metadata_summary()
3. 如果 metadata 已有有效 IMAGE_VALID：
   - 不写入
   - 返回 already_exists
4. 如果 metadata state 不是 EMPTY：
   - 不写入
   - 返回 METADATA_INVALID
5. 只有 EMPTY state 才写 request.image 对应的 IMAGE_VALID
```

summary 规则：

```json
{
  "written": true,
  "already_exists": false,
  "reason": null
}
```

或：

```json
{
  "written": false,
  "already_exists": true,
  "reason": "IMAGE_VALID_ALREADY_EXISTS"
}
```

#### `append_boot_attempt()` 行为

```text
1. ensure_service_attached()
2. get_metadata_summary()
3. metadata invalid 时返回 METADATA_INVALID
4. 缺少当前 IMAGE_VALID 时返回 IMAGE_VALID_REQUIRED
5. boot_attempt_limit 必须在 1..3
6. 已有 APP_CONFIRMED 时不写入并返回 APP_CONFIRMED_ALREADY_EXISTS
7. attempt count 达到 limit 或 3 时返回 BOOT_ATTEMPT_LIMIT_REACHED
8. 否则使用当前 summary identity 追加一个 BOOT_ATTEMPT
```

#### `append_app_confirmed()` 行为

```text
1. ensure_service_attached()
2. get_metadata_summary()
3. metadata invalid 时返回 METADATA_INVALID
4. 检查当前 metadata 是否存在 IMAGE_VALID 和 BOOT_ATTEMPT
5. 如果 IMAGE_VALID 不存在：
   - 不写入
   - 返回 IMAGE_VALID_REQUIRED
6. 如果没有 BOOT_ATTEMPT：
   - 不写入
   - 返回 BOOT_ATTEMPT_REQUIRED
7. 如果当前 image 已有 APP_CONFIRMED：
   - 不写入
   - 返回 already_exists
8. 否则使用当前 summary identity 写 APP_CONFIRMED
```

---

### 10.6 `operations/ram_ops.py`

#### Request 类

```python
@dataclass(frozen=True)
class LoadRamImageRequest:
    image: PreparedRamImage


@dataclass(frozen=True)
class CheckRamCrcRequest:
    image: PreparedRamImage
```

#### 函数

```python
def load_ram_image(
    ctx: OperationContext,
    request: LoadRamImageRequest,
) -> OperationResult:
    ...


def check_ram_crc(
    ctx: OperationContext,
    request: CheckRamCrcRequest,
) -> OperationResult:
    ...
```

#### 行为要求

```text
load_ram_image:
  RAM_LOAD_BEGIN / RAM_LOAD_DATA / RAM_LOAD_END
  不 RUN_RAM

check_ram_crc:
  RAM_CHECK_CRC
```

---

### 10.7 `operations/execution_ops.py`

#### Request 类

```python
@dataclass(frozen=True)
class RunFlashAppRequest:
    entry_point: int


@dataclass(frozen=True)
class RunRamImageRequest:
    entry_point: int


@dataclass(frozen=True)
class ResetTargetRequest:
    pass


@dataclass(frozen=True)
class BootCpu2RunCpu1Request:
    pass


@dataclass(frozen=True)
class BootCpu2ResetCpu1Request:
    pass
```

#### 函数

```python
def run_flash_app(
    ctx: OperationContext,
    request: RunFlashAppRequest,
) -> OperationResult:
    ...


def run_ram_image(
    ctx: OperationContext,
    request: RunRamImageRequest,
) -> OperationResult:
    ...


def reset_target(
    ctx: OperationContext,
    request: ResetTargetRequest,
) -> OperationResult:
    ...


def boot_cpu2_run_cpu1(
    ctx: OperationContext,
    request: BootCpu2RunCpu1Request,
) -> OperationResult:
    ...


def boot_cpu2_reset_cpu1(
    ctx: OperationContext,
    request: BootCpu2ResetCpu1Request,
) -> OperationResult:
    ...
```

#### 行为要求

```text
run_flash_app:
  只发送 RUN
  不自动写 BOOT_ATTEMPT

run_ram_image:
  只发送 RUN_RAM
  不自动 load_ram_image
  不自动 check_ram_crc

reset_target:
  只发送 RESET

boot_cpu2_*:
  本阶段只做 command 发送
  不做 CPU2 完整升级流程
```

---

### 10.8 `operations/_service_runtime.py`

#### 类 / 函数

```python
@dataclass(frozen=True)
class ServiceRuntimeSummary:
    reused: bool
    attach_performed: bool
    service_state: int
    service_major: int
    service_minor: int
    capabilities: int
    loaded_image_crc32: int


def ensure_service_attached(ctx: FlashOperationContext) -> ServiceRuntimeSummary:
    ...
```

#### 行为要求

必须实现：

```text
GET_SERVICE_STATUS
service reuse 判断
RAM_LOAD service
RAM_CHECK_CRC
SERVICE_ATTACH
attached status 校验
ABI / capability 校验
```

普通 GUI/CLI 不直接调用 `ensure_service_attached()`。

`ensure_service_attached()` 使用 `ctx.service.required_capabilities` 校验 attached service。不得从 map 文件猜测 capability。

---

### 10.9 `operations/_flash_protocol.py`

#### 函数

```python
def erase_protocol(...): ...
def program_begin_protocol(...): ...
def program_data_protocol(...): ...
def program_end_protocol(...): ...
def verify_begin_protocol(...): ...
def verify_data_protocol(...): ...
def verify_end_protocol(...): ...
```

#### 要求

参考当前 `UpgradeWorkflow.erase()` 和 `_transfer()`。

---

### 10.10 `operations/_ram_protocol.py`

#### 函数

```python
def ram_load_begin_protocol(...): ...
def ram_load_data_protocol(...): ...
def ram_load_end_protocol(...): ...
def ram_check_crc_protocol(...): ...
```

#### 要求

参考当前 `UpgradeWorkflow.ram_load()` 和 service RAM load。

---

## 11. Progress 要求

以下阶段必须通过 `ProgressEvent` 上报：

```text
RAM_LOAD_SERVICE
PROGRAM_DATA
VERIFY_DATA
RAM_LOAD_DATA
```

必须填写：

```text
current_words
total_words
chunk_words
```

速度由 GUI 根据事件时间差计算。ops 层不计算速度。

C28x word 为 16-bit，SCI 发送顺序为 low byte then high byte。GUI 可按：

```text
bytes = words * 2
```

换算传输速度。

---

## 12. Timeout 要求

本阶段不新增 timeout 配置体系。

要求：

```text
1. 使用 protocol/command_timeouts.py 内部常量。
2. 常量从当前 UpgradeWorkflow._COMMAND_TIMEOUT_MS 迁移。
3. OperationContext 不包含 timeout。
4. GUI/CLI 不需要为每个 operation 传 timeout。
5. Serial transport 只暴露 tx_timeout_ms、rx_timeout_ms、autobaud_timeout_ms。
```

---

## 13. Tools 要求

```text
1. 原 tools/cpu1_upgrade.py 保留。
2. 本阶段不迁移旧 CLI。
3. 本阶段不实现正式 GUI。
4. 本阶段不实现 persistent CLI，除非后续单独确认。
```

---

## 14. GUI/CLI 后续组合方式

### 14.1 Flash App

后续 GUI/CLI 组合：

```text
prepare_flash_app_image
prepare_service_image
erase_flash_image_area
program_flash_image
verify_flash_image
append_image_valid
```

GUI/CLI 不直接处理：

```text
service attach
program_begin/data/end
verify_begin/data/end
metadata/App 共用 sector 擦除顺序
```

---

### 14.2 Image 与当前 App 比较

后续 GUI/CLI 组合：

```text
prepare_flash_app_image
get_metadata_summary
compare_flash_image_with_metadata
```

该比较为 PC 本地判断，不属于 operation。

---

### 14.3 Run App

后续 GUI/CLI 组合：

```text
get_metadata_summary
append_boot_attempt
run_flash_app
```

`run_flash_app()` 不自动写 `BOOT_ATTEMPT`。

---

### 14.4 Confirm App

后续 GUI/CLI 组合：

```text
get_metadata_summary
append_app_confirmed
```

`append_app_confirmed()` 内部检查是否存在当前 image 的 `IMAGE_VALID` 和 `BOOT_ATTEMPT`。

---

## 15. 测试要求

必须新增单元测试覆盖：

```text
1. SerialTransport 行为参考 SerialIoDevice。
2. SerialTransport 默认 baudrate = 9600。
3. SerialTransport 暴露 autobaud_timeout_ms，默认 5000 ms。
4. FrameReader 保留 magic sync / dirty byte discard / partial frame。
5. BootProtocolClient 可发送 command 并通过 FrameReader 接收。
6. CPU1 TargetProfile 可创建。
7. CPU2 TargetProfile skeleton 可创建。
8. FlashLayout / RamLayout / MetadataLayout 字段可用于 image 检查。
9. require_command 成功和 unsupported cases。
10. prepare_flash_app_image 使用 target.memory_map。
11. prepare_ram_app_image 使用 target.memory_map。
12. prepare_service_image 使用 target.memory_map。
13. prepare_service_image 保存 required_capabilities。
14. compare_image_identity_with_metadata 在 metadata invalid 时返回 same_image=false。
15. compare_image_identity_with_metadata 在 entry_point 不一致时返回 mismatches 包含 entry_point。
16. compare_image_identity_with_metadata 在 image_size_words 不一致时返回 mismatches 包含 image_size_words。
17. compare_image_identity_with_metadata 在 image_crc32 不一致时返回 mismatches 包含 image_crc32。
18. compare_image_identity_with_metadata 不要求 MetadataSummary 提供 app_end。
19. compare_flash_image_with_metadata 正确调用 image.identity。
20. get_metadata_summary 位于 status_ops.py。
21. metadata_ops.py 不包含 get_metadata_summary。
22. metadata_ops.py 不包含 compare_image_with_metadata。
23. erase_flash_image_area 内部调用 ensure_service_attached。
24. erase_flash_image_area 使用固定擦除顺序。
25. erase_sector_mask 保护 forbidden sector。
26. program_flash_image 内部调用 ensure_service_attached。
27. verify_flash_image 内部调用 ensure_service_attached。
28. verify_flash_image 不调用 metadata append。
29. append_image_valid 已存在时返回 already_exists。
30. append_boot_attempt 缺少 IMAGE_VALID 时不写入。
31. append_boot_attempt 可重复追加到 limit；达到 limit 时不写入。
32. append_app_confirmed 缺少 IMAGE_VALID 时不写入。
33. append_app_confirmed 缺少 BOOT_ATTEMPT 时不写入。
34. append_app_confirmed 已存在时返回 already_exists。
35. RAM_LOAD_SERVICE / PROGRAM_DATA / VERIFY_DATA / RAM_LOAD_DATA 发 ProgressEvent。
36. OperationResult 字段统一。
37. OperationResult.error 使用 OperationErrorInfo。
38. operation_result_to_dict 正确序列化 OperationResult。
39. known fatal error 返回 OperationResult(ok=False)。
40. fatal error 后不继续执行后续步骤。
41. 原 cpu1_upgrade CLI 单元测试不回归。
```

验证命令：

```powershell
.\.venv\Scripts\python.exe -m py_compile <modified files>
.\.venv\Scripts\python.exe -m pytest tests/unit/test_cpu1_upgrade_cli.py -q
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

---

## 16. 一致性检查与风险答复冻结

### 16.1 分层一致性

当前分层职责：

```text
transport:
  byte stream

protocol:
  frame / command

session:
  connection lifecycle

targets:
  command set / memory map

images:
  local image preparation and image identity comparison

operations:
  GUI/CLI direct operations

internal helpers:
  service runtime and protocol primitive wrapping

tools:
  old CLI retained
```

### 16.2 `get_metadata_summary()` 归属

`get_metadata_summary()` 保持在 `status_ops.py`。

原因：

```text
1. 它是 bootloader resident protocol 只读查询。
2. 它不需要 flash_service_lib。
3. 它不写 metadata。
4. 它用于 GUI/CLI 状态显示和后续 orchestration 判断。
```

### 16.3 Image 对比功能归属

Image 与 metadata 的一致性判断放在 `images/identity.py`。

原因：

```text
1. 对比动作不需要 DSP 通信。
2. 不需要 session。
3. 不需要 protocol。
4. 不需要 flash_service_lib。
5. 不应作为 operation。
```

### 16.4 Context 设计

只保留：

```text
OperationContext
FlashOperationContext
```

不定义 `RamOperationContext`。

### 16.5 `OperationResult.error` 表达方式

Python 内部统一使用 `OperationErrorInfo` dataclass 表示错误信息。

GUI、日志、JSON 输出时，通过 `operation_result_to_dict()` 转换为 dict。

规则：

```text
known fatal error:
  public operation 捕获并返回 OperationResult(ok=False, error=OperationErrorInfo(...))

unknown programming error:
  不强行吞掉，可以继续抛出
```

### 16.6 `CommandSet` 与 `BootProtocolClient` 关系

冻结为：

```text
BootProtocolClient 只发送 int command id。
operation 层必须通过 ctx.target.command_set 获取 command id。
operation 层不得直接硬编码 Command enum。
```

`Command` enum 可以继续作为 CPU1 默认 `CommandSet` 的来源，但 operation 层以 `ctx.target.command_set` 为准。

### 16.7 `PreparedServiceImage.required_capabilities` 来源

`required_capabilities` 不从 map 文件猜测。

默认值使用当前仓库已有的 `SERVICE_REQUIRED_CAPABILITIES`。

执行规则：

```text
1. required_capabilities 默认使用 SERVICE_REQUIRED_CAPABILITIES。
2. prepare_service_image() 保存 required_capabilities 到 PreparedServiceImage。
3. ensure_service_attached() 使用 ctx.service.required_capabilities 校验 attached service。
4. 不从 map 文件猜测 capability。
5. 不新增未验证 capability 解析逻辑。
```

### 16.8 Metadata 格式与 `app_end` 比较规则

metadata record 格式以仓库文档和头文件为准：

```text
docs/27_app_slot_metadata_header_design.md
dsp/bootloader_common/include/boot_metadata.h
```

冻结结论：

```text
1. metadata record 中存在 app_end。
2. C BootMetadataSummary struct 中存在 app_end。
3. 当前 GET_METADATA_SUMMARY payload 没有暴露 app_end。
4. 当前 PC MetadataSummary model 没有 app_end 字段。
5. Phase 10.8A 不修改 DSP protocol payload。
6. compare_image_identity_with_metadata() 不比较 app_end。
```

### 16.9 最终审核结论

该需求清单整体一致，可以作为 Phase 10.8A 的冻结版基础。

最终冻结结论：

```text
1. transport 只做 byte stream。
2. protocol 只做 frame/command。
3. session 只做连接生命周期。
4. images 做 image preparation 和 image/metadata identity comparison。
5. status_ops 做只读状态查询，包括 get_metadata_summary。
6. metadata_ops 只做 metadata 写入。
7. flash_ops / metadata_ops 内部自动 ensure_service_attached。
8. verify_flash_image 不写 IMAGE_VALID。
9. metadata 写入严格按 IMAGE_VALID -> BOOT_ATTEMPT -> APP_CONFIRMED 顺序。
10. OperationResult.error 使用 OperationErrorInfo。
11. service required_capabilities 默认使用 SERVICE_REQUIRED_CAPABILITIES。
12. 当前 GET_METADATA_SUMMARY payload 不暴露 app_end。
13. Phase 10.8A 不修改 DSP protocol payload。
14. image/metadata 比较不比较 app_end。
15. 旧 CLI 保留，不迁移。
```

---

## 17. Reliability hardening

### 17.0 Downloaded-service descriptor-last CRC contract

Downloaded service materialization and transfer preserve this ordering:

```text
1. Pre-invalidate descriptor magic before loading the formal image.
2. Send all non-descriptor words first.
3. Send the descriptor/header last so a partial transfer cannot appear valid.
4. Calculate CRC in the formal service receive order, including descriptor-last ordering.
5. Exclude the descriptor-magic invalidation transaction from the formal image CRC.
6. Use the same formal service CRC for RAM_CHECK_CRC and SERVICE_ATTACH.
```

The pre-invalidation write is a safety transaction outside the formal service
image. Descriptor/header-last ordering is part of the service image identity
and must not be replaced with ordinary address-order CRC calculation.

### 17.1 Transport and session open result

`ByteTransport.open(cancellation=None)` and
`UpgradeSession.connect(cancellation=None)` return a typed
`TransportOpenResult`:

```text
OPENED
  resource_released = false

CANCELLED
  resource_released = true
  stage identifies the cooperative cancellation boundary
```

`CancellationToken` is read-only and exposes only
`is_cancel_requested()`. The caller owns the mutable cancellation source;
transport, session, protocol, and operation code only observe it.

### 17.2 Protocol capability ownership and discovery

`BootProtocolClient` owns the connected session's cached `DeviceInfo` and
`ProtocolInfo`, plus the negotiated effective limits:

```text
effective_max_payload_words
effective_max_data_words
effective_max_write_data_words
```

Persistent-session initialization requires both `GET_DEVICE_INFO` and
`GET_PROTOCOL_INFO`. `discover_connected_target()` performs both, validates
the identity and protocol data, and returns the active `TargetProfile`.
`GET_DEVICE_INFO` alone is not sufficient before non-bootstrap operations.

One complete `transact()` call, including request write and response read, is
protected by the client transaction lock. Cancellation is checked only at
operation-defined safe boundaries; an active protocol transaction is not
interrupted.

### 17.3 Operation cancellation contract

`OperationContext.cancellation` and inherited
`FlashOperationContext.cancellation` accept the read-only token.
`OperationResult.completion` distinguishes:

```text
SUCCEEDED
FAILED
CANCELLED
COMPLETED_AFTER_CANCEL_REQUEST
```

Cancellation evidence is carried by `OperationCancellationInfo`, including
the stage, progress counts, protocol cleanup state, partial-program state, and
caller recovery action. `ProgressEvent.cancellation_supported` means the
previous DATA transaction completed and the event is a safe cooperative
cancellation boundary; it does not permit interruption of the active
transaction.

After a partial RAM, service, Program, or Verify transfer, cancellation sends
the matching END command once using the original total packet/word counts.
`TOTAL_COUNT_MISMATCH` from that cleanup END means the DSP discarded the
partial session and is therefore accepted as clean cancellation cleanup.
Other cleanup failures require reconnect recovery.

If any Program DATA was accepted before cancellation, retry requires erase
before Program restarts. The library reports this through
`partial_flash_programmed`, `erase_before_retry_required`, and a recovery
action such as `ERASE_AND_RESTART_PROGRAM` or
`RECONNECT_ERASE_AND_RESTART_PROGRAM`; it does not erase or retry
automatically.

### 17.4 GUI persistent Connect cancellation

The GUI Connect task passes its existing read-only token unchanged to
`UpgradeSession.connect()`. It accepts only a valid `TransportOpenResult`.
Open-stage cancellation does not start target discovery or close an already
released resource again.

After `OPENED`, the GUI checks cancellation before target discovery and again
after the atomic discovery unit completes but before committing persistent
session state. Cancellation cleanup runs synchronously on the connection
worker. Clean cleanup returns `CANCELLED`; cleanup failure returns
`FAILED / CONNECT_CANCELLATION_CLEANUP_FAILED`, clears advertised connection
state, and retains retryable cleanup state for the next Connect attempt.
Ordinary discovery or protocol failure takes precedence over a concurrent
cancellation request.
