// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

/*
 * LEDManager.h - Manages WS2812B LED strip allocation and rendering
 * 
 * Board-agnostic LED strip manager. Handles allocation of LED ranges
 * and updates from animators.
 */

#ifndef LED_MANAGER_H
#define LED_MANAGER_H

#include <Arduino.h>
#include <FastLED.h>

#define LED_TYPE WS2812B
#define COLOR_ORDER GRB
#define MAX_LEDS_PER_STRING 256
#define MAX_LED_STRINGS 8
#define PULSE_FADE_DURATION_MS 200

// Blanking modes
enum BlankingMode : uint8_t {
  BLANKING_OFF = 0,
  BLANKING_ON = 1,
  BLANKING_DISRUPTION = 2
};

struct LEDString {
  uint8_t pin;
  CRGB* leds;
  uint8_t count;
  uint8_t nextIndex;  // For allocateLEDs within this string
};

class LEDManager {
public:
  static LEDManager* getInstance();
  
  // Initialization sequence
  virtual void begin();

  virtual CRGB* addLEDString(uint8_t pin, uint8_t maxLEDs);  // Returns array pointer
  uint8_t allocateLEDs(CRGB* stringArray, uint8_t count);  // Returns starting index within that string
  uint8_t allocateLEDs(uint8_t count);  // Uses the first registered string

  virtual void finalize();  // Call after all allocations to init FastLED

  // Single-arg overloads target the first registered string (_strings[0]).
  void setLED(uint8_t index, uint8_t r, uint8_t g, uint8_t b);
  void setLED(uint8_t index, CRGB color);
  CRGB getLED(uint8_t index) const;
  // for multistring addressing (called by animators)
  void setLED(CRGB* stringArray, uint8_t index, uint8_t r, uint8_t g, uint8_t b);
  void setLED(CRGB* stringArray, uint8_t index, CRGB color);
  CRGB getLED(CRGB* stringArray, uint8_t index) const;


  // Global brightness
  void setBrightness(uint8_t brightness);
  uint8_t getBrightness() const { return _brightness; }
  
  // Blanking control
  void setBlanking(BlankingMode mode, uint8_t param = 0);  // param = duration for disruption in seconds
  void pulse(); // flash all controls white for impact effects
  BlankingMode getBlankingMode() const { return _blankingMode; }

  // Reset to default state
  void reset();
  
  // looped update - call after all animators have rendered their LEDs
  virtual void update();

protected:
  LEDManager();
  ~LEDManager();

  LEDString _strings[MAX_LED_STRINGS];
  uint8_t _stringCount;
  static LEDManager* _instance;
  
  uint8_t _brightness;
  bool _finalized;

  BlankingMode _blankingMode;
  // Disruption blanking state
  unsigned long _disruptionStartMs;
  uint32_t _disruptionDurationMs;
  
  // Pulse state
  bool _pulseActive;
  unsigned long _pulseStartMs;
  
  bool shouldBlankControl(uint8_t stringIndex, uint8_t ledIndex, unsigned long currentMs);

  void applyBrightness();
  LEDString* findString(CRGB* array);
};

#endif