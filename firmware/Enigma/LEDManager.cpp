// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

#include "esp32-hal.h"
/*
 * LEDManager.cpp - LED strip allocation and rendering implementation
 */

#include "LEDManager.h"
#include "EnigmaLogger.h"

LEDManager* LEDManager::_instance = nullptr;

LEDManager::LEDManager()
  : _stringCount(0)
  , _brightness(255)
  , _finalized(false)

  , _blankingMode(BLANKING_OFF)
  , _disruptionStartMs(0)
  , _disruptionDurationMs(0)
  , _pulseActive(false)
  , _pulseStartMs(0)
{
  memset(_strings, 0, sizeof(_strings));
}

LEDManager::~LEDManager() {
  // Free allocated arrays
  for (uint8_t i = 0; i < _stringCount; i++) {
    if (_strings[i].leds) {
      delete[] _strings[i].leds;
    }
  }
}

LEDManager* LEDManager::getInstance() {
  if (!_instance) {
    _instance = new LEDManager();
  }
  return _instance;
}

CRGB* LEDManager::addLEDString(uint8_t pin, uint8_t maxLEDs) {
  if (_finalized) {
    EnigmaLogger::error("Cannot add string after finalize()");
    return nullptr;
  }
  
  if (_stringCount >= MAX_LED_STRINGS) {
    EnigmaLogger::error("Max LED strings reached");
    return nullptr;
  }
  
  if (maxLEDs > MAX_LEDS_PER_STRING) {
    maxLEDs = MAX_LEDS_PER_STRING;
  }
  
  // Allocate array
  CRGB* array = new CRGB[maxLEDs];
  if (!array) {
    EnigmaLogger::error("Failed to allocate LED array");
    return nullptr;
  }
  
  memset(array, 0, maxLEDs * sizeof(CRGB));
  
  _strings[_stringCount].pin = pin;
  _strings[_stringCount].leds = array;
  _strings[_stringCount].count = maxLEDs;
  _strings[_stringCount].nextIndex = 1; // index 0 reserved as sig-integrity buffer

  _stringCount++;
  
  EnigmaLogger::debug("Added LED string: pin=%d, maxLEDs=%d", pin, maxLEDs);
  return array;
}

uint8_t LEDManager::allocateLEDs(CRGB* stringArray, uint8_t count) {
  LEDString* str = findString(stringArray);
  if (!str) {
    EnigmaLogger::error("Unknown LED string array");
    return 255;
  }
  
  if (str->nextIndex + count > str->count) {
    EnigmaLogger::error("LED allocation exceeds string capacity");
    return 255;
  }
  
  uint8_t startIndex = str->nextIndex;
  str->nextIndex += count;
  
  return startIndex;
}

void LEDManager::begin() {
  EnigmaLogger::info("LEDManager initializing");
}

uint8_t LEDManager::allocateLEDs(uint8_t count) {
  if (_stringCount == 0) {
    begin();  // Auto-initialize if needed
  }
  return allocateLEDs(_strings[0].leds, count);
}

void LEDManager::finalize() {
  if (_finalized) {
    return;
  }
  
  // Initialize FastLED for each string
  for (uint8_t i = 0; i < _stringCount; i++) {
    LEDString& str = _strings[i];
    
    // Use template magic to add the correct pin
    EnigmaLogger::debug("adding %d leds to pin %d, addr = %lx", str.count, str.pin, str.leds);
    switch (str.pin) {
      case 6: FastLED.addLeds<LED_TYPE, 6, COLOR_ORDER>(str.leds, str.count); break;
      case 10: FastLED.addLeds<LED_TYPE, 10, COLOR_ORDER>(str.leds, str.count); break;
      case 11: FastLED.addLeds<LED_TYPE, 11, COLOR_ORDER>(str.leds, str.count); break;
      case 12: FastLED.addLeds<LED_TYPE, 12, COLOR_ORDER>(str.leds, str.count); break;
      case 13: FastLED.addLeds<LED_TYPE, 13, COLOR_ORDER>(str.leds, str.count); break;
      case 14: FastLED.addLeds<LED_TYPE, 14, COLOR_ORDER>(str.leds, str.count); break;
      case 18: FastLED.addLeds<LED_TYPE, 18, COLOR_ORDER>(str.leds, str.count); break;
      case 21: FastLED.addLeds<LED_TYPE, 21, COLOR_ORDER>(str.leds, str.count); break;
      case 38: FastLED.addLeds<LED_TYPE, 38, COLOR_ORDER>(str.leds, str.count); break;
      case 41: FastLED.addLeds<LED_TYPE, 41, COLOR_ORDER>(str.leds, str.count); break;
      case 45: FastLED.addLeds<LED_TYPE, 45, COLOR_ORDER>(str.leds, str.count); break;
      case 47: FastLED.addLeds<LED_TYPE, 47, COLOR_ORDER>(str.leds, str.count); break;
      case 48: FastLED.addLeds<LED_TYPE, 48, COLOR_ORDER>(str.leds, str.count); break;
      // Add more pins as needed
      default:
        EnigmaLogger::error("Unsupported Enigma LED pin: %d", str.pin);
    }
    
    EnigmaLogger::info("FastLED initialized: pin=%d, count=%d", str.pin, str.count);
  }
  // Set FastLED brightness to max - we apply brightness ourselves in applyBrightness()
  FastLED.setBrightness(255);

  FastLED.clear();
  FastLED.show();
  _finalized = true;
}

void LEDManager::setBlanking(BlankingMode mode, uint8_t param) {
  _blankingMode = mode;
  
  if (mode == BLANKING_DISRUPTION) {
    _disruptionStartMs = millis();
    _disruptionDurationMs = param * 100UL;  // Convert tenths of seconds to ms
//    EnigmaLogger::info("Disruption blanking: %d.%d seconds", param / 10, param % 10);
  }
}

void LEDManager::pulse() {
  _pulseActive = true;
  _pulseStartMs = millis();
//  EnigmaLogger::debug("LED pulse triggered");
}

bool LEDManager::shouldBlankControl(uint8_t stringIndex, uint8_t ledIndex, unsigned long currentMs) {
  if (_blankingMode != BLANKING_DISRUPTION) {
    return false;
  }
  
  // Check if disruption period is over
  unsigned long elapsed = currentMs - _disruptionStartMs;
  if (elapsed >= _disruptionDurationMs) {
    // Disruption period ended - go to full blank
    _blankingMode = BLANKING_ON;
    return true;
  }
  
  // Calculate probability of blanking based on elapsed time
  // Probability increases linearly from 0% to 100% over duration
  float progress = (float)elapsed / (float)_disruptionDurationMs;
  uint8_t blankThreshold = (uint8_t)(progress * 255);
  
  // Generate pseudo-random value for this specific LED at this frame
  // Use a simple hash of stringIndex, ledIndex, and frame counter
  uint32_t frameCount = currentMs / 16;  // ~60fps frame counter
  uint32_t hash = stringIndex * 7919 + ledIndex * 6997 + frameCount * 5003;
  hash = (hash ^ (hash >> 16)) * 0x85ebca6b;
  hash = (hash ^ (hash >> 13)) * 0xc2b2ae35;
  hash = hash ^ (hash >> 16);
  
  uint8_t randomValue = hash & 0xFF;
  
  return randomValue < blankThreshold;
}

void LEDManager::setLED(CRGB* stringArray, uint8_t index, uint8_t r, uint8_t g, uint8_t b) {
  LEDString* str = findString(stringArray);
  if (str && index < str->count) {
    str->leds[index] = CRGB(r, g, b);
  }
}

void LEDManager::setLED(CRGB* stringArray, uint8_t index, CRGB color) {
  LEDString* str = findString(stringArray);
  if (str && index < str->count) {
    str->leds[index] = color;
  }
}

void LEDManager::setLED(uint8_t index, uint8_t r, uint8_t g, uint8_t b) {
  if (_stringCount > 0) {
    setLED(_strings[0].leds, index, r, g, b);
  }
}

void LEDManager::setLED(uint8_t index, CRGB color) {
  if (_stringCount > 0) {
    setLED(_strings[0].leds, index, color);
  }
}

CRGB LEDManager::getLED(CRGB* stringArray, uint8_t index) const {
  LEDString* str = const_cast<LEDManager*>(this)->findString(stringArray);
  if (str && index < str->count) {
    return str->leds[index];
  }
  return CRGB::Black;
}

CRGB LEDManager::getLED(uint8_t index) const {
  if (_stringCount > 0 && index < _strings[0].count) {
    return _strings[0].leds[index];
  }
  return CRGB::Black;
}

void LEDManager::setBrightness(uint8_t brightness) {
  _brightness = brightness;
  // Don't call FastLED.setBrightness() - we apply brightness ourselves
  // in applyBrightness() with rescue logic for dim LEDs
}

void LEDManager::reset() {
  // Reset to default state
  _brightness = 255;
  _blankingMode = BLANKING_OFF;
  _pulseActive = false;
  _disruptionStartMs = 0;
  _disruptionDurationMs = 0;
  // Brightness applied in applyBrightness() during update()
}

void LEDManager::update() {
  if (!_finalized) {
    return;
  }

  unsigned long currentMs = millis();
  
  // Handle pulse (blend toward white, then fade back over PULSE_FADE_DURATION_MS)
  if (_pulseActive) {
    unsigned long elapsed = currentMs - _pulseStartMs;

    if (elapsed < PULSE_FADE_DURATION_MS) {
      // Calculate white blend amount: 1.0 -> 0.0
      float fadeProgress = (float)elapsed / (float)PULSE_FADE_DURATION_MS;
      uint8_t whiteBlend = (uint8_t)((1.0f - fadeProgress) * 255);

      // Blend each LED toward white
      for (uint8_t i = 0; i < _stringCount; i++) {
        for (uint8_t j = 1; j < _strings[i].count; j++) {
          CRGB& led = _strings[i].leds[j];
          // Blend toward white: led = led + (white - led) * whiteBlend/255
          led.r += ((255 - led.r) * whiteBlend) >> 8;
          led.g += ((255 - led.g) * whiteBlend) >> 8;
          led.b += ((255 - led.b) * whiteBlend) >> 8;
        }
      }
      // Fall through to normal FastLED.show() at end of update()
    } else {
      // Fade complete
      _pulseActive = false;
    }
  }
  
  // Check if disruption period has ended - CHECK BEFORE APPLYING
  if (_blankingMode == BLANKING_DISRUPTION) {
    unsigned long elapsed = currentMs - _disruptionStartMs;
    if (elapsed >= _disruptionDurationMs) {
      _blankingMode = BLANKING_ON;
      
      // IMMEDIATELY blank everything - don't render one more frame
      for (uint8_t i = 0; i < _stringCount; i++) {
        for (uint8_t j = 1; j < _strings[i].count; j++) {
          _strings[i].leds[j] = CRGB::Black;
        }
      }
      applyBrightness();
      FastLED.show();
      return;  // Early exit - skip normal blanking logic
    }
  }
  
  // Apply blanking based on mode
  switch (_blankingMode) {
    case BLANKING_OFF:
      // Normal rendering - do nothing
      break;
      
    case BLANKING_ON:
      // Full blank - zero all LEDs except status
      for (uint8_t i = 0; i < _stringCount; i++) {
        for (uint8_t j = 1; j < _strings[i].count; j++) {
          _strings[i].leds[j] = CRGB::Black;
        }
      }
      break;
      
    case BLANKING_DISRUPTION:
      // Probabilistic blanking - check each LED
      for (uint8_t i = 0; i < _stringCount; i++) {
        for (uint8_t j = 1; j < _strings[i].count; j++) {
          if (shouldBlankControl(i, j, currentMs)) {
            _strings[i].leds[j] = CRGB::Black;
          }
        }
      }
      break;
  }
  applyBrightness();
  taskDISABLE_INTERRUPTS();
  FastLED.show();
  taskENABLE_INTERRUPTS();

// show() is synchronous so this is unnecessary
//  // Calculate actual transmission time
//  // Each LED = 24 bits x 1.25us = 30us
//  uint32_t totalLEDs = 0;
//  for (uint8_t i = 0; i < _stringCount; i++) {
//    totalLEDs += _strings[i].count;
//  }
//  uint32_t transmitTime = (totalLEDs * 30) + 100; // +100us margin

//  delayMicroseconds(transmitTime);

//  FastLED.show();
}

void LEDManager::applyBrightness() {
  if (_brightness == 255) return;  // No scaling needed

  for (uint8_t i = 0; i < _stringCount; i++) {
    for (uint8_t j = 0; j < _strings[i].count; j++) {
      CRGB& led = _strings[i].leds[j];

      if (led.r == 0 && led.g == 0 && led.b == 0) continue;  // Black stays black

      // Save originals before scaling
      uint8_t origR = led.r, origG = led.g, origB = led.b;

      // WS2812 LEDs need values of 2+ to actually emit visible light
      const uint8_t MIN_VISIBLE = 2;

      // Apply brightness scaling
      led.r = (origR * _brightness) >> 8;
      led.g = (origG * _brightness) >> 8;
      led.b = (origB * _brightness) >> 8;

      // Find max scaled channel
      uint8_t maxScaled = led.r;
      if (led.g > maxScaled) maxScaled = led.g;
      if (led.b > maxScaled) maxScaled = led.b;

      // Rescue if max scaled is below visible threshold
      if (maxScaled < MIN_VISIBLE) {
        // Find max original channel
        uint8_t maxOrig = origR;
        if (origG > maxOrig) maxOrig = origG;
        if (origB > maxOrig) maxOrig = origB;
        if (maxOrig == 0) maxOrig = 1;  // Safety, shouldn't happen
        // Scale so max channel = MIN_VISIBLE, others proportional
        led.r = (origR * MIN_VISIBLE) / maxOrig;
        led.g = (origG * MIN_VISIBLE) / maxOrig;
        led.b = (origB * MIN_VISIBLE) / maxOrig;
      }
    }
  }
}

LEDString* LEDManager::findString(CRGB* array) {
  for (uint8_t i = 0; i < _stringCount; i++) {
    if (_strings[i].leds == array) {
      return &_strings[i];
    }
  }
  return nullptr;
}