// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

/*
 * BoardQD04.h - 4 quadrature encoder knobs with LED rings
 * 
 * Hardware: ESP32-S3 with 4 rotary encoders with integrated push buttons
 * Each encoder has an addressable LED ring indicator
 */

#ifndef BOARD_QD04_H
#define BOARD_QD04_H

#include "Board.h"
#include "DialAnimator.h"
#include <atomic>

#define QD04_NUM_CONTROLS 4
#define MAX_LEDS_PER_DIAL 100

// Display mode for dial background (bit 0 of mode flags)
enum DialMode : uint8_t {
  DIAL_MODE_GRADIENT = 0,
  DIAL_MODE_RANGED = 1
};

// Mode flag bits for SETCONFIG
#define MODE_FLAG_BACKGROUND_RANGED  0x01  // Bit 0: 0=gradient, 1=ranged
#define MODE_FLAG_ACTIVE_TICK        0x02  // Bit 1: 0=bar, 1=tick (single LED)
#define MODE_FLAG_AB_REVERSED        0x04  // Bit 2: 0=normal, 1=A/B wiring reversed
#define MODE_FLAG_INCREMENTAL        0x08  // Bit 3: 0=absolute, 1=incremental reporting

struct QD04ControlState {
  // Hardware config (from SETCONFIG)
  uint8_t numLEDs;
  uint8_t buttonMode;      // 0=momentary, 1=toggle
  uint8_t buttonReports;   // 0=don't report, 1=report
  uint8_t modeFlags;       // Bitset: see MODE_FLAG_* defines
  DialMode mode;           // Extracted from modeFlags bit 0 for convenience
  
  // Current state
  uint8_t position;        // 0 to numLEDs
  uint8_t buttonState;     // 0 or 1 (logical state)
  uint8_t lastReportedPos;
  uint8_t lastReportedBtn;
  
  // LED rendering
  CRGB* ledArray;          // Pointer to LED string for this control
  uint8_t ledStartIndex;   // Start of this control's LEDs within the string
  DialAnimator* animator;  // Gradient or Ranged animator
};

class BoardQD04 : public Board {
public:
  BoardQD04();
  virtual ~BoardQD04();
  
  void init() override;
  void update() override;
  
  // Protocol handlers (called by EnigmaHID)
  uint8_t applyControlConfig(uint8_t controlNum, const uint8_t* rawConfig, size_t len) override;
  bool applyControlState(uint8_t controlNum, const uint8_t* stateData, size_t len) override;
  bool applyIndicatorUpdate(uint8_t controlNum, const uint8_t* rawStates, size_t len) override;
  uint8_t getControlState(uint8_t controlNum, uint8_t* buffer, size_t maxLen) override;
  uint8_t getControlCount() override;

private:
  QD04ControlState _controls[QD04_NUM_CONTROLS];
  
  // Shared state with ISRs (atomic for thread safety)
  std::atomic<int32_t> _encoderRawPos[QD04_NUM_CONTROLS];
  std::atomic<uint8_t> _buttonPhysicalState[QD04_NUM_CONTROLS];
  std::atomic<bool> _encoderChanged[QD04_NUM_CONTROLS];
  std::atomic<bool> _buttonChanged[QD04_NUM_CONTROLS];
  
  // ISR state (Core 0 only, no atomic needed)
  volatile uint8_t _lastEncoderState[QD04_NUM_CONTROLS];
  volatile uint32_t _lastEncoderTime[QD04_NUM_CONTROLS];
  volatile uint32_t _lastButtonTime[QD04_NUM_CONTROLS];
  volatile uint8_t _lastButtonReading[QD04_NUM_CONTROLS];
  volatile int8_t   _encQuarterAccum[QD04_NUM_CONTROLS];
  
  // Pin assignments
  static const uint8_t ENC_A[8];
  static const uint8_t ENC_B[8];
  static const uint8_t BTN[8];
  static const uint8_t LED_PIN[8];
  
  // Helper functions
  void setupEncoderHardware();
  void updateEncoderPosition(uint8_t controlNum, int32_t rawPos);
  void updateButtonState(uint8_t controlNum);
  
  // Config parsing helpers
  bool parseGradientConfig(uint8_t controlNum, const uint8_t* data, size_t len);
  bool parseRangedConfig(uint8_t controlNum, const uint8_t* data, size_t len);
  
  // Quadrature decoding (kept for compatibility; not used by the new ISR path)
  static const int8_t ENCODER_TABLE[16];
  int8_t decodeQuadrature(uint8_t lastState, uint8_t newState);

  // ===== New: ESP-IDF GPIO ISR plumbing =====
public:
  // Context passed to ISR add call
  struct ISRContext {
    BoardQD04* self;
    uint8_t    idx;   // 0..6
  };

  // Static member ISRs so they can access private fields
 // static void IRAM_ATTR EncoderA_ISR(void* arg);
  static void IRAM_ATTR EncoderAB_ISR(void* arg); 
  static void IRAM_ATTR Button_ISR(void* arg);
};

#endif  // BOARD_QD04_H
