// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

/*
 * LEDAnimator.h - Base class for LED animations
 * 
 * Each animator manages a range of LEDs and renders to LEDManager
 */

#ifndef LED_ANIMATOR_H
#define LED_ANIMATOR_H

#include <Arduino.h>
#include <FastLED.h>
#include "LEDManager.h"

enum AnimationMode : uint8_t {
  ANIM_MODE_SOLID = 0,
  ANIM_MODE_BLINK = 1,
  ANIM_MODE_FADE = 2
};

class LEDAnimator {
public:
  LEDAnimator(uint8_t startIndex, uint8_t count, CRGB* ledArray, uint32_t timebaseMs);
  virtual ~LEDAnimator() {}
  
  // Called by board to render this animator's LEDs
  // Animator calls LEDManager::setLED() to update its range
  virtual void render(unsigned long currentMs) = 0;
  
  // Configuration
  void setTimebase(uint32_t timebaseMs) { _timebaseMs = timebaseMs; }
  void setPeriod(uint16_t periodMs) { _periodMs = periodMs; }
  void setDutyCycle(uint16_t dutyCycleMs) { _dutyCycleMs = dutyCycleMs; }
  void setColors(uint8_t r1, uint8_t g1, uint8_t b1, 
                 uint8_t r2, uint8_t g2, uint8_t b2);
  
  uint8_t getStartIndex() const { return _startIndex; }
  uint8_t getCount() const { return _count; }
  
protected:
  CRGB* _ledArray;
  uint8_t _startIndex;
  uint8_t _count;
  uint32_t _timebaseMs;     // Sync point from host
  uint16_t _periodMs;       // Animation period
  uint16_t _dutyCycleMs;    // time within _periodMs spent on color1
  CRGB _color1;
  CRGB _color2;
  
  // Get current duty cycle within period
  float getDutyCycle(unsigned long currentMs) const;

};

// ============================================================================
// Solid Color Animator - all LEDs same color
// ============================================================================
class SolidAnimator : public LEDAnimator {
public:
  SolidAnimator(uint8_t startIndex, uint8_t count, 
                CRGB* ledArray,
                uint8_t r, uint8_t g, uint8_t b,
                uint32_t timebaseMs);
  
  void render(unsigned long currentMs) override;
};

// ============================================================================
// Blink Animator - switches between two colors
// ============================================================================
class BlinkAnimator : public LEDAnimator {
public:
  BlinkAnimator(uint8_t startIndex, uint8_t count,
                CRGB* ledArray,
                uint8_t r1, uint8_t g1, uint8_t b1,
                uint8_t r2, uint8_t g2, uint8_t b2,
                uint16_t periodMs, uint16_t dutyCycleMs,
                uint32_t timebaseMs);
  
  void render(unsigned long currentMs) override;
};

// ============================================================================
// Fade Animator - smoothly transitions between two colors
// ============================================================================
class FadeAnimator : public LEDAnimator {
public:
  FadeAnimator(uint8_t startIndex, uint8_t count,
               CRGB* ledArray,
               uint8_t r1, uint8_t g1, uint8_t b1,
               uint8_t r2, uint8_t g2, uint8_t b2,
               uint16_t periodMs, uint16_t dutyCycleMs,
               uint32_t timebaseMs);
  
  void render(unsigned long currentMs) override;
};

// ============================================================================
// Factory function - creates appropriate animator based on mode
// ============================================================================
LEDAnimator* createAnimator(AnimationMode mode, 
                            uint8_t startIndex, uint8_t count,
                            CRGB* ledArray,
                            uint8_t r1, uint8_t g1, uint8_t b1,
                            uint8_t r2, uint8_t g2, uint8_t b2,
                            uint16_t periodMs, uint16_t dutyCycleMs,
                            uint32_t timebaseMs);

#endif