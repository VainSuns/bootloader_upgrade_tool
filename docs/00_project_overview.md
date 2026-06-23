# 00 Project Overview

## 1. 项目背景

本项目开发一套用于 TMS320F28377D / F2837xD 的在线升级系统。系统由 PC GUI、DSP bootloader upper-layer algorithm、通信协议、Simulator、device_info 工具组成。

## 2. 第一版 MVP 主流程

```text
PC GUI 选择 .out 文件
-> 自动调用 hex2000 转换为 -boot -a -sci8 格式
-> 解析 hex2000 sci8 输出
-> 加载 device_info.json
-> 连接已运行的 DSP kernel
-> 获取 Device Info
-> Erase
-> Program
-> Verify
-> Run App
```

注意：原先使用的 Download 命名已正式更改为 Program。

## 3. Future 目标流程

未来为了安全和减小常驻 bootloader 尺寸，Flash API 相关复杂功能可能放入 RAM-resident service lib：

```text
PC GUI 选择 App .out
-> hex2000 转换 App
-> 解析 App boot stream
-> 加载 device_info.json
-> 连接 DSP Flash-resident kernel core
-> 获取 Device Info
-> PC 加载 service lib .out
-> hex2000 转换 service lib
-> lib 文件传输
-> bootloader 调用用户 RAM API 写入 RAM
-> RAM service lib 自动生效
-> Erase
-> Program
-> Verify
-> Run App
```

MVP 不实现 RAM service lib 加载，但源码和协议必须预留 `RamLoadBegin / RamLoadData / RamLoadEnd`。

## 4. Codex 工作定位

Codex 负责上层算法、协议、GUI、工具、Simulator、测试骨架。Codex 不负责 DSP 系统初始化、不负责 Flash API 底层实现、不负责 linker 命令文件最终布局。
