# DSP Source

The DSP tree preserves the Flash-resident kernel core / RAM-resident service
library boundary. Phase 4 provides the hardware-independent connection,
protocol, and DeviceInfo core plus guarded user-port templates. Low-level
initialization, linker placement, raw F021 API, and Flash operations remain
user-owned and are not implemented here.
