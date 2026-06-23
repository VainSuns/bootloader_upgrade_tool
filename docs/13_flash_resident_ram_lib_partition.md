# 13 Flash-resident Kernel Core and RAM-resident Service Lib Partition

## 1. 背景

出于安全和尺寸考虑，Flash API 通常不应长期随 bootloader 常驻 Flash，以降低误调用和攻击面。同时 bootloader 常驻空间应尽可能小。

未来方案是：常驻 Flash 的 bootloader core 只负责连接、协议、RAM 写入 primitive；Flash 操作等复杂逻辑由 PC 在连接后发送 RAM-resident service lib 到 RAM 中运行或提供服务。

## 2. MVP 状态

MVP 不实现 RAM service lib 加载。MVP 可以单体编译 Erase / Program / Verify 逻辑，但源码必须按照未来可拆分的方式组织。

## 3. Flash-resident core 建议包含

```text
ConnectMaster
word-based IO
frame encode/decode
Ping
GetDeviceInfo
GetProtocolInfo
GetLastError
RamLoadBegin/Data/End primitive
Run action
Reset action
minimal state machine
```

## 4. RAM-resident service lib 建议包含

```text
Erase
Program
Verify
Flash API wrapper calls
Flash buffering
Flash diagnostics
Future metadata
Future upload
```

## 5. 协议影响

协议预留：

```text
RamLoadBegin
RamLoadData
RamLoadEnd
```

无 `RamServiceActivate`。RAM 写入后功能是否生效由用户设计的 RAM 区域、入口和函数表决定。

## 6. 文件组织建议

```text
dsp/
  bootloader_algorithm/
    core/
      boot_protocol.c
      boot_device_info.c
      boot_ram_load.c
      boot_action.c
    service_flash/
      boot_erase.c
      boot_program.c
      boot_verify.c
      boot_flash_buffer.c
    include/
```

MVP 可一起编译，但 Future 可拆成不同输出。
