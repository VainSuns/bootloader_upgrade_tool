# TMS320F28377D Bootloader Upgrade Tool
# Runtime Architecture Contract V2

```text
Document ID: RAC-V2
Version: 2.0
Language: Chinese
Repository: VainSuns/bootloader_upgrade_tool
Repository baseline reviewed: f1e59f07bd2e8fd8e872a99d6e592c9c9ea4a275
Approved date: 2026-07-16
Target device: TMS320F28377D
GUI stack: Python 3.12 + PySide6 6.8+
Status: FROZEN
```

---

## 1. 文档目的与权威性

本合同定义 PC GUI Runtime V2 的长期架构边界、状态所有权、资源生命周期、持久化范围、事件模型、操作门禁、证据失效规则、连接维护扩展点以及后续功能的扩展方式。

本合同的目标不是只让当前 CPU1 功能工作，而是确保以下已知后续功能可以通过新增 Provider、Policy、Adapter、Profile、Workflow 或 Operation 接入，而不再大范围重写已验证代码：

```text
CPU2 runtime
W5300 TCP transport
connection ping / keepalive
双 CPU Program workflow
Reset
Image 文件监视
InstalledResourceProvider / 打包
后续新的 Target 或 transport
```

### 1.1 适用范围

本合同适用于：

```text
pc/src/bootloader_upgrade_tool/gui/
pc/src/bootloader_upgrade_tool/session/
pc/src/bootloader_upgrade_tool/images/
pc/src/bootloader_upgrade_tool/operations/
pc/src/bootloader_upgrade_tool/targets/
pc/src/bootloader_upgrade_tool/transport/
pc/src/bootloader_upgrade_tool/protocol/
相关单元测试和架构文档
```

### 1.2 不覆盖的稳定合同

以下内容继续由现有稳定合同约束，本合同不得改变：

```text
TMS320F28377D 为默认目标芯片
用户维护 DSP 底层初始化和 linker cmd
Flash-resident bootloader 不静态链接 F021 或 flash_service_lib
bootloader 只读 metadata
Flash / metadata 写入由 downloaded flash_lib 完成
PC 是 master，DSP 是 slave
SCI-A 使用 GPIO64/GPIO65，经 RS232
SCI word 低字节先传，高字节后传
自动跳 App 的唯一条件仍为 confirmed_bootable
RUN_RAM / RAM_RUN 源码和测试保留，Flash build 默认裁剪
```

### 1.3 文档优先级

发生冲突时采用以下优先级：

```text
1. 用户对当前工作的明确决定
2. Runtime Architecture Contract V2
3. 稳定 DSP / protocol / Flash layout 技术合同
4. Phase 10.8A operation library 合同
5. repository AGENTS 与 GUI AGENTS 的贡献边界
6. Phase 11 GUI Layout V1 合同
7. 当前指南与 README 摘要
```

本合同明确取代旧 GUI Runtime 文档中以下已经过时的假设：

```text
Advanced 只支持 CPU1
Advanced 自己拥有独立 Flash Image
Backend 长期缓存 Prepared Image
所有 Controller 任务都是用户可见 TaskDialog 任务
BOOT_ATTEMPT 只能写一次
显式 RUN 必须要求 BOOT_ATTEMPT
GUI 暴露 autobaud 业务步骤
```

---

## 2. 核心架构原则

### 2.1 唯一状态所有者

`RuntimeBackend` 是所有活动业务状态和运行期资源状态的唯一所有者。

禁止 View、Binding、Controller、Store、Provider 或 Policy 各自保存第二份可独立变化的业务状态。

允许存在：

```text
不可变请求
不可变快照
不可变操作计划
只读 View Model
持久化 DTO
```

不允许存在：

```text
Binding 内部的 CPU1/CPU2 独立 revision 真值
View 控件值作为业务真值
Controller 中重复的 Image / Metadata / Verify 状态
Store 对象作为 Runtime 当前状态所有者
```

### 2.2 面向能力和资源，不面向 CPU 名称编码

CPU 资源统一存放：

```python
target_resources: dict[CpuId, TargetResourceState]
```

禁止新增：

```python
cpu1_xxx
cpu2_xxx
if target == "cpu1": ...
elif target == "cpu2": ...
```

仅允许在以下边界出现 CPU 标识：

```text
TargetProfile 注册
Session 中的 CPU key
导航页实例化
用户可见标题
DSP discovery 结果
CPU-specific capability / FlashLayout 数据
```

### 2.2.1 延期能力不是架构特化许可

CPU1/SCI 已验证而 CPU2/TCP 延期，描述的是当前 capability 状态，不改变共享架构：

```text
允许：CPU2 控件显示 unavailable/disabled
允许：缺少 CPU2 TargetProfile、bootloader、resource 或 capability 时拒绝操作
允许：在 TargetProfile、FlashLayout、resource construction 中提供 target-specific 数据

禁止：在共享 Backend、Binding、Widget 或 operation flow 中复制 CPU1/CPU2 分支
禁止：用 CPU1 默认值填充尚未实现的 CPU2 行为
禁止：因为 CPU2 延期而把共享状态、资源或命令选择改成 CPU1-only
禁止：伪造 CPU2 支持或绕过 capability gate
```

延期能力只能保持未提供、不可用或被 capability gate 拒绝；已存在的共享抽象仍必须保持 target/profile driven。

### 2.3 监听式派生处理

Target、Image、Connection、Evidence、Metadata 等源状态改变时：

```text
源状态修改
→ 发布类型化 Domain Event
→ 各 Policy 监听自己关心的事件
→ Backend 原子提交新状态
→ 发布不可变 RuntimeSnapshot
→ View Adapter 更新界面
```

禁止在 `set_target()`、`set_image_path()` 等函数中堆叠大量无关逻辑。

### 2.4 开闭原则

新增已知后续功能时，优先采用：

```text
Provider
Policy
Strategy
Adapter
Registry
Profile
Workflow composition
Operation implementation
```

避免修改：

```text
通用 Advanced Flash/Metadata/RAM 逻辑
TaskDialog 状态机
Program Image 生命周期规则
Session 基础 schema
Transport 上层 workflow
已验证 operation 原子语义
```

### 2.5 保留已验证实现，不无目的重写

现有已验证行为应通过适配和迁移保留：

```text
Program Image 路径提交后自动解析
现有 TaskDialog 展示与取消状态机
Phase 10.8A operations/* 原子操作边界
BootProtocolClient / FrameReader / ByteTransport 分层
Phase 11.1 页面布局、主题和导航
```

重构应针对状态所有权和错误架构，不应重写已稳定算法。

---

## 3. 总体分层与依赖方向

```text
PySide6 View
  - 只显示状态和发送用户 intent
  - 不访问 session / transport / protocol / operations / images

View Binding / Presenter
  - 将 View intent 转换为应用命令
  - 将 RuntimeSnapshot 映射为界面状态
  - 不拥有业务资源

Application Services
  - Session lifecycle
  - Settings lifecycle
  - Flash write confirmation orchestration
  - foreground task orchestration
  - navigation intent

GuiController
  - 单个用户前台任务状态机
  - Worker / QThread 生命周期
  - TaskDialog 状态
  - 不拥有 Image / Metadata / Target resource 真值

RuntimeBackend
  - 活动连接和 UpgradeSession
  - Target resource state
  - Image Summary / Evidence / Snapshot
  - Operation request preparation
  - Domain Event / Policy 执行
  - 唯一业务状态所有者

ConnectionCommandExecutor
  - UpgradeSession.client 的唯一协议访问入口
  - 前台协议操作与维护操作串行化
  - 前台优先

operations/*
  - 原子业务操作
  - Flash / metadata 最终 PC 侧业务检查
  - SERVICE_ATTACH 内部处理

UpgradeSession
  - ByteTransport + BootProtocolClient 生命周期

BootProtocolClient / FrameReader
  - 协议命令、sequence、frame、timeout

ByteTransport Provider
  - SCI/RS232
  - 后续 W5300 TCP
```

依赖只能向下，不允许反向导入 View 或 GUI 控件。

---

## 4. 标识类型与通用模型

### 4.1 强类型标识

建议至少定义：

```python
CpuId
TransportId
ConnectionId
ConnectionGeneration
SessionRevision
ImageRevision
OperationId
TaskId
```

实现可以使用 Enum、NewType 或冻结 dataclass，但不应在业务代码中散布裸字符串。

### 4.2 ImageIdentity

Flash Image 使用现有完整身份：

```python
@dataclass(frozen=True, slots=True)
class ImageIdentity:
    entry_point: int
    image_size_words: int
    image_crc32: int
    app_end: int
```

路径不是 `ImageIdentity` 的组成部分。

RAM Image 应使用与 RAM operation 需要一致的完整身份，至少包含：

```python
@dataclass(frozen=True, slots=True)
class RamImageIdentity:
    entry_point: int
    total_words: int
    image_crc32: int
```

后续如 RAM operation library 增加必要字段，应扩展统一类型，不得另建 GUI 专用 identity。

---

## 5. RuntimeBackend 状态模型

建议的概念模型：

```python
class RuntimeBackend:
    global_settings: GlobalSettings
    session_state: SessionState
    runtime_cache: RuntimeCacheState

    app_resource_provider: AppResourceProvider
    target_resources: dict[CpuId, TargetResourceState]

    connection_state: ConnectionRuntimeState | None
    metadata_state: MetadataRuntimeState
    diagnostics_state: DiagnosticsRuntimeState
    memory_states: dict[CpuId, MemoryRuntimeState]

    active_foreground_operation: ForegroundOperationState | None
    event_dispatcher: DomainEventDispatcher
    policies: tuple[DomainPolicy, ...]
```

### 5.1 TargetResourceState

```python
@dataclass
class TargetResourceState:
    cpu_id: CpuId

    program_image_path: str
    program_image_summary: FlashImageSummary | None
    program_image_parse_status: ParseStatus
    program_image_parse_error: str | None

    ram_image_path: str
    ram_image_summary: RamImageSummary | None
    ram_image_parse_status: ParseStatus
    ram_image_parse_error: str | None

    erase_scope: EraseScope
    custom_sector_mask: int

    verify_evidence: VerifyEvidence | None
    ram_crc_evidence: RamCrcEvidence | None
```

`TargetResourceState` 不保存完整 `FirmwareImage` 或 `Prepared*Image`。

### 5.2 ConnectionRuntimeState

```python
@dataclass
class ConnectionRuntimeState:
    connection_id: ConnectionId
    generation: ConnectionGeneration
    session: UpgradeSession
    target_id: CpuId
    transport_id: TransportId
    endpoint_label: str
    health_state: ConnectionHealthState
```

连接代次必须用于 Evidence 和异步回调校验。

---

## 6. 持久化分类合同

### 6.1 Session Settings

Session 路径由用户决定；Session 文件可以不存在。未保存状态称为 Untitled Session。

Session 保存：

```text
每个 CPU 的 Program Image 路径
每个 CPU 的 RAM Image 路径
每个 CPU 的 Erase Scope
每个 CPU 的 Custom Sector Mask
每个 CPU 的 Sector 配置
当前选择的 transport 类型
所有 transport 的连接配置
后续明确加入的 Session 配置
schema_version
```

Session 不保存：

```text
Verify Evidence
RAM CRC Evidence
Metadata Snapshot
Diagnostics Snapshot
Memory Snapshot
活动连接
完整 Image
Prepared Image
SCI8 临时文件
Flash Service 路径
hex2000 路径
日志输出路径
```

### 6.2 Global Settings

Global Settings 存储到用户 App Data 目录，不随 Session 切换。

保存：

```text
hex2000 可执行文件路径
通用命令 timeout
通用 retry policy
日志输出路径
未来 connection maintenance 的通用时间参数
schema_version
```

不保存：

```text
Flash Service 路径
SCI8 Temp Directory
Program/RAM Image 路径
transport endpoint
Sector Mask
Evidence 或 Snapshot
```

### 6.3 Runtime Cache

Runtime Cache 当前只保存最近 Session 记录：

```python
@dataclass(frozen=True, slots=True)
class RecentSessionEntry:
    path: str
    last_saved_at_utc: datetime
```

规则：

```text
最多 10 条
按最近保存时间倒序
规范化绝对路径去重
同一路径更新后移动到首位
文件不存在时不静默删除
用户可以手动移除不可用条目
```

### 6.4 Store 与 Backend 的边界

```text
GlobalSettingsStore
SessionStore
RuntimeCacheStore
```

只负责序列化、反序列化、版本迁移和原子写入，不拥有当前运行状态。

---

## 7. AppResourceProvider 合同

所有 CPU 共享一个 Flash Service 资源。

```python
class AppResourceProvider(Protocol):
    def flash_service_image_path(self) -> Path: ...
    def flash_service_map_path(self) -> Path: ...
```

### 7.1 DevelopmentResourceProvider

```text
使用开发者本机固定绝对路径
文件由用户创建
包含用户目录信息
不得被 Git 跟踪
Git 只跟踪 DevelopmentResourceProvider.example
缺失时明确报错，不静默回退
```

### 7.2 InstalledResourceProvider

当前只冻结职责，实际安装目录和 manifest 在打包阶段确认并形成文档。

### 7.3 禁止事项

```text
Flash Service 路径不可进入 Global Settings
不可进入 Session
不可由最终用户编辑
业务代码不可根据目录猜测开发版或发布版
```

---

## 8. Image 生命周期合同

### 8.1 路径提交后的自动解析

保留当前已经实现的行为：

```text
用户选择或编辑 Image 路径
→ 路径提交
→ 自动解析
→ 更新轻量 Summary 和 Parse Status
```

本次重构不得重写已经验证的解析算法，只迁移状态所有权和资源生命周期。

### 8.2 Backend 不缓存完整 Image

Backend 不得长期保存：

```text
FirmwareImage
PreparedFlashImage
PreparedRamImage
PreparedServiceImage
完整 blocks / words
可直接用于 Program / Verify / RAM Load 的对象
生成的 SCI8 路径
```

Backend 可以保存：

```text
路径
ImageIdentity / RamImageIdentity
轻量 Summary
Parse Status
Parse Error
Evidence
```

### 8.3 操作前必须重新解析

任何需要 Image 数据的操作，必须在该次操作中重新读取源文件并重新生成完整 Image：

```text
基于 Image 的 Erase
Program
Verify
Write IMAGE_VALID
RAM Load
RAM CRC
```

禁止从旧完整 Image cache 执行操作。

自动解析得到的 Summary 只用于显示、导航、门禁和 Evidence 比较，不是实际操作输入。

### 8.4 RAM Run 例外

RAM Run：

```text
不重新解析 Image
不运行 hex2000
不创建 PreparedRamImage
只使用有效 RamCrcEvidence 中的 entry point / identity 信息
```

RAM Run 是调试功能，只提供尽可能安全的程序门禁，最终有效性由使用者保障。

### 8.5 不变任务输入与一次性 Materialization

任务执行使用不可变输入。路径控件在活动 TaskDialog 期间不可操作。

需要确认的 Flash 写操作采用一次性准备对象：

```python
@dataclass(frozen=True, slots=True)
class PreparedFlashWriteRequest:
    public_plan: FlashWritePlan
    private_materialization: OperationImageMaterialization | None
```

规则：

```text
重新解析源 Image / Flash Service
→ 创建本次操作专用 materialization
→ 从同一 materialization 构造公开 FlashWritePlan
→ 显示确认对话框
→ Confirm 后把同一一次性请求交给 Worker
→ 操作完成、失败、取消或拒绝后立即销毁 materialization
```

`private_materialization` 不进入 Backend 资源状态，不进入 Session，不可被其他操作查询或复用，因此不属于 Image cache。

用户取消确认时必须立即销毁该对象。确认后执行内容必须与确认框显示的 Identity、Sector Mask 和 metadata 参数一致，不得再次从控件读取替换参数。

无需确认的 Image 操作可以在 Worker 内创建同样的一次性 materialization，并在任务结束时销毁。

---

## 9. SCI8 临时文件合同

### 9.1 `.txt` 输入

```text
直接只读解析用户提供的 SCI8 TXT
不复制
不删除
```

### 9.2 `.out` 输入

每次解析或操作创建独立临时 workspace：

```text
<OS temp>/bootloader_upgrade_tool/<process>/<operation-or-random-id>/image.sci8.txt
```

要求：

```text
不写入源 Image 目录
不写入应用安装目录
不写入 Session 目录
不跨操作复用
CPU1/CPU2 不共享固定输出文件名
成功、失败、取消、异常均在 finally 清理
Windows 删除前关闭全部文件句柄
```

### 9.3 配置边界

```text
hex2000 路径：Global Settings，可编辑
SCI8 Temp Directory：不在用户可见设置中
测试可注入临时根目录
CLI/测试可显式要求保留 SCI8
GUI 正常流程不保留
```

---

## 10. Domain Event 与 Policy 合同

### 10.1 类型化事件

至少预留：

```text
SessionChanged
ProgramImagePathChanged
ProgramImageParsed
RamImagePathChanged
RamImageParsed
ConnectionOpened
ConnectionClosed
ConnectionGenerationChanged
ActiveTargetChanged
ForegroundOperationStarted
ForegroundOperationFinished
EraseStarted
ProgramStarted
VerifyStarted
VerifySucceeded
RamLoadStarted
RamCrcStarted
RamCrcSucceeded
MetadataWriteStarted
MetadataRefreshSucceeded
MetadataRefreshFailed
MemoryReadSucceeded
MemoryCleared
```

### 10.2 Policy

建议至少包含：

```text
ImageSummaryPolicy
VerifyEvidencePolicy
RamCrcEvidencePolicy
MetadataFreshnessPolicy
MemoryStalePolicy
SectorSelectionPolicy
ConnectionHealthPolicy
```

### 10.3 执行规则

```text
事件处理顺序固定并可测试
Policy 不保存第二份业务状态
Policy 只修改 Backend 管理的状态
一次源事件处理完成后发布一个一致快照
Domain Event 不依赖 Qt
Qt signal 仅用于应用层和 View 通知
监听器异常不得导致部分状态提交
```

---

## 11. Connection、Transport 与 Ping 扩展合同

### 11.1 Transport 抽象

GUI 上层不出现 autobaud、SCI、TCP、W5300 业务步骤。

```text
Session：transport 类型和所有 transport-specific 配置
Global：通用 timeout / retry
Transport Provider：open / close / byte read-write 和内部握手
```

autobaud 属于 SCI transport 内部行为。

### 11.2 协议访问唯一入口

所有 `UpgradeSession.client` 协议访问必须经过统一连接执行器。执行器提供的是**操作级 lease**，不是只锁住单个 frame：

```python
class ConnectionCommandExecutor(Protocol):
    def execute_foreground(self, generation, action): ...
    def try_execute_maintenance(self, generation, action): ...
```

其中 `action` 在持有 lease 时接收当前 `UpgradeSession`，可以执行一个完整的多命令原子操作。

规则：

```text
同一连接不允许协议事务并发
一个 Flash/RAM/Metadata operation 的多条协议命令之间不得插入 Ping
Foreground 优先于 Maintenance
待执行 Ping 不得阻塞用户操作
Maintenance 获取不到 lease 时直接延期，不排在前台请求之前
已经开始的短 Ping 完成后才能开始前台协议阶段
Timer / View / Scheduler 不得直接访问 transport 或 client
本地 Image 解析必须尽量在获取 foreground lease 前完成
```

`BootProtocolClient` 自身的 transaction lock 继续保留，作为底层防御；它不能替代操作级 lease。

### 11.3 Ping 的定位

未来 Ping 属于内部连接维护，不属于用户任务。

Ping 不得：

```text
打开 TaskDialog
进入 Shared Result
修改 Session dirty
显示普通操作进度
进入 Flash 写确认
改变当前页面
```

### 11.4 Maintenance Scheduler 扩展点

当前阶段不实现 Ping，但必须预留：

```python
class ConnectionMaintenanceScheduler(Protocol):
    def connection_opened(self, generation): ...
    def foreground_command_started(self, generation): ...
    def foreground_command_finished(self, generation): ...
    def protocol_activity(self, generation): ...
    def connection_closed(self, generation): ...
```

当前注入：

```text
NoOpConnectionMaintenanceScheduler
```

未来替换：

```text
PingConnectionMaintenanceScheduler
```

### 11.5 Ping 调度边界

未来行为：

```text
仅在连接有效时
且没有前台协议命令占用连接通道
且不在断开、shutdown、结果处置流程中
且达到空闲阈值
才允许发送 Ping
```

本地 Image 解析和 Flash 写确认对话框本身不应永久阻止维护 Ping；只有实际占用 `UpgradeSession` 协议通道的阶段才暂停维护命令。

连接关闭、Run 释放连接、Session 切换和 GUI 关闭时，旧 generation 的维护回调必须丢弃。

具体 Ping timeout、retry、DSP idle timeout 和失败提示在 DSP 协议确定后再冻结，但不得要求修改 Advanced、TaskDialog、Image、Metadata 或 transport 上层架构。

---

## 12. GuiController 与 TaskDialog 合同

### 12.1 前台任务

`GuiController` 只管理用户可见的前台任务：

```text
一次只允许一个前台任务
任务使用现有 QThread / Worker 模式
任务发出 TaskState / Progress / Result
TaskDialog 继续使用现有状态机
```

### 12.2 Maintenance 不进入 GuiController 前台任务槽

Ping 等维护命令使用独立维护调度和连接执行器，不创建 `TaskPlan`，不发出 `taskStarted`。

### 12.3 TaskDialog 保留现有合同

保留：

```text
Window-modal overlay
可取消任务关闭等价于一次 cancel request
不可取消任务不能关闭
clean success 按 CompletionPolicy 自动关闭
warning / failure 等待用户关闭
uncertain outcome 的 Disconnect / Keep Connection 等动作
```

不得为 Ping 或 Flash 确认重写 TaskDialog 状态机。

---

## 13. FlashWriteConfirmationDialog 合同

所有独立 Flash 写操作必须每次确认：

```text
Erase
Program
Write IMAGE_VALID
每一次 Write BOOT_ATTEMPT
Write APP_CONFIRMED
```

流程：

```text
重新解析必要 Image
→ 完成前置检查
→ 构造不可变 FlashWritePlan
→ 打开独立 Window-modal FlashWriteConfirmationDialog
→ 用户 Confirm
→ Controller 接受任务
→ 打开现有 TaskDialog
→ operation library 执行最终检查和写入
```

取消确认不得创建 Task、不得改变 Evidence、不得写入日志为失败操作。

建议模型：

```python
@dataclass(frozen=True, slots=True)
class FlashWritePlan:
    operation_type: FlashWriteOperationType
    cpu_id: CpuId
    connection_id: ConnectionId
    connection_generation: ConnectionGeneration
    image_identity: ImageIdentity | None
    sector_mask: int | None
    metadata_record_type: MetadataRecordType | None
    boot_attempt_count_before: int | None
    boot_attempt_count_after: int | None
```

---

## 14. Program Image 页面合同

### 14.1 CPU Program 页面

CPU Program 页面是对应 CPU 的 Program Image 唯一编辑入口。

```text
路径始终可编辑，但活动 TaskDialog 期间全局模态阻止操作
路径提交后自动解析
保留现有实现，不重写解析 workflow
Program workflow 暂缓
```

### 14.2 Advanced 中的 Program Image 显示

Advanced 同时显示 CPU1 和 CPU2 两套 Program Image 信息，均为只读。

保持当前面板布局，只做以下调整：

```text
Path 单独显示
路径右侧按钮保留
按钮不选择文件
按钮切换到对应 CPU Program 页面并聚焦路径控件
删除 Target 字段
摘要区由两行增加为三行，两列布局不变
```

每个 CPU 的摘要排列：

| 行 | 左列 | 右列 |
|---|---|---|
| 1 | App End | Entry Point |
| 2 | Image Size | CRC32 |
| 3 | Parse Status | Verify |

更新来源：

```text
Path、App End、Entry Point、Image Size、CRC32、Parse Status
  只随对应 CPU Image 更新

Verify
  随连接、当前 Target 和 VerifyEvidence 更新
```

连接或 Target 变化不得重新解析或清空 CPU1/CPU2 Image 信息。

---

## 15. VerifyEvidence 合同

```python
@dataclass(frozen=True, slots=True)
class VerifyEvidence:
    cpu_id: CpuId
    connection_generation: ConnectionGeneration
    image_identity: ImageIdentity
    operation_id: OperationId
```

### 15.1 生成

```text
Verify 新任务成功
→ 生成新 Evidence
```

### 15.2 失效

```text
路径变化且完整 ImageIdentity 不同
Erase 开始
Program 开始
Verify 新任务开始
当前 CPU Target 变化
断开并重新连接
GUI 重启
```

```text
路径变化但完整 ImageIdentity 相同
→ Evidence 保留
```

Session 保存和加载不持久化 Evidence；Session 切换导致运行期 Evidence 失效。

### 15.3 使用

Write IMAGE_VALID 前 Backend 必须确认：

```text
当前连接 Target 与 Evidence CPU 一致
connection generation 一致
本次重新解析得到的完整 ImageIdentity 与 Evidence 相同
```

GUI 只负责该 Evidence 门禁；metadata 最终业务检查由 operation library 完成。

---

## 16. RAM Image 与 RamCrcEvidence 合同

### 16.1 RAM Image 归属

```text
RAM Image 是 Advanced 调试功能
路径在 Advanced RAM 页面编辑
CPU1/CPU2 各自保存路径
路径保存到 Session
不由 CPU Program 页面管理
不需要 Flash 写确认
```

### 16.2 操作

```text
RAM Load：重新解析 Image
RAM CRC：重新解析 Image，并对 DSP RAM 校验
RAM Run：不解析 Image，只使用 RamCrcEvidence
```

### 16.3 RamCrcEvidence

```python
@dataclass(frozen=True, slots=True)
class RamCrcEvidence:
    cpu_id: CpuId
    connection_generation: ConnectionGeneration
    image_identity: RamImageIdentity
    entry_point: int
    image_crc32: int
    operation_id: OperationId
```

### 16.4 RAM Run 门禁

```text
当前连接有效
AND 当前 Target 与 RAM Image CPU 相同
AND RAM CRC 成功
AND Evidence 对应当前已知完整 RAM Image Identity
```

不额外要求本连接中必须执行过 RAM Load。

### 16.5 Evidence 失效

```text
RAM Image Identity 改变
新的 RAM Load 开始
新的 RAM CRC 开始
当前 Target 改变
断开并重新连接
Session 切换
GUI 重启
```

RAM Run 是高级调试操作，程序只尽可能维护有效性，不承诺检测用户在外部绕过 GUI 后造成的所有 RAM 变化。

---

## 17. Sector 与 Erase Scope 合同

每个 CPU 独立保存：

```text
Erase Scope
Custom Sector Mask
```

### 17.1 三种范围

```text
Required App Sectors
  = 本次重新解析 Image 得到的 sector_mask
    | FlashLayout.metadata_sector_mask

Entire Application Region
  = FlashLayout.allowed_erase_mask

Custom Sector Mask
  = Session 中当前 CPU 保存的 mask
```

### 17.2 UI 行为

```text
未连接：显示无，禁止编辑
连接 CPU1：显示 CPU1 配置
连接 CPU2：显示 CPU2 配置
Target 变化：由监听器切换
Sector 只在 Advanced 编辑
```

### 17.3 合法性

```text
mask != 0
mask 不包含 forbidden_erase_mask
mask 不超出 allowed_erase_mask
```

所有 FlashLayout 数据由 target profile / operations library 提供，GUI 不硬编码 TMS320F28377D sector 表作为业务真值。

---

## 18. Metadata 写入合同

### 18.1 职责

```text
GUI / Backend：Evidence 门禁、确认、展示
operation library：操作前重新读取 metadata 并执行 PC 侧最终业务检查
flash_lib：最终写入和底层校验
bootloader：只读 metadata
```

### 18.2 IMAGE_VALID

允许条件：

```text
当前 Program Image 的 VerifyEvidence 有效
AND 本次重新解析完整 ImageIdentity 与 Evidence 相同
AND operation library 读取到 metadata 当前没有 IMAGE_VALID
```

任一条件不满足则禁止写入。

### 18.3 BOOT_ATTEMPT

operation library 读取 metadata，允许条件：

```text
存在 IMAGE_VALID
AND boot_attempt_count < 3
AND APP_CONFIRMED 不存在
```

不依赖当前 Program Image 或 VerifyEvidence。

每次写入单独确认。

### 18.4 APP_CONFIRMED

operation library 读取 metadata，允许条件：

```text
存在 IMAGE_VALID
AND boot_attempt_count > 0
AND APP_CONFIRMED 不存在
```

不依赖当前 Program Image 或 VerifyEvidence。

### 18.5 operation library 接口方向

BOOT_ATTEMPT 和 APP_CONFIRMED 不应要求 GUI 从当前 Program Image 提供 identity。operation library 应从当前 metadata IMAGE_VALID summary 获取需要写入的绑定信息。

---

## 19. Run 合同

协议和 operation library 只有一种 Flash App `RUN`。

PC 显式 Run 条件：

```text
metadata valid
AND IMAGE_VALID valid
AND entry point valid
```

不要求：

```text
BOOT_ATTEMPT
APP_CONFIRMED
当前 Program Image
VerifyEvidence
```

原因：Advanced 是调试模式；正常升级 workflow 会在 Run 前写入 BOOT_ATTEMPT。

DSP 后续修改显式 RUN 逻辑，删除对 BOOT_ATTEMPT 的依赖。

Bootloader 自动跳 App 仍严格要求：

```text
confirmed_bootable
```

显式 Run 成功后释放连接。

---

## 20. MetadataSnapshot 生命周期

建议模型：

```python
@dataclass(frozen=True, slots=True)
class MetadataRuntimeState:
    snapshot: MetadataSnapshot | None
    freshness: SnapshotFreshness
    stale_reason: str | None
```

### 20.1 生命周期

```text
断开连接
  → 清空 Advanced Metadata Snapshot

Target 变化
  → 清空 Advanced 中 Target 相关信息
  → 不清空 CPU Program Image 数据
  → 不清空 Advanced CPU1/CPU2 Image 信息

Erase / Program / Metadata Write 开始
  → 保留旧值
  → 立即标记 STALE

操作成功
  → 自动 Metadata Refresh

刷新成功
  → 替换 Snapshot
  → FRESH

操作失败
  → 保留旧 Snapshot
  → STALE

写操作成功但自动刷新失败
  → 写任务仍为 SUCCEEDED
  → 附带 METADATA_REFRESH_FAILED warning
  → 旧 Snapshot 保持 STALE
```

不得因为后续只读刷新失败，把已成功完成的不可逆 Flash 写入报告为失败。

---

## 21. Memory 合同

Memory 页面只读取 DSP 数据。

```text
当前 Target 为 CPU1：CPU1 Read 启用，CPU2 Read 禁用
当前 Target 为 CPU2：CPU2 Read 启用，CPU1 Read 禁用
未连接：全部 Read 禁用
```

旧数据：

```text
断开或 Target 不匹配后继续显示
标记 Stale
直到对应 CPU 下一次成功读取、用户清空或关闭 App
不写入 Session
不写入 Global Settings
不写入 Runtime Cache
```

MemorySnapshot 应至少记录：

```text
cpu_id
address
length
data
read_at
connection_generation
freshness
```

---

## 22. Session 生命周期合同

### 22.1 New / Open / Switch

```text
已连接：New/Open 禁用，并提示先断开
活动任务：New/Open/Close 禁用
存在未保存修改：Save / Discard / Cancel
```

### 22.2 Session 切换

切换后所有运行期缓存数据失效：

```text
VerifyEvidence
RamCrcEvidence
MetadataSnapshot
DiagnosticsSnapshot
MemorySnapshot
操作结果临时状态
旧 Image Summary
旧 Parse Error
```

新 Session 的 Program/RAM Image 路径加载后，使用现有自动解析机制重新生成轻量 Summary。

### 22.3 Advanced 无 Session 文件

未保存的 Untitled Session 仍可使用 Advanced。Session 文件是否存在不得成为连接或 Advanced 操作的必要条件。

---

## 23. Advanced 的定位

Advanced 是调试模式，不是“更高权限”的另一套协议实现。

Advanced 直接组合稳定原子 operation：

```text
Diagnostics
Flash Erase / Program / Verify
Metadata write
Flash App Run
RAM Load / CRC / Run
Memory read
```

Advanced 不复制 operation library 的 Flash、metadata 或 service attach 状态机。

CPU Program 页面代表未来正常升级 workflow；其完整 Program workflow 在 CPU2 bootloader 和 CPU2 Advanced 完成后统一设计。

---

## 24. 结果、错误与连接状态合同

### 24.1 OperationResult 不丢失

operation library 的：

```text
stage
summary
progress
warning
error
cancellation info
service info
```

应完整适配为 GUI Task 结果，不得简化成布尔值。

### 24.2 写成功 + 刷新失败

按照第 20 节处理为成功附带 warning。

### 24.3 不确定结果

保持现有 TaskDialog disposition：

```text
ASK_DISCONNECT
FORCE_DISCONNECTED
RUNTIME_FATAL
```

### 24.4 连接代次

所有异步结果、Evidence、维护回调、Snapshot 必须校验 `connection_generation`，旧连接结果不得污染新连接。

---

## 25. 后续功能扩展合同

### 25.1 CPU2

新增：

```text
CPU2 TargetProfile
CPU2 bootloader 能力
CPU2 resource entry
CPU2 capability / FlashLayout
必要 operation adapter
```

不应修改通用 Advanced Flash/Metadata/RAM/Memory 逻辑。

### 25.2 W5300 TCP

新增：

```text
Transport Provider
Session transport schema
配置页面适配
```

不应修改 Image、Flash、Metadata 和 Program workflow 原子操作。

### 25.3 Ping

新增：

```text
PingConnectionMaintenanceScheduler
Maintenance command
ConnectionHealthPolicy
Global ping settings
测试
```

不应修改 TaskDialog、Advanced 页面或 Image 生命周期。

### 25.4 Program workflow

只组合已有原子 operation，不复制：

```text
Erase
Program
Verify
IMAGE_VALID
BOOT_ATTEMPT
Run
APP_CONFIRMED
```

### 25.5 Reset

新增 execution operation 和结果适配，不修改 Flash / Metadata / Image 管理。

### 25.6 File watcher

仅发布文件变化事件并触发轻量重解析；实际操作前重新解析合同不变，File watcher 不能成为正确性的唯一保证。

### 25.7 Packaging

新增 `InstalledResourceProvider` 和打包 manifest，不修改 Flash Service 业务使用方式。

---

## 26. 明确禁止的架构回退

```text
Backend 重新缓存 PreparedFlashImage / PreparedRamImage
Advanced 重新拥有可编辑 Program Image
Binding 持有独立业务真值
GUI 暴露 autobaud 工作流
根据 target 字符串散布 CPU1/CPU2 分支
把 Ping 作为 TaskDialog 用户任务
让 Timer 直接调用 BootProtocolClient
将 Flash 写确认塞入现有 TaskDialog 状态机
GUI 重复 metadata 写入判断而 operation library 不检查
Program workflow 复制 operations/* 实现
将 Flash Service 路径写入 Settings 或 Session
将 SCI8 Temp Directory 暴露给普通用户
```

---

## 27. 架构验收测试

### 27.1 CPU 扩展测试

模拟注册 CPU3 时，不修改：

```text
Advanced Flash binding
Advanced Metadata binding
RAM operation binding
Memory binding
VerifyEvidencePolicy
```

### 27.2 Transport 扩展测试

注入 Fake TCP transport 时，不修改：

```text
operations/*
Image lifecycle
Metadata lifecycle
Advanced workflow
```

### 27.3 Ping 扩展测试

注入 Fake Maintenance Scheduler：

```text
不打开 TaskDialog
前台命令优先
前台协议占用时 Ping 延后
本地 Image 解析阶段可继续维护连接
旧 generation 回调被丢弃
```

### 27.4 Image 生命周期测试

```text
路径提交自动解析仍工作
每次 Program/Verify/RAM Load/RAM CRC 都重新解析
Backend 不持有 Prepared Image
临时 SCI8 在成功/失败/取消后清理
相同完整 Identity 保留 VerifyEvidence
不同 Identity 使 Evidence 失效
```

### 27.5 Metadata 测试

```text
IMAGE_VALID 需要 VerifyEvidence 且 metadata 无 IMAGE_VALID
BOOT_ATTEMPT 最多 3 次
APP_CONFIRMED 后禁止 BOOT_ATTEMPT
APP_CONFIRMED 需要 BOOT_ATTEMPT
写成功刷新失败为 success + warning + stale
```

### 27.6 Session 测试

```text
连接后禁止 New/Open
活动任务禁止 Session 切换
Untitled Session 可使用 Advanced
Evidence/Snapshot 不持久化
最近 Session 最多 10 条且路径去重
```

### 27.7 View 边界测试

View 模块继续禁止导入：

```text
operations
images
session
transport
protocol
targets
subprocess
```

---

## 28. 当前仓库的已知迁移驱动

以下不是新需求，而是当前实现与本合同之间的已知差距，后续仓库审计必须逐项定位：

```text
Backend 当前长期保存 Prepared Flash/RAM/Service Image
Advanced 当前有 CPU1/CPU2 可编辑 Flash Image
部分 Binding 和 Backend 存在 CPU1 硬编码
Verify credential 当前不是统一 per-CpuId 资源
Metadata operation library 当前 BOOT_ATTEMPT 只允许一次
Metadata operation library 当前仍要求当前 Image identity
显式 DSP RUN 当前仍依赖 BOOT_ATTEMPT
Controller 当前只有用户前台任务槽，没有 maintenance lane
Runtime Binding 对 taskStarted 无条件打开 TaskDialog
Settings 仍包含 SCI/autobaud 具体概念和 SCI8 temp directory
Session/Global/Runtime Cache 持久化尚未按 V2 分类实现
```

这些差距应通过分阶段迁移解决，不得一次性重写全部 Runtime。

---

## 29. 分阶段迁移原则

正式实施前必须先形成仓库差距审计和迁移计划。

迁移顺序建议：

```text
1. 建立 V2 类型、资源容器和事件合同
2. 建立 Session / Global / Runtime Cache schema
3. 将 CPU1 现有 Image 自动解析迁移到统一资源状态
4. 删除 Backend 完整 Image cache，改为 operation-scoped materialization
5. 将 Advanced Program Image 改为只读双 CPU 显示
6. 建立 VerifyEvidence / RamCrcEvidence Policy
7. 建立 Metadata / Memory freshness lifecycle
8. 建立 FlashWriteConfirmationDialog
9. 修正 operation library metadata 规则
10. 预留 ConnectionCommandExecutor 和 NoOp Maintenance Scheduler
11. 完成 CPU1 Advanced 回归
12. 用户执行真实硬件验证
13. CPU2 bootloader 与 CPU2 Advanced
14. 双 CPU Program workflow
15. Ping / W5300 / packaging 等后续功能
```

每阶段要求：

```text
保持现有已验证行为
补齐 characterization tests
避免同时修改 View、Backend、operation library 和 DSP 大量文件
软件验证通过后涉及硬件时停止并交还用户
```

---

## 30. 变更控制

本合同已于 2026-07-16 经用户确认，现为 Runtime V2 冻结合同。

后续任何变更必须明确标记为：

```text
Contract clarification
Backward-compatible extension
Contract revision
Deferred detail resolution
```

不得通过实现代码或 Codex 任务隐式改变合同。

明确推迟但不构成未确认需求：

```text
Ping 空闲阈值、timeout、retry 和具体提示
DSP idle timeout 数值
InstalledResourceProvider 最终目录和 manifest
CPU2 bootloader 具体实现
双 CPU Program workflow 细节
W5300 transport 实现
Reset 实现
```

这些内容应沿本合同预留接口实现，不应要求再次重构核心资源架构。

---

## 31. 最终架构判定

满足本合同后，可以合理保证：

```text
当前已知的 CPU2、W5300、Ping、Program workflow、Reset、File watcher 和 Packaging
主要通过新增模块、注册项、Policy、Provider、Adapter 或 Workflow 接入，
不会再次要求大范围修改已验证的通用 Runtime 代码。
```

不能承诺任何未知未来需求完全零修改，但核心修改范围必须被限制在明确扩展点，不得再次恢复 CPU-specific 分支、重复状态所有权或跨层耦合。


---

## 32. 需求闭环追踪表

| 已确认需求 | 合同章节 | 状态 |
|---|---:|---|
| Backend 唯一状态所有者 | 2、5 | 已纳入 |
| CPU 统一资源类和 `dict[CpuId, ...]` | 2、5 | 已纳入 |
| Session / Global / Runtime Cache 分离 | 6 | 已纳入 |
| transport 类型和 endpoint 跟随 Session | 6、11 | 已纳入 |
| timeout / retry / hex2000 / 日志路径属于 Global | 6 | 已纳入 |
| Flash Service 随应用发布、所有 CPU 共享 | 7 | 已纳入 |
| DevelopmentResourceProvider 本地固定路径且不入 Git | 7 | 已纳入 |
| Program Image 路径提交后自动解析且不重写现有实现 | 8、14 | 已纳入 |
| Backend 不缓存完整 Image | 5、8 | 已纳入 |
| 每个需要 Image 的操作重新解析 | 8 | 已纳入 |
| SCI8 临时文件为 operation-scoped | 9 | 已纳入 |
| Advanced 双 CPU Image 只读、保持布局、删除 Target、增加一行 | 14 | 已纳入 |
| Path 独立显示，按钮跳转对应 CPU 页面 | 14 | 已纳入 |
| Image 信息只随 Image 更新，Verify 随 Target/Evidence 更新 | 10、14、15 | 已纳入 |
| Verify 使用完整 ImageIdentity 及全部失效规则 | 15 | 已纳入 |
| RAM Image 在 Advanced 编辑并保存 Session | 16 | 已纳入 |
| RAM Run 不重新解析，只依赖 RAM CRC Evidence | 16 | 已纳入 |
| Sector 三种范围和未连接禁用规则 | 17 | 已纳入 |
| IMAGE_VALID / BOOT_ATTEMPT / APP_CONFIRMED 门禁 | 18 | 已纳入 |
| BOOT_ATTEMPT 最多三次，APP_CONFIRMED 后禁止继续写 | 18 | 已纳入 |
| Run 只有一种，显式 Run 不要求 BOOT_ATTEMPT | 19 | 已纳入 |
| 自动启动仍只允许 confirmed_bootable | 1、19 | 已纳入 |
| Flash 写每次独立确认，使用独立对话框 | 13 | 已纳入 |
| Metadata Snapshot 清空、Stale、自动刷新及 warning 规则 | 20 | 已纳入 |
| Memory 旧数据保留并标记 Stale | 21 | 已纳入 |
| 连接后禁止 Session 切换，切换后所有运行缓存失效 | 22 | 已纳入 |
| Advanced 可在无 Session 文件时使用 | 22 | 已纳入 |
| TaskDialog 沿用当前设计 | 12 | 已纳入 |
| Ping 不作为用户任务并预留 maintenance lane | 11、12 | 已纳入 |
| CPU2 / W5300 / Program / Reset / Packaging 扩展边界 | 25 | 已纳入 |
| Codex 不执行真实硬件操作 | 29 | 已纳入 |

本表所列需求均已进入规范性章节；当前未给定的 Ping 数值参数、CPU2 实现细节和打包目录属于明确延期项，不是架构缺口。
