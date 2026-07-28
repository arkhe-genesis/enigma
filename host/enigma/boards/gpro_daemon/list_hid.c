// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

/*
 * list_hid.c - List all HID interfaces for G Pro keyboard
 */

#include <stdio.h>
#include <hidapi/hidapi.h>

#define GPRO_VID 0x046d
#define GPRO_PID 0xc339

int main() {
    struct hid_device_info *devs, *cur;

    if (hid_init() != 0) {
        fprintf(stderr, "Failed to initialize HIDAPI\n");
        return 1;
    }

    printf("Enumerating all G Pro keyboard interfaces (VID=%04x, PID=%04x):\n\n",
           GPRO_VID, GPRO_PID);

    devs = hid_enumerate(GPRO_VID, GPRO_PID);

    if (!devs) {
        printf("No devices found!\n");
        hid_exit();
        return 1;
    }

    int count = 0;
    for (cur = devs; cur; cur = cur->next) {
        count++;
        printf("Interface %d:\n", count);
        printf("  Path: %s\n", cur->path);
        printf("  VID/PID: %04x:%04x\n", cur->vendor_id, cur->product_id);
        printf("  Interface: %d\n", cur->interface_number);
        printf("  Usage Page: 0x%04x\n", cur->usage_page);
        printf("  Usage: 0x%04x\n", cur->usage);
        printf("  Product: %ls\n", cur->product_string);
        printf("  Manufacturer: %ls\n", cur->manufacturer_string);
        printf("\n");
    }

    printf("Total interfaces found: %d\n", count);

    hid_free_enumeration(devs);
    hid_exit();

    return 0;
}
