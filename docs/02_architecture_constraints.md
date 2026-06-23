# 02 Architecture Constraints

## 1. 不模仿 TI 示例工程

TI 官方 flash kernel 示例只是简单案例，不是通用工程方案。Codex 可以借鉴其流程和概念，但不得完整模仿其工程结构、全局状态、模块边界和 ACK/NAK 流式协议。

本项目自研 bootloader upper-layer algorithm。

## 2. PC/DSP 主从关系

DSP 永远作为 slave，PC GUI 永远作为 master。

## 3. Word-based 协议

正式协议以 16-bit word stream 为基本单位。线上发送采用 little-endian：low byte first。

## 4. IO Device 抽象

### DSP 侧

DSP bootloader algorithm 只依赖：

```c
BootIo_ConnectMaster(ctx, timeout_ms)
BootIo_GetWord(ctx)
BootIo_SendWord(ctx, word)
```

SCI、W5300、Simulator 均应适配为该接口。

### PC 侧

PC GUI 不直接依赖 pySerial、socket 或 Simulator，必须通过统一 IO Device：

```python
open()
wait_slave(timeout_ms)
read_word(timeout_ms)
write_word(word)
close()
```

第一版实现 SerialIoDevice 和 SimulatorIoDevice，后续实现 TcpIoDevice / W5300IoDevice。

## 5. SCI autobaud 连接层

SCI `'A'` 握手属于连接层，不属于正式协议帧。正式协议从 `magic0/magic1` 开始。

## 6. Flash API 边界

Codex 不直接实现 raw F021 API。Codex 只声明并调用 `BootFlash_*`，用户实现。

Codex 必须理解 Flash API 的基本约束：RAM execution、Flash wait-state、pump semaphore、DCSM、AutoECC、64-bit/128-bit alignment、FMSTAT、BlankCheck、Verify。

## 7. Flash-resident core / RAM-resident service lib

MVP 可以先单体编译，但源码结构必须预留：

```text
flash_resident_core:
  ConnectMaster
  Ping
  GetDeviceInfo
  GetProtocolInfo
  protocol encode/decode
  RamLoad primitive
  Run/Reset action

ram_resident_service_lib:
  Erase
  Program
  Verify
  Flash API wrapper calls
  detailed Flash diagnostics
  future metadata/upload
```

## 8. 超时不是协议状态码

超时由 GUI / IO Device 本地检测。DSP 协议状态码中不定义 timeout status。GUI timeout 后可发送 Ping 探测，若仍无响应，提示用户复位 bootloader 并重启 GUI 或重新连接。
