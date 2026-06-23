# 08 Future Features

以下功能不进入 MVP，但必须影响协议规划和模块边界。

## 1. W5300 / TCP

PC GUI 和 DSP 侧均已通过 IO Device 抽象预留。W5300 的 ALIGN/padding/socket 状态不得污染正式协议层。

## 2. CPU2 Upgrade

CPU1 和 CPU2 使用不同 device_info 文件。CPU2 Flash 操作必须在 CPU2 上执行。

## 3. App MetaData

用于：

- App 有效性；
- App 起始地址；
- App 长度；
- App CRC；
- App version；
- App Upload / Readback。

## 4. RAM App Download

通过 RamLoadBegin/Data/End 实现。RAM 允许重复写，但协议传输数据仍要求 8-word 整数倍。

## 5. App Upload / Readback

依赖 MetaData。不进入 MVP。

## 6. RAM-resident service lib

未来部分 Flash API 相关逻辑迁移到 RAM lib，Flash-resident core 只保留连接、协议 core、RAM 写入 primitive 和 Run/Reset action。

## 7. Security

DCSM Unlock、通信加密、固件签名、压缩、双 App / 回滚均为 Future。
