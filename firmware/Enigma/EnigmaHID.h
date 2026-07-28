// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

#ifndef ENIGMA_HID_H
#define ENIGMA_HID_H

#include <Arduino.h>
#include "Board.h"

// HID Command opcodes (Host -> Device)
enum HIDCommand : uint8_t {
  CMD_RESET           = 0x01,
  CMD_GETCONFIG       = 0x02,
  CMD_SETCONFIG       = 0x03,
  CMD_SETSTATE        = 0x04,
  CMD_GETSTATE        = 0x05,
  CMD_SETINDICATOR    = 0x06,
  CMD_SETBRIGHTNESS   = 0x07,
  CMD_STATUS          = 0x08,
  CMD_SETLOGLEVEL     = 0x0D,
  CMD_SETBLANKING     = 0x0E,
  CMD_PULSE           = 0x0F,
  CMD_ENABLE          = 0x10,
  CMD_VARIANT_BASE    = 0x80
};

// Device -> Host responses
enum HIDResponse : uint8_t {
  RESP_REPORTSTATE    = 0x09,
  RESP_ACK            = 0x0A,
  RESP_CONFIGREPORT   = 0x0B,
  RESP_LOGMSG         = 0x0C,
  RESP_VARIANT_BASE   = 0xC0
};

// Protocol version
#define PROTOCOL_VERSION 0x08
#define HW_VERSION 0x03
#define SW_VERSION 0x45

class EnigmaHID {
public:
  EnigmaHID(Board* board);
  ~EnigmaHID();
  
  bool begin();
  void update();
  
  // Called by EnigmaLogger
  void sendLogMessage(uint8_t level, const char* msg);
  static EnigmaHID* getInstance() { return _instance; }

private:
  Board* _board;
  
  uint32_t _nextSeq;
  uint32_t _timebaseMs;
  uint8_t _brightness;
  
  uint8_t _reportBuffer[64];
  uint8_t _logBuffer[64];
  
  // Command handlers
  void processReport(const uint8_t* data, uint16_t len);
  void handleReset(uint32_t seq, const uint8_t* payload, uint16_t len);
  void handleGetConfig(uint32_t seq, const uint8_t* payload, uint16_t len);
  void handleSetConfig(uint32_t seq, const uint8_t* payload, uint16_t len);
  void handleSetState(uint32_t seq, const uint8_t* payload, uint16_t len);
  void handleGetState(uint32_t seq, const uint8_t* payload, uint16_t len);
  void handleSetIndicator(uint32_t seq, const uint8_t* payload, uint16_t len);
  void handleSetBrightness(uint32_t seq, const uint8_t* payload, uint16_t len);
  void handleStatus(uint32_t seq, const uint8_t* payload, uint16_t len);
  void handleSetLogLevel(uint32_t seq, const uint8_t* payload, uint16_t len);
  void handleSetBlanking(uint32_t seq, const uint8_t* payload, uint16_t len);
  void handlePulse(uint32_t seq, const uint8_t* payload, uint16_t len);
  void handleEnable(uint32_t seq, const uint8_t* payload, uint16_t len);

  // Response senders
  void sendAck(uint32_t seq, uint8_t status, const char* message);
  void sendConfigReport(uint32_t seq);
  void sendStateReport(uint32_t seq, uint8_t controlNum, const uint8_t* stateData, uint8_t stateLen);
  void sendReport(const uint8_t* data, uint16_t len);
  
  // Callback from board when state changes
  static void onStateChange(uint8_t controlNum, const uint8_t* stateData, uint8_t stateLen);
  static EnigmaHID* _instance;
  
  friend class EnigmaHIDDevice;
};

#endif