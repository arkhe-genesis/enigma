// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

/*
 * EnigmaLogger.cpp - Logger implementation
 */

#include "EnigmaLogger.h"
//#include "Config.h"

//#define REPORT_WAIT_MS 50
#define MAX_LOG_LEN    128

LogLevel EnigmaLogger::_logLevel = DEFAULT_LOG_LEVEL;
void (*EnigmaLogger::_hidCallback)(uint8_t, const char* ) = nullptr;

void EnigmaLogger::setHIDOutput(void (*callback)(uint8_t, const char* )) {
  _hidCallback = callback;
}

void EnigmaLogger::setLogLevel(LogLevel level) {
  _logLevel = level;
  Config::setLogLevel( (int)_logLevel );
}

void EnigmaLogger::log(LogLevel level, const char* msg) {
  if (!_hidCallback) { // if not set up for usb msging yet, default to local
    char *levelStr[] = {"ERROR", "WARN", "INFO", "DEBUG"};
    Serial.printf("[local %s] %s", levelStr[level], msg);
    return;
  }
  
  size_t msgLen = strlen(msg);
  size_t offset = 0;
  const size_t chunkSize = 58;  // 64 - 1(cmd) - 4(seq) - 1(level) = 58 bytes for message
  
  // Break into chunks if needed
  while (offset < msgLen) {
    char chunk[59];  // 58 + null terminator
    size_t len = (msgLen - offset > chunkSize) ? chunkSize : (msgLen - offset);
    
    memcpy(chunk, msg + offset, len);
    chunk[len] = '\0';
    _hidCallback(level, chunk);
    
    offset += len;
  }
}

void EnigmaLogger::debug(const char* msg, ...) {
  if( _logLevel < LogLevel::LOG_DEBUG ) {
    return;
  }
  char buf[MAX_LOG_LEN];
  va_list args;
  va_start(args, msg);
  vsnprintf(buf, sizeof(buf), msg, args);
  va_end(args);
//  strncat(buf, "\n", MAX_LOG_LEN-1 );
  size_t len = strlen(buf);
  if (len < MAX_LOG_LEN - 2) {
    buf[len] = '\n';
    buf[len + 1] = '\0';
  }
  log(LOG_DEBUG, buf);
}

void EnigmaLogger::info(const char* msg, ...) {
  if( _logLevel < LogLevel::LOG_INFO ) {
    return;
  }
  char buf[MAX_LOG_LEN];
  va_list args;
  va_start(args, msg);
  vsnprintf(buf, sizeof(buf), msg, args);
  va_end(args);
  strncat(buf, "\n", MAX_LOG_LEN-1 );
  log(LOG_INFO, buf);
}

void EnigmaLogger::warning(const char* msg, ...) {
  if( _logLevel < LogLevel::LOG_WARNING ) {
    return;
  }
  char buf[MAX_LOG_LEN];
  va_list args;
  va_start(args, msg);
  vsnprintf(buf, sizeof(buf), msg, args);
  va_end(args);
  strncat(buf, "\n", MAX_LOG_LEN-1 );
  log(LOG_WARNING, buf);
}

void EnigmaLogger::error(const char* msg, ...) {
  if( _logLevel < LogLevel::LOG_ERROR ) {
    return;
  }
  char buf[MAX_LOG_LEN];
  va_list args;
  va_start(args, msg);
  vsnprintf(buf, sizeof(buf), msg, args);
  va_end(args);
  strncat(buf, "\n", MAX_LOG_LEN-1 );
  log(LOG_ERROR, buf);
}


