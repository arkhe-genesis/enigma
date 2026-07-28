// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

/*
 * Enigma.ino - Main firmware for Enigma HID devices
 * 
 * SETTINGS:
 * Board: ESP32-S3 Dev Module  
 * USB CDC On Boot: Disabled
 * USB Mode: USB-OTG (TinyUSB)
 * Partition Scheme: Default 4MB with spiffs (or larger)
 * Arduino ESP32 Core: 3.3.2+
 */

#include "USB.h"
#include "Config.h"
#include "Board.h"
#include "BoardSW14.h"
#include "EnigmaLogger.h"

Board* board = nullptr;
EnigmaHID* enigmaHID = nullptr;

void setup() {
  Serial.begin(115200);

EnigmaLogger::debug( "waiting 2 sec before starting up...");
delay(2000);

  EnigmaLogger::debug("Enigma Device Starting...");

  // Create configuration manager
  Config* config = new Config();

  // Detect board
  BoardVariant variant = Config::detectBoardVariant();
  if (variant == VARIANT_UNKNOWN) {
    EnigmaLogger::error("ERROR: Unknown board variant!");
    while(1) { delay(1000);  }
  }

  uint8_t address = Config::detectBoardAddress();
  // Instantiate board
  Board::setBoardVariant(variant);

  board = Board::newInstance(variant);
  
  if (!board) {
    EnigmaLogger::error("Failed to create board instance!");
    while(1) { delay(1000);  }
  }

  // Initialize board (this calls hidDevice.begin())
//EnigmaLogger::debug("initializing...");
  board->init();
//EnigmaLogger::debug("DONE initializing...");

  // Create HID (separate)
  enigmaHID = new EnigmaHID(board);  // Pass board reference

  if (!enigmaHID->begin()) {
    EnigmaLogger::error("HID initialization failed!");
    while(1) { delay(1000); }
  }
//EnigmaLogger::debug("beginning usb...");

   // start USB - this triggers enumeration
  USB.begin();
//EnigmaLogger::debug("(done)...");
  
  // Wait for enumeration
  delay(1000);
  
  EnigmaLogger::info("Initialization complete!");
  EnigmaLogger::info("=================================\n");
//sequenceColors();
}

void loop() {
  if (board) {
    board->update();
  }
  delay(10);
}