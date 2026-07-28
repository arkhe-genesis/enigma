# SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
# SPDX-License-Identifier: MIT

# Makefile for gpro_daemon

CC = gcc
CFLAGS = -Wall -O2 -pthread
LDFLAGS = -pthread

# Platform detection
UNAME_S := $(shell uname -s)

ifeq ($(UNAME_S),Darwin)
    # macOS - assumes hidapi installed via Homebrew.
    # IOKit + CoreFoundation are needed for IORegisterForSystemPower so
    # the daemon can drop stale HID handles on sleep/wake - without that
    # the post-wake handles are orphaned and never recover.
    CFLAGS += -I/opt/homebrew/include -I/usr/local/include
    LDFLAGS += -L/opt/homebrew/lib -L/usr/local/lib -lhidapi -framework IOKit -framework CoreFoundation
else ifeq ($(UNAME_S),Linux)
    # Linux - use pkg-config if available
    CFLAGS += $(shell pkg-config --cflags hidapi-libusb 2>/dev/null || echo "")
    LDFLAGS += $(shell pkg-config --libs hidapi-libusb 2>/dev/null || echo "-lhidapi-libusb")
endif

TARGET = enigma-gpro-daemon
SOURCE = gpro_daemon.c
INSTALL_DIR = /usr/local/bin
SOCKET_PATH = /tmp/gpro_daemon.sock

.PHONY: all clean install uninstall run test

all: $(TARGET)

$(TARGET): $(SOURCE)
	$(CC) $(CFLAGS) -o $(TARGET) $(SOURCE) $(LDFLAGS)

clean:
	rm -f $(TARGET)
	rm -f gpro_daemon
	rm -f $(SOCKET_PATH)

# Install to /usr/local/bin with root ownership
install: $(TARGET)
	@echo "Installing $(TARGET) to $(INSTALL_DIR)..."
	sudo install -m 755 $(TARGET) $(INSTALL_DIR)/
	@echo "Installation complete."
	@echo ""
	@echo "Next steps:"
	@echo "  1. Run: sudo $(INSTALL_DIR)/$(TARGET)"
	@echo "  2. Or create a launchd service (see INSTALL.md)"

# Uninstall
uninstall:
	@echo "Removing $(TARGET) from $(INSTALL_DIR)..."
	sudo rm -f $(INSTALL_DIR)/$(TARGET)
	sudo rm -f $(INSTALL_DIR)/gpro_daemon
	rm -f $(SOCKET_PATH)
	@echo "Uninstall complete."

# Run daemon (requires sudo on macOS for HID access)
run: $(TARGET)
	@echo "Starting daemon (requires sudo for HID access)..."
	sudo ./$(TARGET)

# Test build (compile only, don't run)
test: $(TARGET)
	@echo "Build successful!"
	@file $(TARGET)
	@echo ""
	@echo "To run: sudo ./$(TARGET)"
