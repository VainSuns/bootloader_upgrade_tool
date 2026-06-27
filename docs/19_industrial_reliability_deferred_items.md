# Industrial Reliability Deferred Items

## Purpose

This document records industrial reliability topics that are intentionally deferred from the current MVP.

The current MVP has validated the main bootloader upgrade chain:

```text
Connect
GetDeviceInfo
Erase
Program
Verify
Run
Jump to Flash App
```

The MVP target is a functional, testable DSP bootloader and PC upgrade tool. Some industrial reliability mechanisms are intentionally deferred to avoid increasing low-level state-machine complexity too early.

## Current MVP Policy

The current MVP does not implement distributed timeout handling inside every low-level path.

The following locations may block by design in the current MVP:

```text
SCI byte receive
SCI TX FIFO wait
protocol magic search
Flash pump ownership wait
Flash FSM busy wait
Run action final jump
```

This is intentional for the MVP.

Do not add independent timeout policies into each low-level function unless the system-level recovery strategy is defined.

## Future Unified Timeout Strategy

Industrial timeout handling will be designed as a unified watchdog-driven recovery mechanism.

The intended future design is:

```text
1. Bootloader records the current critical section.
2. Watchdog timeout or watchdog ISR identifies the fault location.
3. Metadata is used to decide the recovery action.
4. Recovery action chooses one of:
   - remain in bootloader;
   - retry;
   - jump to a confirmed valid app;
   - enter recovery mode.
```

Possible critical section markers:

```text
BOOT_CRITICAL_NONE
BOOT_CRITICAL_COMMUNICATION
BOOT_CRITICAL_FLASH_ERASE
BOOT_CRITICAL_FLASH_PROGRAM
BOOT_CRITICAL_FLASH_VERIFY
BOOT_CRITICAL_RUN_ACTION
```

## Metadata Deferred

The following metadata features are deferred:

```text
image valid flag
pending update flag
confirmed app flag
image CRC
image version
entry point
boot attempt counter
rollback state
device compatibility
hardware compatibility
```

## Reset Deferred

RESET is not advertised in `DeviceInfo.feature_flags`.

The GUI must not expose Reset until deterministic reset behavior is implemented.

The current reset action placeholder is not a production reset implementation.

## RAM_LOAD Deferred

RAM_LOAD is not advertised in `DeviceInfo.feature_flags`.

The GUI must not expose RAM_LOAD until the RAM permission model and dynamic service loading strategy are finalized.

## Permission and Security Deferred

The following features are deferred:

```text
DCSM unlock
firmware signature
host authentication
device authorization
firmware compatibility check
CPU2 upgrade
W5300/TCP transport
```

## Current GUI Exposure Rule

The GUI may expose only capabilities advertised by `DeviceInfo.feature_flags`.

Currently enabled:

```text
ERASE
PROGRAM
VERIFY
RUN
```

Currently disabled:

```text
RESET
RAM_LOAD
APP_UPLOAD
METADATA
UNLOCK_Z1
UNLOCK_Z2
```
