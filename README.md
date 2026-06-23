# DSP28377D Bootloader Upgrade Tool Documentation v1.5

本文件是 Codex 开发入口文档。

## 项目目标

开发一套用于 TI TMS320F28377D / F2837xD 的在线升级系统，包括 DSP 端 bootloader upper-layer algorithm、PC GUI、SCI/RS232 MVP 通信、后续 W5300/TCP 扩展、`.out -> hex2000 -boot -a -sci8` 转换与解析、`.cmd MEMORY -> device_info.json` 工具、GUI 内置 Simulator，以及可扩展的 RAM-resident service lib 架构。

## 最重要的架构约束

1. DSP 永远是 slave，PC GUI 永远是 master。
2. 正式协议基于 16-bit word stream。
3. SCI autobaud `'A'` 握手属于 IO Device 连接层，不属于正式协议帧。
4. GUI 侧和 DSP 侧都必须提供统一 IO Device 抽象。
5. Flash API 不由 Codex 实现，Codex 只调用 `BootFlash_*` 抽象。
6. 第一版 MVP 不实现 RAM service lib 加载，但源码结构必须支持未来拆分。
7. 未来架构应区分 Flash-resident kernel core 与 RAM-resident service lib。
8. Program / Verify / RamLoad 中用于写入 Flash/RAM 的数据必须是 8-word 整数倍，不足由 PC 侧补 `0xFFFF`。
9. DFU 是 GUI 组合流程：Erase + Program + Verify，不是 DSP 单条协议命令。
10. 不使用 TI 风格 ACK/NAK word，所有命令统一返回完整 response frame。

## 文档索引

| 文档 | 说明 |
|---|---|
| `00_project_overview.md` | 项目总体说明 |
| `01_mvp_requirements.md` | MVP 功能范围 |
| `02_architecture_constraints.md` | 架构约束 |
| `03_dsp_bootloader_algorithm.md` | DSP bootloader algorithm 需求 |
| `04_pc_gui_requirements.md` | PC GUI 需求 |
| `05_simulator_requirements.md` | Simulator 需求 |
| `06_device_info_tool.md` | device_info 工具需求 |
| `07_user_porting_guide.md` | 用户移植边界 |
| `08_future_features.md` | Future 功能规划 |
| `09_not_in_mvp.md` | MVP 不做清单 |
| `10_open_questions.md` | 待确认问题 |
| `11_codex_task_list.md` | Codex 任务清单 |
| `12_mvp_acceptance_criteria.md` | MVP 验收标准 |
| `13_flash_resident_ram_lib_partition.md` | Flash core / RAM lib 分层 |
| `14_communication_protocol.md` | 通信协议规范 |
| `15_ti_sci_flash_kernel_reference_guide.md` | TI SCI flash kernel 示例参考指南 |
| `16_f28377d_flash_operation_codex_guide.md` | F28377D Flash 操作指南 |

## 推荐 Codex 开发顺序

1. 阅读 `README.md`、`02_architecture_constraints.md`、`13_flash_resident_ram_lib_partition.md` 和 `14_communication_protocol.md`。
2. 实现 `.cmd MEMORY -> device_info.json` 和 `.out -> hex2000` 调用。
3. 实现 PC core 数据模型和 `FirmwareImage`。
4. 实现 PC IO Device 抽象、Serial、Simulator。
5. 实现协议 encode/decode 与 CRC。
6. 实现 GUI 基础流程。
7. 实现 DSP bootloader algorithm 骨架和 `BootIoOps` / `BootFlash_*` / `BootRam_*` 抽象。
8. 先完成 DeviceInfo 通信联调。
9. 再实现 Erase / Program / Verify / Run。
10. 最后补充测试、日志、记录和验收。
