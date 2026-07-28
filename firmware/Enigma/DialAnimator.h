// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

/*
 * DialAnimator.h - Specialized animators for QD08 dial indicators
 * 
 * Handles gradient and ranged (multi-zone) rendering with active region
 * highlighting using various blend modes.
 */

#ifndef DIAL_ANIMATOR_H
#define DIAL_ANIMATOR_H

#include "LEDAnimator.h"
#include <FastLED.h>

// Active region blend modes
enum ActiveBlendMode : uint8_t {
  BLEND_BRIGHTEN = 0,      // Inactive 25%, active 100%
  BLEND_REPLACE = 1,       // Active uses overlay_color
  BLEND_ADDITIVE = 2,      // active = zone + overlay (clamped)
  BLEND_MULTIPLY = 3,      // active = zone * overlay / 255
  BLEND_SCREEN = 4,        // active = 255 - ((255-zone)*(255-overlay)/255)
  BLEND_ALPHA = 5          // active = lerp(zone, overlay, alpha)
};

// Zone definition for ranged mode
struct DialZone {
  uint8_t threshold;  // LED position where this zone starts (1-based)
  CRGB color;
};

// ============================================================================
// Base class for dial animators
// ============================================================================
class DialAnimator : public LEDAnimator {
public:
  DialAnimator(uint8_t startIndex, uint8_t count, CRGB* ledArray, 
               uint32_t timebaseMs);
  virtual ~DialAnimator();
  
  // Set current dial position and button state
  void setPosition(uint8_t position);
  uint8_t getPosition() const { return _position; }
  
  // Active region rendering config
  void setActiveBlendMode(ActiveBlendMode mode) { _activeBlendMode = mode; }
  void setOverlayColor(uint8_t a, uint8_t r, uint8_t g, uint8_t b);

  // Active display mode: bar (default) or tick (single LED)
  void setTickMode(bool enabled) { _tickMode = enabled; }

  // Animation mode (applies to active region, or whole dial if position=0)
  void setAnimationMode(AnimationMode mode) { _animMode = mode; }

protected:
  uint8_t _position;              // Current dial position (0 to _count)
  ActiveBlendMode _activeBlendMode;
  CRGB _overlayColor;
  uint8_t _overlayAlpha;          // For BLEND_ALPHA mode
  AnimationMode _animMode;
  bool _tickMode;                 // true = single LED tick, false = bar fill
  
  // Blend mode helpers
  CRGB getAnimatedColor(const CRGB& activeColor, const CRGB& inactiveColor, unsigned long currentMs);
  CRGB applyBlend(const CRGB& baseColor, bool isActive, unsigned long currentMs);
};

// ============================================================================
// Gradient Dial Animator - smooth color gradient from start to end
// ============================================================================
class DialGradientAnimator : public DialAnimator {
public:
  DialGradientAnimator(uint8_t startIndex, uint8_t count, CRGB* ledArray,
                       uint8_t r1, uint8_t g1, uint8_t b1,
                       uint8_t r2, uint8_t g2, uint8_t b2,
                       uint16_t periodMs, uint16_t dutyCycleMs,
                       uint32_t timebaseMs);
  
  void render(unsigned long currentMs) override;
  
  void setGradientColors(uint8_t r1, uint8_t g1, uint8_t b1,
                         uint8_t r2, uint8_t g2, uint8_t b2);

private:
  CRGB _startColor;
  CRGB _endColor;
  
  CRGB getGradientColor(uint8_t ledIndex);
};

// ============================================================================
// Ranged Dial Animator - discrete color zones
// ============================================================================
class DialRangedAnimator : public DialAnimator {
public:
  DialRangedAnimator(uint8_t startIndex, uint8_t count, CRGB* ledArray,
                     uint16_t periodMs, uint16_t dutyCycle,
                     uint32_t timebaseMs);
  
  ~DialRangedAnimator();
  
  void render(unsigned long currentMs) override;
  
  // Zone configuration
  void setZones(uint8_t numZones, const uint8_t* thresholds, const CRGB* colors);
  void clearZones();

private:
  DialZone* _zones;
  uint8_t _numZones;
  
  CRGB getZoneColor(uint8_t ledIndex);
};

#endif