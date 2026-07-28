// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

/*
 * Config.cpp - Configuration implementation
 */

#include <Arduino.h>
#include <Preferences.h>
#include "esp_crc.h"

#include "Config.h"
//#include "Board.h"
#include "EnigmaLogger.h"
#include "LEDManager.h"

#define BOARD_VARIANT_ADC_PIN 5
#define BOARD_ADDRESS_ADC_PIN 4
#define BOARD_DETECT_SAMPLES 20

// NVS namespace for Enigma config
#define NVS_NAMESPACE "enigma"
#define KEY_LOG_LEVEL "LogLevel"
#define DEFAULT_LOG_LEVEL LogLevel::LOG_DEBUG

uint8_t Config::_address = -1;
Config* Config::_config = nullptr;
Preferences Config::_nvs;
uint32_t Config::_timebaseMs = 0;
int Config::_logLevel = DEFAULT_LOG_LEVEL;

Config::Config() {
  _config = this;

  // Initialize NVS
  if (!_nvs.begin(NVS_NAMESPACE, false)) {
    EnigmaLogger::error( "NVS init failed");
    return;
  }
  _logLevel = (LogLevel)_nvs.getInt(KEY_LOG_LEVEL, -1);
  if (_logLevel == -1) {  // init store
    _nvs.putInt(KEY_LOG_LEVEL, (int)DEFAULT_LOG_LEVEL);
  }
/*
  // Detect hardware variant
  BoardVariant bv = detectBoardVariant();
  if (bv == BoardVariant::VARIANT_UNKNOWN) {
    EnigmaLogger::error( "BOARD NOT RECOGNIZED");
    return;
  }

  Board* b = Board::newInstance(bv);
  if (!b) {
    EnigmaLogger::error( "***ERROR INSTANTIATING BOARD");
  }
*/
}

void Config::setLogLevel(int level ) {
  _logLevel = level;
  _nvs.putInt( KEY_LOG_LEVEL, _logLevel );
}

int Config::getLogLevel() {
  return _logLevel;
}

BoardVariant Config::detectBoardVariant() {
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
  pinMode(BOARD_VARIANT_ADC_PIN, INPUT);

  // detect board variant resistor
  long sum = 0;
  for (int i = 0; i < BOARD_DETECT_SAMPLES; i++) {
    sum += analogRead(BOARD_VARIANT_ADC_PIN);
    delay(10);  // Small delay between samples if needed
  }             // for
  int averageValue = sum / BOARD_DETECT_SAMPLES;

  EnigmaLogger::debug("Variant detect ADC: %d\n", averageValue);

  // Map ADC ranges to variants
  // These thresholds depend on your resistor divider network
  if (averageValue >= 0 && averageValue <= 450) {
    return BoardVariant::VARIANT_SW14;
  } else if (averageValue >= 460 && averageValue < 630) {
    return BoardVariant::VARIANT_BM16;
  } else if (averageValue >= 650 && averageValue < 850) {
    return BoardVariant::VARIANT_AN08;
//    return BoardVariant::VARIANT_QD04;
  } else if (averageValue >= 900 && averageValue < 1100) {
    return BoardVariant::VARIANT_QD04;
  } else if (averageValue >= 1200 && averageValue < 1400) {
    return BoardVariant::VARIANT_UD08;
  } else if (averageValue >= 1500 && averageValue < 1800) {
    return BoardVariant::VARIANT_SC16;
  } else if (averageValue >= 1900 && averageValue < 2200) {
    return BoardVariant::VARIANT_DC04;
  } else if (averageValue >= 2300 && averageValue < 2600) {
    return BoardVariant::VARIANT_RL16;
  } else if (averageValue >= 2700 && averageValue < 2900) {
    return BoardVariant::VARIANT_LC04;
  } else if (averageValue >= 3000 && averageValue < 3200) {
    return BoardVariant::VARIANT_AU04;
  } else if (averageValue >= 3300 && averageValue < 3450) {
    return BoardVariant::VARIANT_AC08;
  } else if (averageValue >= 3500 && averageValue < 3600) {
    return BoardVariant::VARIANT_MO04;
  } else if (averageValue >= 3675 && averageValue < 3750) {
    return BoardVariant::VARIANT_UNKNOWN;
  } else if (averageValue >= 3790 && averageValue < 4095) {
    return BoardVariant::VARIANT_UNKNOWN;
  }
  return BoardVariant::VARIANT_UNKNOWN;
}

uint8_t Config::detectBoardAddress() {
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
  pinMode(BOARD_ADDRESS_ADC_PIN, INPUT);

  // detect address resistor
  uint32_t sum = 0;
  uint32_t averageValue;
  for (int i = 0; i < BOARD_DETECT_SAMPLES; i++) {
    sum += analogRead(BOARD_ADDRESS_ADC_PIN);
    delay(10);  // Small delay between samples if needed
  }             // for
  averageValue = sum / BOARD_DETECT_SAMPLES;

  EnigmaLogger::debug("Address detect ADC: %d\n", averageValue);
  // index of adc reading maps to address
  //                0    1    2    3    4     5    6    7    8     9   10   11   12   13   14   15
  int values[] = { 4095, 327, 620, 216, 1092, 260, 430, 181, 1720, 288, 507, 200, 795, 235, 373, 169 };
  int dMin = 9999;
  _address = -1;
  for (int i = 0; i < 16; i++) {
    int delta = abs((int)averageValue - values[i]);
    if (delta < dMin) {
      dMin = delta;
      _address = i;
    }
  }
  EnigmaLogger::debug("Address = %d\n", _address);
  return _address;
}

// ============================================================================
// NVS Storage Methods
// ============================================================================

bool Config::saveControlConfig(uint8_t controlNum, const uint8_t* data, size_t len) {
  if (controlNum < 1 || controlNum > 16) {
    EnigmaLogger::error( "Invalid control number: %d", controlNum);
    return false;
  }

  if (!data || len == 0 || len > 256) {
    EnigmaLogger::error("Invalid config data size: %d", len);
    return false;
  }

  // Generate key name: "ctrl_1", "ctrl_2", etc.
  char key[16];
  snprintf(key, sizeof(key), "ctrl_%d", controlNum);

  // Write to NVS
  size_t written = _nvs.putBytes(key, data, len);
  if (written != len) {
    EnigmaLogger::error( "NVS write failed for %s", key);
    return false;
  }

  EnigmaLogger::debug("Saved config for control %d (%d bytes)", controlNum, len);
  return true;
}

bool Config::loadControlConfig(uint8_t controlNum, uint8_t* data, size_t len) {
  if (controlNum < 1 || controlNum > 16) {
    EnigmaLogger::warning("Invalid control number: %d", controlNum);
    return false;
  }

  if (!data || len == 0) {
    EnigmaLogger::warning("Invalid buffer for loading config");
    return false;
  }

  // Generate key name
  char key[16];
  snprintf(key, sizeof(key), "ctrl_%d", controlNum);

  // Check if key exists
  if (!_nvs.isKey(key)) {
    EnigmaLogger::debug("No stored config for control %d", controlNum);
    return false;
  }

  // Read from NVS
  size_t read = _nvs.getBytes(key, data, len);
  if (read == 0) {
    EnigmaLogger::warning("NVS read failed for %s (expected %d, got %d)",
                          key, len, read);
    return false;
  }

  Serial.printf("Loaded config for control %d (%d bytes)\n", controlNum, read);
  return true;
}

uint32_t Config::calculateConfigCRC() {
  uint8_t* allData = (uint8_t*)malloc(1024);
  if (!allData) {
 //   EnigmaLogger::error( "Failed to allocate CRC buffer");
    return 0;
  }
  
  size_t totalLen = 0;
  
//  for (uint8_t controlNum = 1; controlNum <= 16; controlNum++) {
  for (uint8_t controlNum = 1; controlNum <= Board::getBoard()->getControlCount(); controlNum++) {
    char key[16];
    snprintf(key, sizeof(key), "ctrl_%d", controlNum);
    
    if (!_nvs.isKey(key)) {
      continue;
    }
    
    size_t len = _nvs.getBytesLength(key);
    if (len > 0 && (totalLen + len) <= 1024) {
      size_t offset = totalLen;
      _nvs.getBytes(key, &allData[totalLen], len);
      totalLen += len;
    }
  }
  uint32_t crc = esp_crc32_le(0, allData, totalLen);
  
//  Serial.printf("CRC TOTAL: %d bytes, crc=%08X\n", totalLen, crc);
  
  free(allData);
//  EnigmaLogger::debug("Config CRC32: %08X (%d bytes)", crc, totalLen);
  return crc;
}

uint8_t Config::getU8(const uint8_t* buf, size_t offset) {
  return buf[offset];
}

uint16_t Config::getU16(const uint8_t* buf, size_t offset) {
  // Always little-endian from HID
  return (uint16_t)buf[offset] | ((uint16_t)buf[offset + 1] << 8);
}

uint32_t Config::getU32(const uint8_t* buf, size_t offset) {
  // Always little-endian from HID
  return (uint32_t)buf[offset] | 
         ((uint32_t)buf[offset + 1] << 8) |
         ((uint32_t)buf[offset + 2] << 16) |
         ((uint32_t)buf[offset + 3] << 24);
}

void Config::setU8(uint8_t* buf, size_t offset, uint8_t val) {
  buf[offset] = val;
}

void Config::setU16(uint8_t* buf, size_t offset, uint16_t val) {
  // Little-endian
  buf[offset] = (uint8_t)(val & 0xFF);
  buf[offset + 1] = (uint8_t)((val >> 8) & 0xFF);
}

void Config::setU32(uint8_t* buf, size_t offset, uint32_t val) {
  // Little-endian
  buf[offset] = (uint8_t)(val & 0xFF);
  buf[offset + 1] = (uint8_t)((val >> 8) & 0xFF);
  buf[offset + 2] = (uint8_t)((val >> 16) & 0xFF);
  buf[offset + 3] = (uint8_t)((val >> 24) & 0xFF);
}

void Config::getString(const uint8_t* buf, size_t offset, char* dest, size_t maxLen) {
  strncpy(dest, (const char*)&buf[offset], maxLen - 1);
  dest[maxLen - 1] = '\0';
}

bool Config::clearAllConfigs() {
  EnigmaLogger::info("Clearing all stored configs");
  return _nvs.clear();
}

bool Config::hasStoredConfig(uint8_t controlNum) {
  if (controlNum < 1) {
    return false;
  }

  char key[16];
  snprintf(key, sizeof(key), "ctrl_%d", controlNum);
  return _nvs.isKey(key);
}