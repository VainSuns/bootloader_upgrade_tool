# 07 User Porting Guide

## 1. 用户负责内容

用户负责：

- DSP system init；
- clock / PLL；
- Flash wait-state；
- SCI/W5300 初始化；
- SCI autobaud；
- CPU Timer / tick；
- Flash pump semaphore；
- DCSM / FLSEM；
- F021 Flash API；
- App jump；
- reset；
- linker placement；
- RAM execution 配置。

## 2. Codex 生成模板

Codex 可生成模板：

```text
boot_io_sci_port.c
boot_flash_port.c
boot_ram_port.c
boot_delay_port.c
boot_device_info_port.c
boot_action_port.c
```

模板中只放 TODO 和函数框架，不实现硬件细节。

## 3. Flash API 注意事项

用户实现 Flash port 时必须确保：

- Flash API wrapper 和 caller chain 在 RAM；
- erase 后检查 FMSTAT 和 BlankCheck；
- program 后检查 FMSTAT 和 Verify；
- AutoECC 不允许同一 64-bit block 擦除前重复编程；
- address/word_count 对齐检查；
- F2837xD 使用 `Fapi_FlashBank0`；
- CPU1 不直接编程 CPU2 Flash。

详细参考 `16_f28377d_flash_operation_codex_guide.md`。
