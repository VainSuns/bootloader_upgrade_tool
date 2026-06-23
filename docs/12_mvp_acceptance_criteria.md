# 12 MVP Acceptance Criteria

MVP 验收标准：

1. GUI 能选择 `.out` 文件；
2. GUI 能从 `C200_CG_ROOT` 查找 `hex2000`；当查找失败时能告警并允许手动配置；
3. GUI 能调用 hex2000 生成 `-boot -a -sci8`；
4. GUI 能解析 hex2000 输出；
5. GUI 能生成 FirmwareImage；
6. GUI 能加载 device_info.json；
7. GUI 通过统一 IO Device 连接 Simulator；
8. GUI 通过 SerialIoDevice 完成 SCI WaitSlave；
9. DSP 通过 BootIo_ConnectMaster 完成连接；
10. GUI 能获取实机 DeviceInfo；
11. 协议 frame CRC、sequence、resync 能通过测试；
12. ProgramData / VerifyData / RamLoadData 均检查 8-word 整数倍；
13. PC 侧能对 Program/Verify/RamLoad 数据进行 0xFFFF padding；
14. Simulator 能完成 Erase / Program / Verify / Run / Reset；
15. 实机能完成 Erase -> Program -> Verify；
16. 实机能 Run App；
17. ProgramData 超时不会自动重试；
18. GUI timeout 后使用 Ping 探测；
19. 日志、ErrorDetail、GetLastError 可用。
