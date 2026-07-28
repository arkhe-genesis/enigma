// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

/*
 * DialAnimator.cpp - Implementation of dial-specific animators
 */

#include "DialAnimator.h"
#include "LEDManager.h"
#include <Arduino.h>

// ============================================================================
// DialAnimator Base Class
// ============================================================================

DialAnimator::DialAnimator(uint8_t startIndex, uint8_t count,
                           CRGB* ledArray, uint32_t timebaseMs)
  : LEDAnimator(startIndex, count, ledArray, timebaseMs)
  , _position(0)
  , _activeBlendMode(BLEND_BRIGHTEN)
  , _overlayColor(CRGB::Blue)
  , _overlayAlpha(128)
  , _animMode(ANIM_MODE_SOLID)
  , _tickMode(false)
{
}

DialAnimator::~DialAnimator() {
}

void DialAnimator::setPosition(uint8_t position) {
  if (position > _count) position = _count;
  _position = position;
}

void DialAnimator::setOverlayColor(uint8_t a, uint8_t r, uint8_t g, uint8_t b) {
  _overlayAlpha = a;
  _overlayColor = CRGB(r, g, b);
}

CRGB DialAnimator::getAnimatedColor(const CRGB& activeColor, const CRGB& inactiveColor, unsigned long currentMs) {
  if (_animMode == ANIM_MODE_SOLID) {
    return activeColor;
  }
  
  float phase = getDutyCycle(currentMs);
  
  if (_animMode == ANIM_MODE_BLINK) {
    // Blink between active (blended) and inactive (background)
    return (phase < 0.5f) ? activeColor : inactiveColor;
  }
  
  if (_animMode == ANIM_MODE_FADE) {
    // Fade between active and inactive using sine wave
    float t = (sin(phase * 2.0f * PI - (PI / 2.0f)) + 1.0f) / 2.0f;
    return CRGB(
      (uint8_t)(inactiveColor.r + t * (activeColor.r - inactiveColor.r)),
      (uint8_t)(inactiveColor.g + t * (activeColor.g - inactiveColor.g)),
      (uint8_t)(inactiveColor.b + t * (activeColor.b - inactiveColor.b))
    );
  }
  
  return activeColor;
}

CRGB DialAnimator::applyBlend(const CRGB& baseColor, bool isActive, unsigned long currentMs) {
  // Calculate animation phase using base class method
  float phase = getDutyCycle(currentMs);
  
  // Calculate what inactive color should be based on blend mode
  CRGB inactiveColor;
  
  if (_activeBlendMode == BLEND_BRIGHTEN) {
    // Only BRIGHTEN mode dims the inactive region
    inactiveColor = CRGB(
      baseColor.r >> 4,
      baseColor.g >> 4,
      baseColor.b >> 4
    );
  } else {
    // All other modes: inactive shows full-brightness base color
    inactiveColor = baseColor;
  }
  
  // If this LED is inactive, return the inactive color
  if (!isActive) {
    return inactiveColor;
  }
  
  // Active region - apply blend mode
  CRGB blendedColor = baseColor;
  bool alphaAlreadyApplied = false;
  
  switch (_activeBlendMode) {
    case BLEND_BRIGHTEN:
      // Full brightness (no change to base)
      blendedColor = baseColor;
      break;
      
    case BLEND_REPLACE:
      // Pure overlay color (alpha will lerp it below)
      blendedColor = _overlayColor;
      break;
      
    case BLEND_ADDITIVE:
      // Add overlay to base (clamped)
      blendedColor = CRGB(
        min(255, (int)baseColor.r + (int)_overlayColor.r),
        min(255, (int)baseColor.g + (int)_overlayColor.g),
        min(255, (int)baseColor.b + (int)_overlayColor.b)
      );
      break;
      
    case BLEND_MULTIPLY:
      // Multiply base by overlay
      blendedColor = CRGB(
        ((uint16_t)baseColor.r * (uint16_t)_overlayColor.r) / 255,
        ((uint16_t)baseColor.g * (uint16_t)_overlayColor.g) / 255,
        ((uint16_t)baseColor.b * (uint16_t)_overlayColor.b) / 255
      );
      break;
      
    case BLEND_SCREEN:
      // Screen blend: 255 - ((255-base)*(255-overlay)/255)
      blendedColor = CRGB(
        255 - (((255 - baseColor.r) * (255 - _overlayColor.r)) / 255),
        255 - (((255 - baseColor.g) * (255 - _overlayColor.g)) / 255),
        255 - (((255 - baseColor.b) * (255 - _overlayColor.b)) / 255)
      );
      break;
      
    case BLEND_ALPHA:
      // Alpha blend between inactive and overlay
      {
        float alpha = _overlayAlpha / 255.0f;
        blendedColor = CRGB(
          (uint8_t)((1.0f - alpha) * inactiveColor.r + alpha * _overlayColor.r),
          (uint8_t)((1.0f - alpha) * inactiveColor.g + alpha * _overlayColor.g),
          (uint8_t)((1.0f - alpha) * inactiveColor.b + alpha * _overlayColor.b)
        );
        alphaAlreadyApplied = true;
      }
      break;
  }
  
  // Apply alpha as final lerp between inactive and blended
  // for all modes EXCEPT BLEND_ALPHA (which already incorporated alpha)
  if (!alphaAlreadyApplied && _overlayAlpha < 255) {
    float alpha = _overlayAlpha / 255.0f;
    blendedColor = CRGB(
      (uint8_t)((1.0f - alpha) * inactiveColor.r + alpha * blendedColor.r),
      (uint8_t)((1.0f - alpha) * inactiveColor.g + alpha * blendedColor.g),
      (uint8_t)((1.0f - alpha) * inactiveColor.b + alpha * blendedColor.b)
    );
  }
  
  // Apply animation between blended (active) and inactive
  return getAnimatedColor(blendedColor, inactiveColor, currentMs);
}

// ============================================================================
// DialGradientAnimator
// ============================================================================

DialGradientAnimator::DialGradientAnimator(uint8_t startIndex, uint8_t count, 
                                           CRGB* ledArray,
                                           uint8_t r1, uint8_t g1, uint8_t b1,
                                           uint8_t r2, uint8_t g2, uint8_t b2,
                                           uint16_t periodMs, uint16_t dutyCycle,
                                           uint32_t timebaseMs)
  : DialAnimator(startIndex, count, ledArray, timebaseMs)
  , _startColor(CRGB(r1, g1, b1))
  , _endColor(CRGB(r2, g2, b2))
{
  _periodMs = periodMs;
  _dutyCycleMs = dutyCycle;
}

void DialGradientAnimator::setGradientColors(uint8_t r1, uint8_t g1, uint8_t b1,
                                             uint8_t r2, uint8_t g2, uint8_t b2) {
  _startColor = CRGB(r1, g1, b1);
  _endColor = CRGB(r2, g2, b2);
}

CRGB DialGradientAnimator::getGradientColor(uint8_t ledIndex) {
  if (_count <= 1) return _startColor;
  
  // Linear interpolation from start to end
  float t = (float)ledIndex / (float)(_count - 1);
  
  return CRGB(
    _startColor.r + (uint8_t)(t * (float)(_endColor.r - _startColor.r)),
    _startColor.g + (uint8_t)(t * (float)(_endColor.g - _startColor.g)),
    _startColor.b + (uint8_t)(t * (float)(_endColor.b - _startColor.b))
  );
}

void DialGradientAnimator::render(unsigned long currentMs) {
  // Render each LED based on position and mode
  for (uint8_t i = 0; i < _count; i++) {
    CRGB baseColor = getGradientColor(i);
    bool isActive;

    if (_tickMode) {
      // Tick mode: only the LED at the current position is active
      // Position 0 -> LED 0, Position 1 -> LED 0, Position N -> LED N-1
      uint8_t activeIndex = (_position > 0) ? (_position - 1) : 0;
      isActive = (i == activeIndex);
    } else {
      // Bar mode: all LEDs from 0 up to position are active
      // LED 0 is always active (no "all background" state at position 0)
      isActive = (i < _position) || (i == 0);
    }

    CRGB finalColor = applyBlend(baseColor, isActive, currentMs);
    LEDManager::getInstance()->setLED(_ledArray, _startIndex + i, finalColor);
  }
}

// ============================================================================
// DialRangedAnimator
// ============================================================================

DialRangedAnimator::DialRangedAnimator(uint8_t startIndex, uint8_t count, 
                                       CRGB* ledArray,
                                       uint16_t periodMs, uint16_t dutyCycleMs,
                                       uint32_t timebaseMs)
  : DialAnimator(startIndex, count, ledArray, timebaseMs)
  , _zones(nullptr)
  , _numZones(0)
{
  _periodMs = periodMs;
  _dutyCycleMs = dutyCycleMs;
}

DialRangedAnimator::~DialRangedAnimator() {
  clearZones();
}

void DialRangedAnimator::clearZones() {
  if (_zones) {
    delete[] _zones;
    _zones = nullptr;
  }
  _numZones = 0;
}

void DialRangedAnimator::setZones(uint8_t numZones, const uint8_t* thresholds, 
                                  const CRGB* colors) {
  clearZones();
  
  if (numZones == 0 || numZones > 12) return;
  
  _numZones = numZones;
  _zones = new DialZone[numZones];
  
  for (uint8_t i = 0; i < numZones; i++) {
    _zones[i].threshold = thresholds[i];
    _zones[i].color = colors[i];
  }
}

CRGB DialRangedAnimator::getZoneColor(uint8_t ledIndex) {
  if (_numZones == 0) return CRGB::Black;
  
  // LED indices are 0-based, thresholds are 1-based
  uint8_t ledPosition = ledIndex + 1;
  
  // Find the zone for this LED
  for (int i = _numZones - 1; i >= 0; i--) {
    if (ledPosition >= _zones[i].threshold) {
      return _zones[i].color;
    }
  }
  
  // Shouldn't reach here, but return first zone color as fallback
  return _zones[0].color;
}

void DialRangedAnimator::render(unsigned long currentMs) {
  // Render each LED based on position and mode
  for (uint8_t i = 0; i < _count; i++) {
    CRGB baseColor = getZoneColor(i);
    bool isActive;

    if (_tickMode) {
      // Tick mode: only the LED at the current position is active
      // Position 0 -> LED 0, Position 1 -> LED 0, Position N -> LED N-1
      uint8_t activeIndex = (_position > 0) ? (_position - 1) : 0;
      isActive = (i == activeIndex);
    } else {
      // Bar mode: all LEDs from 0 up to position are active
      // LED 0 is always active (no "all background" state at position 0)
      isActive = (i < _position) || (i == 0);
    }

    CRGB finalColor = applyBlend(baseColor, isActive, currentMs);
    LEDManager::getInstance()->setLED(_ledArray, _startIndex + i, finalColor);
  }
}