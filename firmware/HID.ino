// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

/*
 * Enigma-SW14 Main Sketch
 * 
 * Clean class-based structure for development
 * MSC config loading will be integrated later
 */

#include "ConfigSW14.h"
#include "EnigmaHID.h"
#include "EnigmaLogger.h"

// Global instances
ConfigSW14 config;
EnigmaLogger logger;

// Device-specific HID subclass
class EnigmaHID_SW14 : public EnigmaHID {
public:
  EnigmaHID_SW14(ConfigSW14* cfg) : EnigmaHID(cfg), sw14Config(cfg) {}
  
protected:
  bool processDeviceCommand(uint8_t cmd, const uint8_t* data, uint16_t len) override {
    // Handle SW14-specific commands here
    switch (cmd) {
      case 0x80:  // Example: Read switch state
        logger.debug("SW14: Read switch command");
        return true;
        
      case 0x81:  // Example: Set LED pattern
        logger.debug("SW14: Set LED pattern");
        return true;
        
      default:
        return false;
    }
  }
  
private:
  ConfigSW14* sw14Config;
};

EnigmaHID_SW14 hid(&config);

void setup() {
  Serial.begin(115200);
  delay(2000);
  
  Serial.println("\n+================================+");
  Serial.println("|     Enigma-SW14 Control        |");
  Serial.println("+================================+\n");
  
  // Initialize logger
  logger.begin();
  logger.info("System starting...");
  
  // Load configuration
  if (!config.begin()) {
    logger.setError(ERR_CONFIG_PARSE);
    logger.critical("Config load failed!");
    while(1) logger.update();  // Blink error forever
  }
  
  logger.info("Config loaded");
  
  // Initialize HID
  if (!hid.begin()) {
    logger.setError(ERR_HID_INIT);
    logger.critical("HID init failed!");
    while(1) logger.update();
  }
  
  logger.info("HID initialized");
  
  // Initialize switches and LEDs
  for (int i = 0; i < config.getSwitchCount(); i++) {
    const SwitchConfig* sw = config.getSwitch(i);
    if (sw && sw->pinSwitch > 0) {
      pinMode(sw->pinSwitch, INPUT_PULLUP);
      pinMode(sw->pinLedR, OUTPUT);
      pinMode(sw->pinLedG, OUTPUT);
      pinMode(sw->pinLedB, OUTPUT);
    }
  }
  
  logger.info("Switches configured");
  logger.setStatusColor(0, 255, 0);  // Green = ready
  
  Serial.println("\n*** SYSTEM READY ***\n");
}

void loop() {
  // Update HID (sends heartbeat)
  hid.update();
  
  // Update logger (blinks errors if any)
  logger.update();
  
  // Read switches and update LEDs
  // TODO: Implement switch polling and LED animation
  
  delay(10);
}