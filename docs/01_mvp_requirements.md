# 01 MVP Requirements

## 1. MVP 功能

MVP 必须实现：

1. Windows PC GUI，Python + PySide6 源码运行；
2. 选择 `.out` 文件；
3. 默认从环境变量 `C200_CG_ROOT` 获取 `hex2000` 路径；当环境变量不存在，或者无法找到 `hex2000` 时，提示告警信息，并允许用户手动配置路径；
4. 自动调用 `hex2000 -boot -a -sci8`；
5. 解析 hex2000 sci8 输出；
6. 生成 `FirmwareImage`；
7. 加载 `device_info.json`；
8. SCI / RS232 通信；
9. Simulator 通信；
10. PC GUI 侧统一 IO Device 抽象；
11. DSP 侧统一 BootIoOps 抽象；
12. Connect / GetDeviceInfo；
13. Erase；
14. Program；
15. Verify；
16. DFU = Erase + Program + Verify；
17. Run；
18. Reset；
19. 进度条、日志、错误显示；
20. 升级记录保存与导出；
21. `.cmd MEMORY -> device_info.json` 工具；
22. 基于通信协议规范的 encode/decode；
23. Phase 4 先完成 DeviceInfo 通信联调。

## 2. Program 数据对齐强制要求

所有用于写入 Flash/RAM 的数据包均必须满足：

```text
data_words % 8 == 0
```

适用于：

```text
ProgramData.data[]
VerifyData.expected_data[]
RamLoadData.data[]
```

若原始数据不足 8-word 整数倍，由 PC 侧补 `0xFFFF`。DSP 仍必须检查，不满足时返回 `BOOT_STATUS_BAD_WORD_COUNT`。

## 3. DFU 定义

DFU 是 GUI 侧组合流程：

```text
Erase -> Program -> Verify
```

Run 不属于 DFU。协议层不定义 DSP 单条 DFU 命令。

## 4. MVP 不实现但必须预留

1. W5300 / TCP 实际通信；
2. CPU2 升级；
3. App MetaData；
4. RAM App Download；
5. App Upload / Readback；
6. DCSM Unlock；
7. 通信加密；
8. 固件签名；
9. 固件压缩；
10. 双 App / 回滚；
11. CLI；
12. 产线批量烧录；
13. Bootloader / App 空间重叠检查；
14. RAM-resident service lib 实际加载。
