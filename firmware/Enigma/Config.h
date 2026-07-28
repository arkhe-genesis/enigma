// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

/*
 * Config.h - Base configuration class for Enigma boards
 * 
 * Handles core configuration parsing and board variant detection,
 * instantiates appropriate board variant.
 */

#ifndef CONFIG_H
#define CONFIG_H
#include <cstdint>
#include <Arduino.h>
#include <Preferences.h>
#include "Board.h"

//enum BoardVariant : uint8_t;
//enum LogLevel : uint8_t;

class Config {
public:
  Config();
  virtual ~Config() {};
  
  static Config *getConfig() {return _config; };
  
  static BoardVariant detectBoardVariant();
  static uint8_t detectBoardAddress();

  static uint32_t calculateConfigCRC();
  static bool clearAllConfigs();
  static bool hasStoredConfig(uint8_t controlNum);
  static void setTimebase(uint32_t timebaseMs) { _timebaseMs = timebaseMs; }
  static uint32_t getTimebase() { return _timebaseMs; }

  // Generic buffer accessors (handle endianness)
  static uint8_t getU8(const uint8_t* buf, size_t offset);
  static uint16_t getU16(const uint8_t* buf, size_t offset);
  static uint32_t getU32(const uint8_t* buf, size_t offset);
  static void getString(const uint8_t* buf, size_t offset, char* dest, size_t maxLen);
  
  static void setU8(uint8_t* buf, size_t offset, uint8_t val);
  static void setU16(uint8_t* buf, size_t offset, uint16_t val);
  static void setU32(uint8_t* buf, size_t offset, uint32_t val);
  
  // NVS storage (raw bytes, no interpretation)
  static void setLogLevel(int level );
  static int getLogLevel();

  static bool saveControlConfig(uint8_t controlNum, const uint8_t* data, size_t len);
  static bool loadControlConfig(uint8_t controlNum, uint8_t* data, size_t maxLen);

private:
  static uint8_t _address;
  static Config *_config;

  static Preferences _nvs;
  static int _logLevel;
  static uint32_t _timebaseMs;

};

#endif