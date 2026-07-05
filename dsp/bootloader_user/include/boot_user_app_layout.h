#ifndef BOOT_USER_APP_LAYOUT_H
#define BOOT_USER_APP_LAYOUT_H

/*
 * Flash App execution window used by the user-layer RUN action.
 * This header intentionally contains no erase mask or Flash API details.
 */
#define BOOT_USER_APP_START             0x082400UL
#define BOOT_USER_APP_END_EXCLUSIVE     0x0C0000UL

#endif
