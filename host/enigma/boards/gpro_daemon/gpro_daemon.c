// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

/*
 * gpro_daemon.c - Logitech G Pro Keyboard HID Proxy Daemon
 *
 * This daemon provides a Unix socket interface to the Logitech G Pro keyboard,
 * forwarding RGB commands and keyboard events between Python clients and the
 * HID device. It runs with elevated privileges to access the HID interfaces.
 *
 * Protocol:
 *   Python -> Daemon: [1 byte size][size bytes padded data]
 *                    Size is 20 or 64 (the HID packet length)
 *   Daemon -> Python: Key events (0xFF + 8 bytes)
 *   (RGB responses not forwarded - LED commands are fire-and-forget)
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>
#include <signal.h>
#include <errno.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <hidapi/hidapi.h>
#ifdef __APPLE__
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOMessage.h>
#include <IOKit/pwr_mgt/IOPMLib.h>
#endif

// Logitech G Pro keyboard identifiers
#define GPRO_VID 0x046d
#define GPRO_PID 0xc339
#define RGB_USAGE_PAGE 0xff43
#define RGB_INTERFACE 1
#define KBD_USAGE_PAGE 0x0001
#define KBD_USAGE 0x0006

// Socket configuration
#define SOCKET_PATH "/tmp/gpro_daemon.sock"
#define MAX_CLIENTS 1

// Global state
static hid_device *rgb_dev = NULL;
static hid_device *kbd_dev = NULL;
static int client_fd = -1;
static pthread_mutex_t socket_lock = PTHREAD_MUTEX_INITIALIZER;
static volatile int running = 1;

// LED color cache - tracks last-sent color per key for replay on reconnect
static uint8_t key_color_cache[256][3];  // [key_id] -> {r, g, b}
static int cache_has_data = 0;

// Power-event reset flags. The power-monitor thread sets these on sleep
// and wake; the worker threads see them at the top of each loop and run
// their existing close+re-enumerate path. Cross-thread hid_close would
// race with hid_read/hid_write in the worker threads, so the power
// monitor never touches the HID handles itself - only the flags.
static volatile sig_atomic_t rgb_needs_reset = 0;
static volatile sig_atomic_t kbd_needs_reset = 0;

// Forward declarations
void signal_handler(int sig);
int open_devices(void);
void close_devices(void);
void initialize_keyboard_black(void);
void cache_update(const unsigned char *buf, int size);
void replay_cached_colors(void);
void* thread_socket_to_rgb(void* arg);
void* thread_rgb_to_socket(void* arg);
void* thread_kbd_to_socket(void* arg);
#ifdef __APPLE__
void* thread_power_monitor(void* arg);
#endif

/*
 * Signal handler - close HID devices before exit so macOS IOKit releases them
 */
void signal_handler(int sig) {
    printf("\nReceived signal %d, cleaning up...\n", sig);
    running = 0;
    close_devices();
    unlink(SOCKET_PATH);
    _exit(0);
}

/*
 * Open both HID interfaces (RGB control and keyboard)
 */
int open_devices(void) {
    struct hid_device_info *devs, *cur;
    int found_rgb = 0, found_kbd = 0;

    devs = hid_enumerate(GPRO_VID, GPRO_PID);
    if (!devs) {
        printf("No G Pro keyboard found (VID=%04x, PID=%04x) - will retry later\n",
                GPRO_VID, GPRO_PID);
        return 0;
    }

    // Find RGB control interface FIRST (keyboard interface can lock device)
    for (cur = devs; cur; cur = cur->next) {
        // RGB control interface (usage_page 0xff43) - try all 0xff43 interfaces
        if (cur->usage_page == RGB_USAGE_PAGE && !found_rgb) {
            printf("Trying RGB interface: path=%s, usage_page=0x%04x, usage=0x%04x, interface=%d\n",
                   cur->path, cur->usage_page, cur->usage, cur->interface_number);
            rgb_dev = hid_open_path(cur->path);
            if (rgb_dev) {
                printf("  -> Opened successfully!\n");
                hid_set_nonblocking(rgb_dev, 0);
                found_rgb = 1;
            } else {
                fprintf(stderr, "  -> Failed: %ls\n", hid_error(NULL));
            }
        }
    }

    // Now try keyboard interface (after RGB is secured)
    for (cur = devs; cur; cur = cur->next) {
        // Keyboard interface (usage_page 0x0001, usage 0x0006)
        if (cur->usage_page == KBD_USAGE_PAGE && cur->usage == KBD_USAGE && !found_kbd) {
            printf("Trying keyboard interface: path=%s\n", cur->path);
            kbd_dev = hid_open_path(cur->path);
            if (kbd_dev) {
                printf("  -> Opened successfully!\n");
                hid_set_nonblocking(kbd_dev, 0);
                found_kbd = 1;
            } else {
                fprintf(stderr, "  -> Failed: %ls\n", hid_error(NULL));
            }
        }
    }

    hid_free_enumeration(devs);

    if (!found_rgb) {
        printf("RGB interface not found - will retry later\n");
        close_devices();
        return 0;
    }

    if (!found_kbd) {
        fprintf(stderr, "Warning: Failed to open keyboard interface (no key events)\n");
        // Continue without keyboard - RGB will still work
    }

    return 0;
}

/*
 * Close HID devices
 */
void close_devices(void) {
    if (rgb_dev) {
        hid_close(rgb_dev);
        rgb_dev = NULL;
        printf("Closed RGB interface\n");
    }
    if (kbd_dev) {
        hid_close(kbd_dev);
        kbd_dev = NULL;
        printf("Closed keyboard interface\n");
    }
}

/*
 * Initialize all keyboard LEDs to black (prevents light leakage)
 * Uses protocol from gpro_test.py: set keys, commit, finalize
 * Must read responses after each write (per gpro_test.py _send64/_send20)
 */
void initialize_keyboard_black(void) {
    if (!rgb_dev) {
        return;
    }

    printf("Initializing all keys to black...\n");

    unsigned char response[64];

    // All USB HID scancodes we care about (from gpro_test.py KEYS dict)
    unsigned char key_ids[] = {
        // Letters A-Z
        0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f,
        0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1a, 0x1b,
        0x1c, 0x1d,
        // Numbers 1-0
        0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27,
        // Special keys
        0x28, 0x29, 0x2a, 0x2b, 0x2c, 0x2d, 0x2e, 0x2f, 0x30, 0x31, 0x33, 0x34,
        0x35, 0x36, 0x37, 0x38, 0x39,
        // Function keys
        0x3a, 0x3b, 0x3c, 0x3d, 0x3e, 0x3f, 0x40, 0x41, 0x42, 0x43, 0x44, 0x45,
        // Navigation
        0x46, 0x47, 0x48, 0x49, 0x4a, 0x4b, 0x4c, 0x4d, 0x4e, 0x4f, 0x50, 0x51, 0x52,
        // Modifiers
        0xe0, 0xe1, 0xe2, 0xe3, 0xe4, 0xe5, 0xe6, 0xe7,
        // Logo
        0x01
    };
    int num_keys = sizeof(key_ids) / sizeof(key_ids[0]);

    // Send in batches of 14 keys
    for (int i = 0; i < num_keys; i += 14) {
        unsigned char buf[64];
        memset(buf, 0, sizeof(buf));

        // Packet header: 12 ff 0c 3a 00 01 00 0e
        buf[0] = 0x12;
        buf[1] = 0xff;
        buf[2] = 0x0c;
        buf[3] = 0x3a;
        buf[4] = 0x00;
        buf[5] = 0x01;
        buf[6] = 0x00;
        buf[7] = 0x0e;

        // Add up to 14 keys (key_id, r=0, g=0, b=0)
        int offset = 8;
        for (int j = 0; j < 14 && (i + j) < num_keys; j++) {
            buf[offset++] = key_ids[i + j];
            buf[offset++] = 0x00; // R
            buf[offset++] = 0x00; // G
            buf[offset++] = 0x00; // B
        }

        // Send packet (64-byte command needs response read)
        hid_write(rgb_dev, buf, 64);
        hid_read_timeout(rgb_dev, response, 64, 100);
    }

    // Commit: 11 ff 0c 3a 00 01 00 0e (20-byte command)
    unsigned char commit[20];
    memset(commit, 0, sizeof(commit));
    commit[0] = 0x11;
    commit[1] = 0xff;
    commit[2] = 0x0c;
    commit[3] = 0x3a;
    commit[4] = 0x00;
    commit[5] = 0x01;
    commit[6] = 0x00;
    commit[7] = 0x0e;
    hid_write(rgb_dev, commit, 20);
    hid_read_timeout(rgb_dev, response, 64, 100);

    // Finalize: 11 ff 0c 5a (20-byte command)
    unsigned char finalize[20];
    memset(finalize, 0, sizeof(finalize));
    finalize[0] = 0x11;
    finalize[1] = 0xff;
    finalize[2] = 0x0c;
    finalize[3] = 0x5a;
    hid_write(rgb_dev, finalize, 20);
    hid_read_timeout(rgb_dev, response, 64, 100);

    // Turn off logo using native effect: 11 ff 0d 3c [zone] [effect] [r] [g] [b]
    // zone=0x01 (logo), effect=0x00 (off), RGB=0,0,0
    unsigned char logo_off[20];
    memset(logo_off, 0, sizeof(logo_off));
    logo_off[0] = 0x11;
    logo_off[1] = 0xff;
    logo_off[2] = 0x0d;  // Feature: effects
    logo_off[3] = 0x3c;
    logo_off[4] = 0x01;  // Zone: logo
    logo_off[5] = 0x00;  // Effect: off
    logo_off[6] = 0x00;  // R
    logo_off[7] = 0x00;  // G
    logo_off[8] = 0x00;  // B
    hid_write(rgb_dev, logo_off, 20);
    hid_read_timeout(rgb_dev, response, 64, 100);

    printf("Keyboard initialized (all keys black, logo off)\n");
}

/*
 * Update LED color cache by sniffing key color packets as they pass through.
 * Only caches 64-byte key color packets (0x12 prefix). Commit/finalize are
 * stateless and don't need caching.
 */
void cache_update(const unsigned char *buf, int size) {
    // Only 64-byte packets with 0x12 header are key color data
    if (size != 64 || buf[0] != 0x12) return;

    // Parse key colors starting at offset 8, groups of 4 bytes (id, r, g, b)
    for (int i = 8; i + 3 < size; i += 4) {
        uint8_t key_id = buf[i];
        if (key_id == 0) break;  // End of key data
        key_color_cache[key_id][0] = buf[i + 1];
        key_color_cache[key_id][1] = buf[i + 2];
        key_color_cache[key_id][2] = buf[i + 3];
    }
    cache_has_data = 1;
}

/*
 * Replay cached LED colors to a newly connected keyboard.
 * Falls back to initialize_keyboard_black() if no colors have been cached yet.
 */
void replay_cached_colors(void) {
    if (!rgb_dev) return;

    if (!cache_has_data) {
        initialize_keyboard_black();
        return;
    }

    printf("Replaying cached LED colors...\n");

    unsigned char response[64];

    // Collect all non-black keys for sending
    // (We send ALL cached keys, including black ones, to ensure full state)
    uint8_t key_ids[256];
    int key_count = 0;

    for (int i = 0; i < 256; i++) {
        // Include any key that was ever set (even to black)
        // We can't distinguish "never set" from "set to black" easily,
        // but since initialize_keyboard_black zeros everything on first
        // connect, and cache starts zeroed, replaying all 256 would be
        // wasteful. Instead, use the known key list.
        if (key_color_cache[i][0] != 0 || key_color_cache[i][1] != 0 || key_color_cache[i][2] != 0) {
            key_ids[key_count++] = i;
        }
    }

    // If all keys are black, just do the fast black init
    if (key_count == 0) {
        initialize_keyboard_black();
        return;
    }

    // First set ALL keys to black (handles keys that were explicitly set to black)
    initialize_keyboard_black();

    // Now overlay the non-black cached colors
    for (int i = 0; i < key_count; i += 14) {
        unsigned char buf[64];
        memset(buf, 0, sizeof(buf));

        buf[0] = 0x12;
        buf[1] = 0xff;
        buf[2] = 0x0c;
        buf[3] = 0x3a;
        buf[4] = 0x00;
        buf[5] = 0x01;
        buf[6] = 0x00;
        buf[7] = 0x0e;

        int offset = 8;
        for (int j = 0; j < 14 && (i + j) < key_count; j++) {
            uint8_t kid = key_ids[i + j];
            buf[offset++] = kid;
            buf[offset++] = key_color_cache[kid][0];
            buf[offset++] = key_color_cache[kid][1];
            buf[offset++] = key_color_cache[kid][2];
        }

        hid_write(rgb_dev, buf, 64);
        hid_read_timeout(rgb_dev, response, 64, 100);
    }

    // Commit
    unsigned char commit[20];
    memset(commit, 0, sizeof(commit));
    commit[0] = 0x11;
    commit[1] = 0xff;
    commit[2] = 0x0c;
    commit[3] = 0x3a;
    commit[4] = 0x00;
    commit[5] = 0x01;
    commit[6] = 0x00;
    commit[7] = 0x0e;
    hid_write(rgb_dev, commit, 20);
    hid_read_timeout(rgb_dev, response, 64, 100);

    // Finalize
    unsigned char finalize[20];
    memset(finalize, 0, sizeof(finalize));
    finalize[0] = 0x11;
    finalize[1] = 0xff;
    finalize[2] = 0x0c;
    finalize[3] = 0x5a;
    hid_write(rgb_dev, finalize, 20);
    hid_read_timeout(rgb_dev, response, 64, 100);

    printf("Replayed %d cached key colors\n", key_count);
}

/*
 * Thread: Forward commands from socket to RGB device
 *
 * Protocol: [1 byte size][size bytes padded data]
 * Reads the size byte (20 or 64), then reads that many bytes and forwards to HID
 */
void* thread_socket_to_rgb(void* arg) {
    unsigned char size_byte;
    unsigned char buf[64];
    int n;

    printf("Thread started: socket -> RGB\n");

    while (running) {
        // Power-event reset: a sleep/wake fired. Drop the orphan handle
        // here (in the same thread that owns it) so the existing reopen
        // poll below takes over. Cross-thread hid_close would race.
        if (rgb_needs_reset) {
            rgb_needs_reset = 0;
            if (rgb_dev) {
                printf("Power event: closing RGB interface for reset\n");
                hid_close(rgb_dev);
                rgb_dev = NULL;
            }
        }

        // Wait for RGB device if not yet available
        if (!rgb_dev) {
            sleep(2);
            struct hid_device_info *devs = hid_enumerate(GPRO_VID, GPRO_PID);
            for (struct hid_device_info *cur = devs; cur; cur = cur->next) {
                if (cur->usage_page == RGB_USAGE_PAGE) {
                    rgb_dev = hid_open_path(cur->path);
                    if (rgb_dev) {
                        hid_set_nonblocking(rgb_dev, 0);
                        printf("RGB interface found!\n");
                        replay_cached_colors();
                        break;
                    }
                }
            }
            hid_free_enumeration(devs);
            continue;
        }

        pthread_mutex_lock(&socket_lock);
        int fd = client_fd;
        pthread_mutex_unlock(&socket_lock);

        if (fd < 0) {
            usleep(100000); // 100ms
            continue;
        }

        // Read from socket with timeout
        fd_set readfds;
        struct timeval tv;
        tv.tv_sec = 0;
        tv.tv_usec = 100000; // 100ms

        FD_ZERO(&readfds);
        FD_SET(fd, &readfds);

        int sel = select(fd + 1, &readfds, NULL, NULL, &tv);
        if (sel <= 0) {
            // Timeout or error - check running flag
            continue;
        }

        // Read length prefix (1 byte)
        n = read(fd, &size_byte, 1);
        if (n <= 0) {
            if (n < 0 && errno != EINTR) {
                perror("Socket read error");
            }
            pthread_mutex_lock(&socket_lock);
            if (client_fd >= 0) {
                close(client_fd);
                client_fd = -1;
                printf("Client disconnected\n");
            }
            pthread_mutex_unlock(&socket_lock);
            continue;
        }

        // Validate size (must be 20 or 64)
        if (size_byte != 20 && size_byte != 64) {
            fprintf(stderr, "Invalid packet size: %d (expected 20 or 64)\n", size_byte);
            continue;
        }

        // Read 'size_byte' bytes of padded data (loop until we get all bytes)
        int total = 0;
        while (total < size_byte) {
            n = read(fd, buf + total, size_byte - total);
            if (n <= 0) {
                pthread_mutex_lock(&socket_lock);
                if (client_fd >= 0) {
                    close(client_fd);
                    client_fd = -1;
                    printf("Client disconnected\n");
                }
                pthread_mutex_unlock(&socket_lock);
                break;
            }
            total += n;
        }
        if (total != size_byte) {
            continue;  // Skip this packet
        }

        // Forward to RGB device
        if (rgb_dev) {
            int sent = hid_write(rgb_dev, buf, size_byte);
            if (sent < 0) {
                fprintf(stderr, "HID write error: %ls\n", hid_error(rgb_dev));

                // Device disconnected - try to reconnect
                printf("Keyboard disconnected, attempting to reconnect...\n");
                hid_close(rgb_dev);
                rgb_dev = NULL;

                // Try to reopen the device (retry silently)
                printf("Waiting for RGB interface to reappear...\n");
                while (running && !rgb_dev) {
                    sleep(2);

                    struct hid_device_info *devs = hid_enumerate(GPRO_VID, GPRO_PID);
                    for (struct hid_device_info *cur = devs; cur; cur = cur->next) {
                        if (cur->usage_page == RGB_USAGE_PAGE) {
                            rgb_dev = hid_open_path(cur->path);
                            if (rgb_dev) {
                                hid_set_nonblocking(rgb_dev, 0);
                                printf("RGB interface reconnected!\n");
                                replay_cached_colors();
                                break;
                            }
                        }
                    }
                    hid_free_enumeration(devs);
                }
            } else {
                // Read response (keyboard requires this even though we don't use it)
                unsigned char response[64];
                hid_read_timeout(rgb_dev, response, 64, 100);
                // Cache key colors for replay on reconnect
                cache_update(buf, size_byte);
            }
        }
    }

    printf("Thread stopped: socket -> RGB\n");
    return NULL;
}

/*
 * Thread: Forward responses from RGB device to socket
 */
void* thread_rgb_to_socket(void* arg) {
    unsigned char buf[64];
    int n;

    printf("Thread started: RGB -> socket\n");

    while (running) {
        if (!rgb_dev) {
            usleep(500000);
            continue;
        }

        pthread_mutex_lock(&socket_lock);
        int fd = client_fd;
        pthread_mutex_unlock(&socket_lock);

        if (fd < 0) {
            usleep(100000); // 100ms
            continue;
        }

        // Read from RGB device (timeout 100ms)
        n = hid_read_timeout(rgb_dev, buf, sizeof(buf), 100);

        if (n < 0) {
            // Device closed or error - exit thread
            break;
        }

        if (n > 0) {
            // Forward to socket
            pthread_mutex_lock(&socket_lock);
            if (client_fd >= 0) {
                int sent = write(client_fd, buf, n);
                if (sent < 0) {
                    perror("Socket write error (RGB)");
                }
            }
            pthread_mutex_unlock(&socket_lock);
        }
    }

    printf("Thread stopped: RGB -> socket\n");
    return NULL;
}

/*
 * Thread: Forward keyboard events to socket (with 0xFF marker)
 */
void* thread_kbd_to_socket(void* arg) {
    unsigned char buf[65]; // 0xFF + 64 byte HID report
    int n;

    printf("Thread started: keyboard -> socket\n");

    while (running) {
        // Power-event reset: same pattern as the RGB thread - drop the
        // orphan handle in the owning thread on sleep/wake so the reopen
        // poll below picks up the freshly-enumerated device.
        if (kbd_needs_reset) {
            kbd_needs_reset = 0;
            if (kbd_dev) {
                printf("Power event: closing keyboard interface for reset\n");
                hid_close(kbd_dev);
                kbd_dev = NULL;
            }
        }

        // Wait for keyboard device if not yet available
        if (!kbd_dev) {
            sleep(2);
            struct hid_device_info *devs = hid_enumerate(GPRO_VID, GPRO_PID);
            for (struct hid_device_info *cur = devs; cur; cur = cur->next) {
                if (cur->usage_page == KBD_USAGE_PAGE && cur->usage == KBD_USAGE) {
                    kbd_dev = hid_open_path(cur->path);
                    if (kbd_dev) {
                        hid_set_nonblocking(kbd_dev, 0);
                        printf("Keyboard interface found!\n");
                        break;
                    }
                }
            }
            hid_free_enumeration(devs);
            continue;
        }

        pthread_mutex_lock(&socket_lock);
        int fd = client_fd;
        pthread_mutex_unlock(&socket_lock);

        if (fd < 0) {
            usleep(100000); // 100ms
            continue;
        }

        // Read keyboard HID report (timeout 100ms)
        n = hid_read_timeout(kbd_dev, buf + 1, 64, 100);

        if (n < 0) {
            // Device disconnected - try to reconnect
            printf("Keyboard interface disconnected, attempting to reconnect...\n");
            hid_close(kbd_dev);
            kbd_dev = NULL;

            printf("Waiting for keyboard interface to reappear...\n");
            while (running && !kbd_dev) {
                sleep(2);

                struct hid_device_info *devs = hid_enumerate(GPRO_VID, GPRO_PID);
                for (struct hid_device_info *cur = devs; cur; cur = cur->next) {
                    if (cur->usage_page == KBD_USAGE_PAGE && cur->usage == KBD_USAGE) {
                        kbd_dev = hid_open_path(cur->path);
                        if (kbd_dev) {
                            hid_set_nonblocking(kbd_dev, 0);
                            printf("Keyboard interface reconnected!\n");
                            break;
                        }
                    }
                }
                hid_free_enumeration(devs);
            }

            if (!kbd_dev) {
                break;  // Daemon is shutting down
            }
            continue;
        }

        if (n > 0) {
            // Positive-edge detection: only send when keys change
            static unsigned char prev_report[64] = {0};

            // Check if report is different from previous
            if (memcmp(buf + 1, prev_report, n) != 0) {
                // Prepend marker byte
                buf[0] = 0xFF;

                // Forward to socket (including all-zero/release reports)
                pthread_mutex_lock(&socket_lock);
                int fd = client_fd;
                pthread_mutex_unlock(&socket_lock);

                if (fd >= 0) {
                    int sent = write(fd, buf, n + 1);
                    if (sent < 0) {
                        perror("Socket write error (keyboard)");
                    }
                }

                // Save current report for next comparison
                memcpy(prev_report, buf + 1, n);
            }
        }
    }

    printf("Thread stopped: keyboard -> socket\n");
    return NULL;
}

#ifdef __APPLE__
/*
 * macOS power-management callback. On sleep the keyboard's USB handle
 * becomes an orphan pointing at a gone IOKit object; on wake, hidapi
 * reads silently return 0 (no events) and writes can succeed against
 * nothing, so the existing error-based reconnect logic never trips.
 *
 * The fix: tell the worker threads "your handle is stale" on both edges.
 * They run their existing close+enumerate+reopen path from there. We
 * acknowledge the sleep so the system actually goes to sleep - never
 * call IOAllowPowerChange from the wake branch.
 */
static io_connect_t g_root_port;

static void power_callback(void *refCon, io_service_t service,
                           natural_t messageType, void *messageArgument) {
    (void)refCon; (void)service;
    switch (messageType) {
        case kIOMessageCanSystemSleep:
            // Some user-facing app could veto here; we don't, just allow.
            IOAllowPowerChange(g_root_port, (long)messageArgument);
            break;
        case kIOMessageSystemWillSleep:
            printf("Power event: system going to sleep - flagging HID for reset\n");
            rgb_needs_reset = 1;
            kbd_needs_reset = 1;
            IOAllowPowerChange(g_root_port, (long)messageArgument);
            break;
        case kIOMessageSystemHasPoweredOn:
            // Wake. The handles closed on sleep may have already been
            // reopened (if the device happened to be plugged the whole
            // time and re-enumerated fast) but the path may have changed,
            // so re-flag to force a clean re-enumerate against the new
            // IOKit registry entry.
            printf("Power event: system woke up - flagging HID for reset\n");
            rgb_needs_reset = 1;
            kbd_needs_reset = 1;
            break;
        default:
            break;
    }
}

void* thread_power_monitor(void* arg) {
    (void)arg;
    IONotificationPortRef notifyPortRef = NULL;
    io_object_t notifierObject = 0;

    g_root_port = IORegisterForSystemPower(NULL, &notifyPortRef,
                                            power_callback, &notifierObject);
    if (g_root_port == MACH_PORT_NULL) {
        fprintf(stderr, "IORegisterForSystemPower failed; sleep/wake reset disabled\n");
        return NULL;
    }

    CFRunLoopAddSource(CFRunLoopGetCurrent(),
                       IONotificationPortGetRunLoopSource(notifyPortRef),
                       kCFRunLoopCommonModes);

    printf("Power monitor thread started - listening for sleep/wake events\n");
    CFRunLoopRun();   // Blocks forever; process exit cleans up.
    return NULL;
}
#endif

/*
 * Main daemon loop
 */
int main(int argc, char *argv[]) {
    int server_fd;
    struct sockaddr_un addr;
    pthread_t thread1, thread3;
    int threads_started = 0;
#ifdef __APPLE__
    pthread_t power_thread;
#endif

    printf("Logitech G Pro Keyboard Daemon\n");
    printf("Socket: %s\n\n", SOCKET_PATH);

    // Setup signal handlers
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    signal(SIGPIPE, SIG_IGN);  // Ignore SIGPIPE from socket writes to disconnected clients

    // Initialize HIDAPI
    if (hid_init() != 0) {
        fprintf(stderr, "Failed to initialize HIDAPI\n");
        return 1;
    }

    // Create Unix domain socket FIRST (so clients can connect even before keyboard is found)
    server_fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (server_fd < 0) {
        perror("socket");
        return 1;
    }

    // Remove old socket file if exists
    unlink(SOCKET_PATH);

    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, SOCKET_PATH, sizeof(addr.sun_path) - 1);

    if (bind(server_fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        perror("bind");
        close(server_fd);
        return 1;
    }

    // Set socket permissions (readable/writable by all users)
    chmod(SOCKET_PATH, 0666);

    if (listen(server_fd, MAX_CLIENTS) < 0) {
        perror("listen");
        close(server_fd);
        return 1;
    }

#ifdef __APPLE__
    // Spawn the power-monitor thread before the accept loop. It runs a
    // CFRunLoop forever, dispatching sleep/wake notifications into the
    // rgb_needs_reset / kbd_needs_reset flags.
    pthread_create(&power_thread, NULL, thread_power_monitor, NULL);
    pthread_detach(power_thread);
#endif

    // Try to open HID devices (non-fatal if keyboard not plugged in yet)
    open_devices();

    // Initialize if device was found
    if (rgb_dev) {
        initialize_keyboard_black();
    }

    printf("Daemon ready, waiting for connections...\n\n");

    // Set accept timeout so we can check running flag
    struct timeval tv;
    tv.tv_sec = 1;
    tv.tv_usec = 0;
    setsockopt(server_fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    // Accept loop
    while (running) {
        struct sockaddr_un client_addr;
        socklen_t client_len = sizeof(client_addr);

        int new_fd = accept(server_fd, (struct sockaddr*)&client_addr, &client_len);

        if (new_fd < 0) {
            if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK) {
                continue; // Timeout or interrupted - check running flag
            }
            perror("accept");
            break;
        }

        printf("Client connected\n");

        // Set new client (disconnect old one if exists)
        pthread_mutex_lock(&socket_lock);
        if (client_fd >= 0) {
            close(client_fd);
            printf("Replaced old client connection\n");
        }
        client_fd = new_fd;
        pthread_mutex_unlock(&socket_lock);

        // Start worker threads on first connection
        if (!threads_started) {
            pthread_create(&thread1, NULL, thread_socket_to_rgb, NULL);
            // Don't forward RGB responses - LED commands are fire-and-forget
            // pthread_create(&thread2, NULL, thread_rgb_to_socket, NULL);
            pthread_create(&thread3, NULL, thread_kbd_to_socket, NULL);
            threads_started = 1;
        }
    }

    printf("\nShutting down...\n");

    // Just exit - OS cleans up sockets, HID devices, threads
    // Python clients will see broken pipe and can reconnect when daemon restarts
    return 0;
}
