# 11 Codex Task List

## Phase 0: 文档和骨架

| ID | 任务 | 责任方 |
|---|---|---|
| DOC-001 | 创建文档目录和 README | Codex |
| DOC-002 | 添加架构约束和协议规范 | Codex |
| REPO-001 | 创建 dsp/ pc/ tools/ examples/ 目录 | Codex |

## Phase 1: 文件解析

| ID | 任务 | 责任方 |
|---|---|---|
| PC-001 | 实现 `.cmd MEMORY` parser | Codex |
| PC-002 | 生成 device_info.json | Codex |
| PC-003 | 从 `C200_CG_ROOT` 定位 `hex2000`，失败时告警并支持手动配置，然后调用 hex2000 转换 `.out` | Codex |
| PC-004 | 解析 hex2000 sci8 输出 | Codex |
| PC-005 | 生成 FirmwareImage | Codex |
| TEST-001 | parser 单元测试 | Codex |

## Phase 2: 协议 core

| ID | 任务 | 责任方 |
|---|---|---|
| PROTO-001 | 定义 protocol constants | Codex |
| PROTO-002 | 实现 CRC-16/CCITT-FALSE | Codex |
| PROTO-003 | 实现 frame encode/decode | Codex |
| PROTO-004 | 实现 resync reader | Codex |
| PROTO-005 | 实现 ErrorDetail / DeviceInfo 结构 | Codex |
| PROTO-006 | 实现 8-word data alignment 检查 | Codex |

## Phase 3: PC GUI 与 IO Device

| ID | 任务 | 责任方 |
|---|---|---|
| GUI-001 | PySide6 主窗口 | Codex |
| GUI-002 | PC IO Device 抽象 | Codex |
| GUI-003 | SerialIoDevice | Codex + User Review |
| GUI-004 | SimulatorIoDevice | Codex |
| GUI-005 | WaitSlave SCI `'A'` 握手 | Codex + User Review |
| GUI-006 | Erase/Program/Verify/Run/Reset 操作流 | Codex |
| GUI-007 | Program/Verify 8-word padding; RamLoad range-only validation | Codex |

## Phase 4: DSP bootloader algorithm skeleton

| ID | 任务 | 责任方 |
|---|---|---|
| DSP-001 | BootIoOps 定义 | Codex |
| DSP-002 | Protocol frame parser | Codex |
| DSP-003 | DeviceInfo command | Codex |
| DSP-004 | BootFlash_* header | Codex |
| DSP-005 | BootRam_* header future | Codex |
| DSP-006 | 用户 port 模板 | Codex |
| DSP-007 | 用户集成 SCI / Flash / timer | User |
| TEST-004 | DeviceInfo 实机联调 | Codex + User |

## Phase 5: Erase / Program / Verify

| ID | 任务 | 责任方 |
|---|---|---|
| DSP-101 | Erase command | Codex |
| DSP-102 | Program session | Codex |
| DSP-103 | Verify session | Codex |
| DSP-104 | Run/Reset action | Codex |
| DSP-105 | ErrorDetail 保存与 GetLastError | Codex |
| USER-101 | Flash API port 实现 | User |
| TEST-101 | 实机 Erase -> Program -> Verify | Codex + User |
| TEST-102 | 实机 Run App | Codex + User |

## Future

| ID | 任务 | 责任方 |
|---|---|---|
| FUT-001 | RAM service lib load | Future |
| FUT-002 | W5300/TCP | Future |
| FUT-003 | App Upload | Future |
| FUT-004 | App MetaData | Future |
| FUT-005 | CPU2 Upgrade | Future |
