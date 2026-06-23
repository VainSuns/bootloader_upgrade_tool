# Flash-resident core

Phase 4 implements hardware-independent BootIoOps delegation, word-stream CRC
and resynchronization, response framing, and Ping/DeviceInfo/ProtocolInfo/
LastError dispatch. Flash/RAM business commands remain outside this core and
return `BOOT_STATUS_UNSUPPORTED_COMMAND` until their later phases.
