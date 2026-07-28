// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

/*
 * LEDAnimator.cpp - LED animation implementations
 */

#include "LEDAnimator.h"
#include "LEDManager.h"
#include "Config.h"
#include "EnigmaLogger.h"

// ============================================================================
// Base LEDAnimator
// ============================================================================

LEDAnimator::LEDAnimator(uint8_t startIndex, uint8_t count, 
                         CRGB* ledArray, uint32_t timebaseMs)
  : _ledArray(ledArray)
  , _startIndex(startIndex)
  , _count(count)
  , _timebaseMs(timebaseMs)
  , _periodMs(1000)
  , _dutyCycleMs(500)
  , _color1(CRGB::Black)
  , _color2(CRGB::Black)
{
}

void LEDAnimator::setColors(uint8_t r1, uint8_t g1, uint8_t b1,
                            uint8_t r2, uint8_t g2, uint8_t b2) {
  _color1 = CRGB(r1, g1, b1);
  _color2 = CRGB(r2, g2, b2);
}

float LEDAnimator::getDutyCycle(unsigned long currentMs) const {
  if (_periodMs == 0) return 0.0f;
  
  // Use global timebase from Config
  uint32_t timebase = Config::getTimebase();
  if (timebase == 0) {
    // No timebase set yet, use millis directly
    timebase = 0;
  }
  
  // Calculate elapsed time with phase offset
  uint32_t elapsed = (currentMs - timebase + _dutyCycleMs) % _periodMs;
  return (float)elapsed / (float)_periodMs;
}

// ============================================================================
// SolidAnimator
// ============================================================================

SolidAnimator::SolidAnimator(uint8_t startIndex, uint8_t count,
                             CRGB* ledArray,
                             uint8_t r, uint8_t g, uint8_t b,
                             uint32_t timebaseMs)
  : LEDAnimator(startIndex, count, ledArray, timebaseMs)
{
  _color1 = CRGB(r, g, b);
}

void SolidAnimator::render(unsigned long currentMs) {
  for (uint8_t i = 0; i < _count; i++) {
    LEDManager::getInstance()->setLED(_ledArray, _startIndex + i, _color1);
  }
}

// ============================================================================
// BlinkAnimator
// ============================================================================

BlinkAnimator::BlinkAnimator(uint8_t startIndex, uint8_t count,
                             CRGB* ledArray,
                             uint8_t r1, uint8_t g1, uint8_t b1,
                             uint8_t r2, uint8_t g2, uint8_t b2,
                             uint16_t periodMs, uint16_t dutyCycleMs,
                             uint32_t timebaseMs)
  : LEDAnimator(startIndex, count, ledArray, timebaseMs)
{
  _color1 = CRGB(r1, g1, b1);
  _color2 = CRGB(r2, g2, b2);
  _periodMs = periodMs;
  _dutyCycleMs = dutyCycleMs;
//  EnigmaLogger::debug("BA @ %d = %d,%d,%d-%d,%d,%d (%d, %d)", startIndex, r1, g1, b1, r2, g2, b2, periodMs, dutyCycleMs );
}

void BlinkAnimator::render(unsigned long currentMs) {
  // Calculate position in current cycle
  unsigned long elapsed = currentMs - _timebaseMs;
  unsigned long posInCycle = elapsed % _periodMs;
  
  // Choose color based on duty cycle
  CRGB color = (posInCycle < _dutyCycleMs) ? _color1 : _color2;
  
  for (uint8_t i = 0; i < _count; i++) {
    LEDManager::getInstance()->setLED(_ledArray, _startIndex + i, color);
  }
}

// ============================================================================
// FadeAnimator
// ============================================================================

FadeAnimator::FadeAnimator(uint8_t startIndex, uint8_t count,
                           CRGB* ledArray,
                           uint8_t r1, uint8_t g1, uint8_t b1,
                           uint8_t r2, uint8_t g2, uint8_t b2,
                           uint16_t periodMs, uint16_t dutyCycleMs,
                           uint32_t timebaseMs)
  : LEDAnimator(startIndex, count, ledArray, timebaseMs)
{
  _periodMs = periodMs;
  _dutyCycleMs = (dutyCycleMs == 0) ? (periodMs / 2) : dutyCycleMs;  // Default to 50%
  setColors(r1, g1, b1, r2, g2, b2);
//  EnigmaLogger::debug("FA @ %d = %d,%d,%d-%d,%d,%d (%d, %d)", startIndex, r1, g1, b1, r2, g2, b2, periodMs, dutyCycleMs );
}


void FadeAnimator::render(unsigned long currentMs) {
  // Calculate position in current cycle
  unsigned long elapsed = currentMs - _timebaseMs;
  unsigned long posInCycle = elapsed % _periodMs;

  float blend;
  if (posInCycle < _dutyCycleMs) {
    // Fade from color1 to color2 during duty cycle portion
    float progress = (float)posInCycle / (float)_dutyCycleMs;
    // Apply sine wave for smooth fade: 0 -> 1
    blend = (sin((progress * PI) - (PI / 2.0)) + 1.0) / 2.0;
  } else {
    // Fade from color2 back to color1 during remaining portion
    unsigned long remaining = _periodMs - _dutyCycleMs;
    unsigned long posInRemaining = posInCycle - _dutyCycleMs;
    float progress = (float)posInRemaining / (float)remaining;
    // Apply sine wave for smooth fade: 1 -> 0
    blend = 1.0 - ((sin((progress * PI) - (PI / 2.0)) + 1.0) / 2.0);
  }
  
  // Interpolate between colors using float math before casting
  CRGB color;
  color.r = (uint8_t)(_color1.r + ((_color2.r - _color1.r) * blend));
  color.g = (uint8_t)(_color1.g + ((_color2.g - _color1.g) * blend));
  color.b = (uint8_t)(_color1.b + ((_color2.b - _color1.b) * blend));
  
  for (uint8_t i = 0; i < _count; i++) {
    LEDManager::getInstance()->setLED(_ledArray, _startIndex + i, color);
  }
}

// ============================================================================
// Factory Function
// ============================================================================

LEDAnimator* createAnimator(AnimationMode mode,
                            uint8_t startIndex, uint8_t count,
                            CRGB* ledArray,
                            uint8_t r1, uint8_t g1, uint8_t b1,
                            uint8_t r2, uint8_t g2, uint8_t b2,
                            uint16_t periodMs, uint16_t dutyCycleMs,
                            uint32_t timebaseMs ) {
  switch (mode) {
    case ANIM_MODE_SOLID:
      return new SolidAnimator(startIndex, count, ledArray, r1, g1, b1, timebaseMs);
      
    case ANIM_MODE_BLINK:
      return new BlinkAnimator(startIndex, count, 
                               ledArray,
                               r1, g1, b1, r2, g2, b2,
                               periodMs, dutyCycleMs, timebaseMs);
      
    case ANIM_MODE_FADE:
      return new FadeAnimator(startIndex, count,
                              ledArray,
                              r1, g1, b1, r2, g2, b2,
                              periodMs, dutyCycleMs, timebaseMs);
      
    default:
      return new SolidAnimator(startIndex, count, ledArray, r1, g1, b1, timebaseMs);
  }
}