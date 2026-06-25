#ifndef BOOT_PROTOCOL_CORE_H
#define BOOT_PROTOCOL_CORE_H

#include "boot_io.h"
#include "boot_protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

BootProtocolReceiveResult BootProtocol_Receive(const BootIoOps *io,
                                                BootProtocolFrame *frame);
void BootProtocol_SendResponse(const BootIoOps *io,
                               const BootProtocolFrame *request,
                               uint16_t packet_type,
                               uint16_t status,
                               const uint16_t *payload,
                               uint16_t payload_words);

#ifdef __cplusplus
}
#endif

#endif
