# 06 device_info Tool Requirements

## 1. 目标

实现 `.cmd` linker command file 的 MEMORY 段解析，生成 `device_info.json`。

第一版只解析 MEMORY，不解析 SECTIONS。

## 2. 输出字段

```json
{
  "device": "F28377D",
  "cpu": "CPU1",
  "memory_regions": [],
  "flash_sectors": [],
  "allowed_address_ranges": [],
  "default_erase_region": [],
  "entry_point_range": []
}
```

## 3. Flash sectors

`flash_sectors` 顺序非常重要。协议中的 `sector_mask` bit 顺序必须与 `device_info.json.flash_sectors` 顺序一致。

例如：

```text
bit0 -> flash_sectors[0]
bit1 -> flash_sectors[1]
...
```

## 4. CPU1/CPU2

CPU1 和 CPU2 使用各自生成的 device_info/TargetProfile 数据。当前硬件验证
覆盖 CPU1；共享 Runtime、GUI binding 和 operation dispatch 仍按活动
TargetProfile/CommandSet 驱动，不能把 CPU1 验证状态固化为共享架构分支。
