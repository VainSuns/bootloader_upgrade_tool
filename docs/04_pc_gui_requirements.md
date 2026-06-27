# 04 PC GUI Requirements

## 1. 技术栈

MVP 使用 Python + PySide6。第一版只要求源码运行，不要求 PyInstaller exe。

## 2. GUI 主流程

```text
选择 .out 文件
-> 自动调用 hex2000 -boot -a -sci8
-> 解析输出
-> 加载 device_info.json
-> 选择 IO Device
-> WaitSlave
-> GetDeviceInfo
-> Erase / Program / Verify / Run / Reset
```

## 2.1 hex2000 路径查找规则

GUI 应优先从环境变量 `C200_CG_ROOT` 定位 `hex2000`。

如果 `C200_CG_ROOT` 不存在，或者在该路径下无法找到 `hex2000`，GUI 必须：

1. 显示告警信息；
2. 允许用户手动配置 `hex2000` 路径；
3. 保存用户配置的路径，供后续会话复用。

## 3. IO Device 抽象

GUI 侧必须通过统一 IO Device 工作：

```python
class PcIoDevice:
    def open(self): ...
    def wait_slave(self, timeout_ms): ...
    def read_available(self): ...
    def read_word(self, timeout_ms): ...
    def write_word(self, word): ...
    def close(self): ...
```

实现：

- `SerialIoDevice`
- `SimulatorIoDevice`
- Future: `TcpIoDevice` / `W5300IoDevice`

GUI 上层流程不得直接调用 pySerial 或 socket。

## 4. SCI WaitSlave

SCI 模式：

```text
GUI 周期性发送 ASCII 'A'
DSP autobaud 成功后回发 ASCII 'A'
GUI 收到 'A' 后连接层完成
随后进入正式协议
```

## 5. FirmwareImage

GUI 解析生成：

```text
source_out_file
generated_hex_file
entry_point
blocks[]
total_words
address_ranges
file_checksum
format_info
```

## 6. Program 数据预处理

PC 必须将写入 Flash 的数据整理为 8-word 整数倍。尾部不足部分补 `0xFFFF`。

适用于：

- ProgramData；
- VerifyData。

RamLoadData 写入 RAM，不使用 Flash 对齐规则。

## 7. Run 检查

FLASH_APP：

- entry point 在 allowed flash range；
- entry point 必须 8-word 对齐；
- 如果当前会话发生过 Erase/Program/DFU，必须 Verify 成功。

RAM_APP：

- entry point 在 allowed RAM range；
- 不要求 8-word 对齐。

## 8. Timeout 处理

Timeout 是 GUI 本地错误，不是 DSP status。

业务命令 timeout 后：

1. 停止当前流程；
2. 标记 `device_state_unknown`；
3. 发送 Ping 探测；
4. 如果 Ping 失败，提示用户复位 bootloader；
5. ProgramData timeout 禁止自动重试，必须重新 Erase/DFU。

## 9. 日志

GUI 显示 INFO/WARN/ERROR。文件保存 `.log` 和 `.jsonl`。RAW 通信默认关闭，可通过调试开关开启。
