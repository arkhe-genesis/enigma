// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

// Board.h
#ifndef BOARD_H
#define BOARD_H

#include <cstdint>
#include <cstddef>

#define MAX_BOARDID_LEN   11

// Board variants detected via ADC
enum BoardVariant {
  VARIANT_UNKNOWN = 0,
  VARIANT_SW14    = 1,  // 14 illuminated 3-position switches
  VARIANT_BM16    = 2,  // 16 illuminated pushbuttons (deprecated; superseded by SW14)
  VARIANT_AN08    = 3,  // 8 10-bit analog inputs (MCP3008T-I/SL)
  VARIANT_QD04    = 4,  // 4 quadrature knobs with RGB led strip gauges
  VARIANT_UD08    = 5,  // 8 incremental up/down counters with OLED displays
  VARIANT_SC16    = 6,  // 16 servo output controller
  VARIANT_DC04    = 7,  // 4 LCD display with animation
  VARIANT_RL16    = 8,  // 16 relay output
  VARIANT_LC04    = 9,  // 4 WS2812 LED strings up to 256 elements
  VARIANT_AU04    = 10, // 4 2-channel audio output soundclip players
  VARIANT_AC08    = 11, // 8 analog output w/ drivers
  VARIANT_MO04    = 12, // 4 bi-directional motor bridge controllers w/ PWM
  VARIANT_CUSTOM  = 255
};

class Board {

public:
    virtual ~Board();
    
    
    virtual void init() = 0;
    virtual void update() = 0;

    const char* getType() { return _boardType; }
    const BoardVariant getTypeNum() const { return _boardTypeNum; }
    const char* getID() const { return _boardID; }
    const uint8_t getAddress() { return _address; }
    
    static Board* getBoard() { return _board; }
    static void setBoardVariant(BoardVariant bv);
    static Board* newInstance(BoardVariant bv);

    // Hardware control (called by EnigmaHID)
    virtual uint8_t applyControlConfig(uint8_t controlNum, const uint8_t* rawConfig, size_t len) = 0;
    virtual bool applyControlState(uint8_t controlNum, const uint8_t* stateData, size_t len) = 0;
    virtual bool applyIndicatorUpdate(uint8_t controlNum, const uint8_t* rawStates, size_t len)  = 0;
    virtual uint8_t getControlState(uint8_t controlNum, uint8_t* buffer, size_t maxLen) = 0;
    virtual uint8_t getControlCount() = 0;

    // Enable/disable mask (bit N-1 = control N, 1=enabled, 0=disabled)
    void setEnableMask(uint16_t mask) { _enableMask = mask; }
    bool isControlEnabled(uint8_t controlNum) { return (_enableMask >> (controlNum - 1)) & 1; }

    // Callback for state changes (set by EnigmaHID)
    void setStateChangeCallback(void (*callback)(uint8_t controlNum, const uint8_t* stateData, uint8_t stateLen)) {
      _stateChangeCallback = callback;
    }

  protected:
    Board();
    void notifyStateChange(uint8_t controlNum, const uint8_t* stateData, uint8_t stateLen) {
      if (_stateChangeCallback) {
        _stateChangeCallback(controlNum, stateData, stateLen);
      }
    }
    
    void (*_stateChangeCallback)(uint8_t, const uint8_t*, uint8_t);
    uint16_t _enableMask = 0xFFFF;

    static char _boardType[5];
    static BoardVariant _boardTypeNum;
    static char _boardID[MAX_BOARDID_LEN];
    static uint8_t _address;
    static Board* _board;
};

#endif // BOARD_H