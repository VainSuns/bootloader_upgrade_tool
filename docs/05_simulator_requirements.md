# 05 Simulator Requirements

## 1. 定位

Simulator 是 GUI 内置 IO Device，同时提供可测试的 simulator core。

## 2. 必须实现

- WaitSlave；
- Protocol frame encode/decode；
- Ping；
- GetDeviceInfo；
- GetProtocolInfo；
- GetLastError；
- Erase；
- ProgramBegin/Data/End；
- VerifyBegin/Data/End；
- Run；
- Reset。

## 3. Flash 模拟

Simulator 应使用内存模拟 Flash region，并按 device_info.json 的 sector 顺序解释 sector_mask。

## 4. Flash 数据对齐

Simulator 对 ProgramData / VerifyData 必须检查：

```text
data_words > 0
data_words % 8 == 0
data_words <= max_data_words
payload_words == 5 + data_words
```

不满足时返回 `BOOT_STATUS_BAD_WORD_COUNT` 或 `BOOT_STATUS_BAD_PAYLOAD_LENGTH`。

RamLoadData 写 RAM，不使用 Flash 8-word 对齐规则。

## 5. 错误注入

支持：

- erase_fail；
- program_fail_at_address；
- verify_fail_at_address；
- bad_payload_crc；
- no_response；
- illegal_address；
- sequence_mismatch；
- bad_block_index。

## 6. Future RAM

Simulator 可先预留 RamLoadBegin/Data/End，不要求 MVP 完整实现真实 RAM service lib。
