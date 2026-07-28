// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

#include "EnigmaHID.h"
#include "EnigmaLogger.h"
#include "Config.h"
#include "LEDManager.h"
#include "USB.h"
#include "USBHID.h"

USBHID HID;

static const uint8_t report_descriptor[] = {
  0x06, 0x00, 0xFF,  // Usage Page (Vendor Defined)
  0x09, 0x01,        // Usage
  0xA1, 0x01,        // Collection (Application)
  0x09, 0x02,        //   Usage
  0x15, 0x00,        //   Logical Minimum (0)
  0x26, 0xFF, 0x00,  //   Logical Maximum (255)
  0x75, 0x08,        //   Report Size (8)
  0x95, 0x40,        //   Report Count (64)
  0x81, 0x02,        //   Input
  0x09, 0x03,        //   Usage
  0x15, 0x00,        //   Logical Minimum (0)
  0x26, 0xFF, 0x00,  //   Logical Maximum (255)
  0x75, 0x08,        //   Report Size (8)
  0x95, 0x40,        //   Report Count (64)
  0x91, 0x02,        //   Output
  0xC0               // End Collection
};

// Helper macros
#define WRITE_U16_LE(buf, val) do { \
  (buf)[0] = (uint8_t)((val) & 0xFF); \
  (buf)[1] = (uint8_t)(((val) >> 8) & 0xFF); \
} while(0)

#define WRITE_U32_LE(buf, val) do { \
  (buf)[0] = (uint8_t)((val) & 0xFF); \
  (buf)[1] = (uint8_t)(((val) >> 8) & 0xFF); \
  (buf)[2] = (uint8_t)(((val) >> 16) & 0xFF); \
  (buf)[3] = (uint8_t)(((val) >> 24) & 0xFF); \
} while(0)

#define READ_U32_LE(buf) \
  ((uint32_t)(buf)[0] | ((uint32_t)(buf)[1] << 8) | \
   ((uint32_t)(buf)[2] << 16) | ((uint32_t)(buf)[3] << 24))

// Custom HID Device
class EnigmaHIDDevice : public USBHIDDevice {
public:
  EnigmaHIDDevice() {
    static bool initialized = false;
    if (!initialized) {
      initialized = true;
      HID.addDevice(this, sizeof(report_descriptor));
      _instance = this;
    }
  }
  
  void setEnigmaHID(EnigmaHID* hid) {
    _enigmaHID = hid;
  }
  
  void begin() {
    HID.begin();
  }

  uint16_t _onGetDescriptor(uint8_t* buffer) {
    memcpy(buffer, report_descriptor, sizeof(report_descriptor));
    return sizeof(report_descriptor);
  }
  
  void _onOutput(uint8_t report_id, const uint8_t* buffer, uint16_t len) {
    if (_enigmaHID && len > 0) {
      _enigmaHID->processReport(buffer, len);
    }
  }
  
  bool send(const uint8_t* data, uint16_t len) {
    if (HID.ready()) {
      return HID.SendReport(0, data, len);
    }
    return false;
  }
  
  static EnigmaHIDDevice* getInstance() {
    return _instance;
  }
  
private:
  EnigmaHID* _enigmaHID = nullptr;
  static EnigmaHIDDevice* _instance;
};

EnigmaHIDDevice* EnigmaHIDDevice::_instance = nullptr;
EnigmaHIDDevice hidDevice;

EnigmaHID* EnigmaHID::_instance = nullptr;

EnigmaHID::EnigmaHID(Board* board) 
  : _board(board)
  , _nextSeq(1)
  , _timebaseMs(0)
  , _brightness(255)
{
  _instance = this;
  memset(_reportBuffer, 0, sizeof(_reportBuffer));
  memset(_logBuffer, 0, sizeof(_logBuffer));
}

EnigmaHID::~EnigmaHID() {
  _instance = nullptr;
}

static void hidLogCallback(uint8_t level, const char* msg) {
  EnigmaHID* instance = EnigmaHID::getInstance();
  if (instance) {
//Serial.println("A"); Serial.flush();
    instance->sendLogMessage(level, msg);
//Serial.println("B"); Serial.flush();
  }
}

bool EnigmaHID::begin() {
  hidDevice.setEnigmaHID(this);
  EnigmaLogger::info("Starting Enigma HID");
  hidDevice.begin();
  EnigmaLogger::info("Registering state change callback"); 
  // Set up logging to go through HID
  _board->setStateChangeCallback(onStateChange);
  EnigmaLogger::info("Registering logging callback"); 
  EnigmaLogger::setHIDOutput(hidLogCallback);

  EnigmaLogger::info("HID started");
  return true;
}

void EnigmaHID::update() {
  // Nothing needed
}

void EnigmaHID::onStateChange(uint8_t controlNum, const uint8_t* stateData, uint8_t stateLen) {
  if (_instance) {
    _instance->sendStateReport(_instance->_nextSeq++, controlNum, stateData, stateLen);
  }
}

void EnigmaHID::sendLogMessage(uint8_t level, const char* msg) {
  memset(_logBuffer, 0, sizeof(_logBuffer));
  
  _logBuffer[0] = RESP_LOGMSG;
  WRITE_U32_LE(&_logBuffer[1], _nextSeq++);
  _logBuffer[5] = level;
  
  // Copy up to 58 bytes
  size_t len = strlen(msg);
  if (len > 58) len = 58;
  memcpy(&_logBuffer[6], msg, len);
  // Buffer is already zeroed, so positions [6+len..63] are null
  
  EnigmaHIDDevice* dev = EnigmaHIDDevice::getInstance();
  if (dev) {
    dev->send(_logBuffer, 64);
    delayMicroseconds(100);  // Wait for USB transaction
  }
}

void EnigmaHID::processReport(const uint8_t* data, uint16_t len) {
  if (len < 5) {
    return;
  }
  Serial.printf("rx %02x\n", data[0] );
  uint8_t cmd = data[0];
  uint32_t seq = READ_U32_LE(&data[1]);
  const uint8_t* payload = &data[5];
  uint16_t payloadLen = len - 5;
  
  switch (cmd) {
    case CMD_RESET:
      handleReset(seq, payload, payloadLen);
      break;
    case CMD_GETCONFIG:
Serial.println("GETCONFIG received, calling board->getConfig()");
      handleGetConfig(seq, payload, payloadLen);
Serial.println("Config response sent successfully");
      break;
    case CMD_SETCONFIG:
      handleSetConfig(seq, payload, payloadLen);
      break;
    case CMD_SETSTATE:
      handleSetState(seq, payload, payloadLen);
      break;
    case CMD_GETSTATE:
      handleGetState(seq, payload, payloadLen);
      break;
    case CMD_SETINDICATOR:
      handleSetIndicator(seq, payload, payloadLen);
      break;
    case CMD_SETBRIGHTNESS:
      handleSetBrightness(seq, payload, payloadLen);
      break;
    case CMD_STATUS:
      handleStatus(seq, payload, payloadLen);
      break;
    case CMD_SETLOGLEVEL:
      handleSetLogLevel(seq, payload, payloadLen);
    case CMD_SETBLANKING:
      handleSetBlanking(seq, payload, payloadLen);
      break;
    case CMD_PULSE:
      handlePulse(seq, payload, payloadLen);
      break;
    case CMD_ENABLE:
      handleEnable(seq, payload, payloadLen);
      break;
    case RESP_ACK:
      // Host sent ACK (shouldn't happen, but ignore gracefully)
      break;
    default:
      EnigmaLogger::warning("Unknown command: 0x%02X", cmd);
      sendAck(seq, 1, "Unknown command");
      break;
  }
}

void EnigmaHID::handleSetLogLevel(uint32_t seq, const uint8_t* payload, uint16_t len) {
  if (len < 1) {
    sendAck(seq, 1, "Invalid SETLOGLEVEL payload");
    return;
  }
  
  uint8_t level = payload[0];
  
  if (level > 3) {
    sendAck(seq, 1, "Invalid log level");
    return;
  }
  
  char rept[58];
  snprintf( rept, 48, "Log level set to %d", level );
  sendAck(seq, 0, rept);
}

void EnigmaHID::handleSetBlanking(uint32_t seq, const uint8_t* payload, uint16_t len) {
  if (len < 1) {
    sendAck(seq, 1, "Invalid SETBLANKING payload");
    return;
  }
  
  BlankingMode mode = (BlankingMode)payload[0];
  uint8_t param = (len >= 2) ? payload[1] : 0;
  
  LEDManager* ledMgr = LEDManager::getInstance();
  ledMgr->setBlanking(mode, param);

  sendAck(seq, 0, "");
}

void EnigmaHID::handlePulse(uint32_t seq, const uint8_t* payload, uint16_t len) {
  LEDManager* ledMgr = LEDManager::getInstance();
  ledMgr->pulse();

  sendAck(seq, 0, "");
}

void EnigmaHID::handleEnable(uint32_t seq, const uint8_t* payload, uint16_t len) {
  if (len < 2) return;
  uint16_t mask = (uint16_t)payload[0] | ((uint16_t)payload[1] << 8);
  _board->setEnableMask(mask);
}

void EnigmaHID::handleReset(uint32_t seq, const uint8_t* payload, uint16_t len) {
  if (len < 4) {
    sendAck(seq, 1, "Invalid RESET payload");
    return;
  }

  // Use local millis() as timebase so all boards sync to "now" when RESET is received
  // (The host's timebase value is ignored - it just triggers the sync)
  _timebaseMs = millis();
  Config::setTimebase(_timebaseMs);

  // Reset enable mask (all controls enabled)
  _board->setEnableMask(0xFFFF);

  // Reset LED manager state (blanking, brightness)
  LEDManager* ledMgr = LEDManager::getInstance();
  ledMgr->reset();

  // Load all configs and apply to board
  for (uint8_t i = 1; i <= Board::getBoard()->getControlCount(); i++) {
    uint8_t configBuf[256];
    if (Config::loadControlConfig(i, configBuf, sizeof(configBuf))) {
      _board->applyControlConfig(i, configBuf, sizeof(configBuf));
    }
  }

  sendAck(seq, 0, "");
}

void EnigmaHID::handleGetConfig(uint32_t seq, const uint8_t* payload, uint16_t len) {
  sendConfigReport(seq);
}

void EnigmaHID::handleSetConfig(uint32_t seq, const uint8_t* payload, uint16_t len) {
  if (len < 2) {
    sendAck(seq, 1, "Invalid config size");
    return;
  }
  
  uint8_t controlNum = payload[0];
  
  if (controlNum < 1 || controlNum > 16) {
    sendAck(seq, 1, "Invalid control number");
    return;
  }
  
  // Let board validate and apply config - it tells us how much to save
  uint8_t bytesToSave = _board->applyControlConfig(controlNum, payload, len);
  
  if (bytesToSave == 0) {
    sendAck(seq, 1, "Hardware config failed");
    return;
  }
  
  // Save only the valid config bytes to NVS
  if (!Config::saveControlConfig(controlNum, payload, bytesToSave)) {
    sendAck(seq, 1, "NVS write failed");
    return;
  }
  
  sendAck(seq, 0, "");
}

void EnigmaHID::handleSetState(uint32_t seq, const uint8_t* payload, uint16_t len) {
  if (len < 1) {
    sendAck(seq, 1, "Invalid SETSTATE payload");
    return;
  }
  
  uint8_t controlNum = payload[0];
  const uint8_t* stateData = &payload[1];
  uint16_t stateLen = len - 1;
  
  if (controlNum < 1 || controlNum > 16) {
    sendAck(seq, 1, "Invalid control number");
    return;
  }
  
  // Let board parse and apply the state data
  if (!_board->applyControlState(controlNum, stateData, stateLen)) {
    sendAck(seq, 1, "Hardware state update failed");
    return;
  }
  
  sendAck(seq, 0, "");
}

void EnigmaHID::handleGetState(uint32_t seq, const uint8_t* payload, uint16_t len) {
  if (len < 1) {
    sendAck(seq, 1, "Invalid GETSTATE payload");
    return;
  }
  
  uint8_t controlNum = payload[0];
  
  if (controlNum < 1 || controlNum > 16) {
    sendAck(seq, 1, "Invalid control number");
    return;
  }
  
  // Get state from board (board packs using Config helpers)
  uint8_t stateBuffer[58];  // Max state data in a report
  uint8_t stateLen = _board->getControlState(controlNum, stateBuffer, sizeof(stateBuffer));
  
  if (stateLen == 0) {
    sendAck(seq, 1, "Failed to read state");
    return;
  }
  
  // Send REPORTSTATE with variable-length state data
  sendStateReport(seq, controlNum, stateBuffer, stateLen);
}

void EnigmaHID::handleSetIndicator(uint32_t seq, const uint8_t* payload, uint16_t len) {
  if (len < 37) {  // 1 + (3 states * 12 bytes)
    sendAck(seq, 1, "Invalid SETINDICATOR payload");
    return;
  }
  
  uint8_t controlNum = payload[0];
  
  // Let board apply the 3 state configs (skip first byte which is controlNum)
  if (!_board->applyIndicatorUpdate(controlNum, &payload[1], len - 1)) {
    sendAck(seq, 1, "Indicator update failed");
    return;
  }
}

void EnigmaHID::handleSetBrightness(uint32_t seq, const uint8_t* payload, uint16_t len) {
  if (len < 1) {
    sendAck(seq, 1, "Invalid SETBRIGHTNESS payload");
    return;
  }
  
  _brightness = payload[0];
  LEDManager::getInstance()->setBrightness(_brightness);
  
  sendAck(seq, 0, "");
}

void EnigmaHID::handleStatus(uint32_t seq, const uint8_t* payload, uint16_t len) {
  sendAck(seq, 0, "");
}

void EnigmaHID::sendAck(uint32_t seq, uint8_t status, const char* message) {
  memset(_reportBuffer, 0, sizeof(_reportBuffer));
  
  _reportBuffer[0] = RESP_ACK;
  WRITE_U32_LE(&_reportBuffer[1], seq);
  _reportBuffer[5] = status;
  
  if (message && message[0]) {
    strncpy((char*)&_reportBuffer[6], message, 58);
  }
  
  sendReport(_reportBuffer, 64);
}

void EnigmaHID::sendConfigReport(uint32_t seq) {
Serial.println("Building config response...");
  memset(_reportBuffer, 0, sizeof(_reportBuffer));
  
  _reportBuffer[0] = RESP_CONFIGREPORT;
  WRITE_U32_LE(&_reportBuffer[1], seq);
  
  const char* boardType = _board->getType();
  memcpy(&_reportBuffer[5], boardType, 4);
  _reportBuffer[9] = PROTOCOL_VERSION;
  _reportBuffer[10] = HW_VERSION;
  _reportBuffer[11] = SW_VERSION;
  _reportBuffer[12] = (uint8_t)_board->getTypeNum();
  _reportBuffer[13] = _board->getAddress();

  uint32_t crc = Config::calculateConfigCRC();
//Serial.println("Header built");
  WRITE_U32_LE(&_reportBuffer[14], crc);
//Serial.println("copied");  
  sendReport(_reportBuffer, 64);
//Serial.println("sent");
}

void EnigmaHID::sendStateReport(uint32_t seq, uint8_t controlNum, const uint8_t* stateData, uint8_t stateLen) {
  memset(_reportBuffer, 0, sizeof(_reportBuffer));
  
  _reportBuffer[0] = RESP_REPORTSTATE;
  WRITE_U32_LE(&_reportBuffer[1], seq);
  _reportBuffer[5] = controlNum;
  
  // Copy variable-length state data
  if (stateLen > 0 && stateLen <= 58) {
    memcpy(&_reportBuffer[6], stateData, stateLen);
  }
  
  sendReport(_reportBuffer, 64);
}

void EnigmaHID::sendReport(const uint8_t* data, uint16_t len) {
//Serial.printf("tx %02x\n", data[0] );

  if (len > 64) len = 64;
  
  EnigmaHIDDevice* dev = EnigmaHIDDevice::getInstance();
  if (dev) {
    dev->send(data, len);
  }
}