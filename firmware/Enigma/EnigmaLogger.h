// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

/*
 * EnigmaLogger.h - Error logging
 *
 * Emits log messages over the HID debug channel; level-gated by
 * setLogLevel(). Future: also write to log.txt on the MSC drive.
 */

#ifndef ENIGMA_LOGGER_H
#define ENIGMA_LOGGER_H
#include <Arduino.h>
#include "Config.h"

#define MAX_ERROR_LEN 128

class Config;

enum LogLevel {
  LOG_ERROR = 0,
  LOG_WARNING = 1,
  LOG_INFO = 2,
  LOG_DEBUG = 3
};

#define DEFAULT_LOG_LEVEL LogLevel::LOG_DEBUG;

class EnigmaLogger {
public:
  // Logging functions
  static void debug(const char* msg, ...);
  static void info(const char* msg, ...);
  static void warning(const char* msg, ...);
  static void error(const char* msg, ...);

  // maintenance functions
  static void setDebugLevel( LogLevel ll ) { _logLevel = ll; }
  static LogLevel getDebugLevel() { return _logLevel; }
  static void setHIDOutput(void (*callback)(uint8_t, const char*));
  static void setLogLevel(LogLevel level);
  static LogLevel getLogLevel() { return _logLevel; }

private:
  static void (*_hidCallback)(uint8_t, const char* );
  static void log(LogLevel level, const char* msg);
  static LogLevel _logLevel;
};

#endif