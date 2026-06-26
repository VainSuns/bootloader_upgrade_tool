# 13 Flash-resident Kernel Core and RAM-resident Service Lib Partition

## 1. 背景

出于安全和尺寸考虑，Flash API 通常不应长期随 bootloader 常驻 Flash，以降低误调用和攻击面。同时 bootloader 常驻空间应尽可能小。

未来方案是：常驻 Flash 的 bootloader core 只负责连接、协议、RAM 写入 primitive；Flash 操作等复杂逻辑由 PC 在连接后发送 RAM-resident service lib 到 RAM 中运行或提供服务。

## 2. MVP 状态

MVP 不实现生产级 RAM service lib 加载、符号库生成或 linker placement。
源码必须保持 Flash-resident core / RAM-resident service lib 拆分：

- core 不包含 Erase / Program / Verify 业务逻辑；
- core 只通过 service ABI 转发 Flash 命令；
- RAM service lib 文件使用 `_lib` 后缀；
- host tests 可把 core 与 service lib 一起编译验证，但产品 bootloader
  Flash 镜像不得包含 RAM service binary code。

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
  bootloader_common/
    include/
      boot_service_abi.h
      boot_protocol.h
      boot_device_info.h
    src/
      boot_protocol.c
      boot_device_info.c
  bootloader_core/
    include/
      boot_algorithm.h
      boot_io.h
      boot_protocol_core.h
    src/
      boot_algorithm.c
      boot_io.c
      boot_protocol_core.c
  bootloader_user/
    cpu01/
    include/
    src/
    templates/
  flash_service_lib/
    include/
      boot_flash_service_lib.h
    src/
      boot_flash_service_lib.c
      boot_flash_session_lib.c
      boot_flash_error_map_lib.c
```

host tests 可一起编译，但产品输出应拆成 Flash-resident core image 和
separately linked RAM service lib image。

## 7. RAM writable limit generation

`bootloader_autogen/boot_user_ram_limit.h` is generated and intentionally not
tracked by git. Generate it before importing/building the CPU1 CCS project.

The generator must parse linker MEMORY plus map allocations, require all
bootloader-owned RAM to be one continuous RAMGS-only interval, and require that
interval to be edge-anchored at either RAMGS0 low address or RAMGS15 high
exclusive address. RAM_LOAD writable regions are not RAMGS-only; they are the
allowed RAM candidates with BOOT_RSVD, RAMM1, RESET, errata tails, and the
bootloader RAMGS interval removed. BEGIN is writable when present in the
generated region table. All generated region end addresses are exclusive C28x
16-bit word addresses.
