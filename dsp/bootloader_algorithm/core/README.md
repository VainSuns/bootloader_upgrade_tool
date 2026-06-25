# Flash-resident core

The hardware-independent core implements byte-level wire resynchronization,
response framing, core queries, RamLoad skeleton handling, service forwarding,
and Run/Reset action reporting.

Erase/Program/Verify state and `BootFlash_*` calls live in the RAM-resident
Flash service lib, not in this Flash-resident core.
