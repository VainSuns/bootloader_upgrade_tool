# RAM-resident Flash service lib

Owns Erase/Program/Verify command validation, Flash transfer session state,
Flash error mapping, and calls to user-provided `BootFlash_*`.

It does not own protocol receive/send, IO state, or the core dispatcher. The
Flash-resident core calls it through `BootServiceApi`.
