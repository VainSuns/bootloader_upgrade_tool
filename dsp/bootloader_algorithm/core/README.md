# Flash-resident core

The hardware-independent core implements byte-level wire resynchronization,
response framing, core queries, and Phase 5 Erase/Program/Verify/Run/Reset
state handling. Flash operations only call the user-owned `BootFlash_*` port.
RAM-load and other Future commands remain unsupported.
