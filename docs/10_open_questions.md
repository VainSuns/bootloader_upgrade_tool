# 10 Open Questions

以下问题分为 **MVP 实现前需要确认** 和 **后续扩展阶段再确认** 两类。Codex 在执行 MVP 任务时，应优先处理第一类问题；第二类问题只需要在架构和协议中保留扩展点，不应阻塞 MVP 开发。

## 1. 第一版 MVP 需要确认的内容

1. `BootFlash_*` 最终函数签名；
2. `BootFlashResult` / `BootFlashErrorInfo` 的最终类型和字段；
3. Flash sector mask 与具体产品 sector 权限映射；
4. `max_payload_words` / `max_data_words` 最终值；
5. `device_info.json.flash_sectors` 与协议 `sector_mask` bit 的最终对应关系；
6. GUI 如何从 `C200_CG_ROOT` 定位 `hex2000`，以及手动配置路径的保存方式；
7. SCI `WaitSlave` / DSP `ConnectMaster` 的默认超时时间；
8. MVP 中 `BootFlash_EraseBySectorMask()` 是否允许用户忽略部分 GUI 传入 sector，或者必须严格返回错误；
9. MVP 中 Program / Verify session 失败后的 GUI 提示文本和恢复流程。

## 2. 后续扩展需要确认的内容

1. `BootRam_*` 最终函数签名；
2. `BootRamResult` / `BootRamErrorInfo` 的最终类型和字段；
3. App MetaData 格式；
4. App Upload / Readback 文件格式；
5. RAM service lib 编译、定位、入口、校验方式；
6. RAM service lib 写入完成后的函数表、入口或自动生效机制；
7. W5300 / TCP 连接层实现；
8. CPU2 升级流程；
9. 安全机制与签名方案；
10. DCSM Unlock 真实命令和错误码；
11. Bootloader / App 空间重叠检查；
12. 产线批量烧录流程；
13. CLI 模式。
