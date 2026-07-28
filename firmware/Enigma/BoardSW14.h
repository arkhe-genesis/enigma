// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

/*
 * BoardSW14.h - 14 illuminated 3-position switches
 */

#ifndef BOARD_SW14_H
#define BOARD_SW14_H

#include <FastLED.h>
#include "Board.h"
#include "EnigmaHID.h"
#include "LEDManager.h"
#include "LEDAnimator.h"


#define SW14_NUM_CONTROLS 14

// Switch types
enum SwitchType : uint8_t {
    TYPE_MOM_OFF_MOM = 0,    // Three-position momentary (Up-Off-Down = 2-0-1)
    TYPE_PUSHBUTTON  = 1,    // Momentary pushbutton (press and release)
    TYPE_TOGGLE      = 2,    // Virtual latching (toggles state on press)
    TYPE_RADIO       = 3     // Radio button in a mutual-exclusion group
};

class BoardSW14 : public Board {
public:
    BoardSW14();
    ~BoardSW14();
    
    void init() override;
    void update() override;
    
    // Hardware control (called by EnigmaHID)
    uint8_t applyControlConfig(uint8_t controlNum, const uint8_t* rawConfig, size_t len) override;
    bool applyControlState(uint8_t controlNum, const uint8_t* stateData, size_t len) override;
    bool applyIndicatorUpdate(uint8_t controlNum, const uint8_t* rawStates, size_t len) override;
    uint8_t getControlState(uint8_t controlNum, uint8_t* buffer, size_t maxLen) override;
    uint8_t getControlCount() override;
    
private:
    // Switch ADC pins
    static const int _switchPins[SW14_NUM_CONTROLS];
    
    // LED indices (allocated from LEDManager)
    uint8_t _ledIndices[SW14_NUM_CONTROLS];
    
    // Current switch states (0, 1, 2)
    uint8_t _currentStates[SW14_NUM_CONTROLS];
    
    // Last physical readings (for edge detection)
    uint8_t _lastPhysicalStates[SW14_NUM_CONTROLS];

    // Hold timer tracking
    unsigned long _pressStartMs[SW14_NUM_CONTROLS];   // When button was pressed
    unsigned long _releaseMs[SW14_NUM_CONTROLS];      // When button was released
    uint8_t _heldState[SW14_NUM_CONTROLS];            // Which state to hold (1 or 2)

    CRGB* _ledString; // one string off gpio 48

    // Animators: 14 controls x 3 states each
    LEDAnimator* _animators[SW14_NUM_CONTROLS][3];
    
    // Switch sampling
    void sampleSwitches(uint16_t* dest);
    uint8_t getSwitchState(uint16_t adcValue);
    void checkSwitchChanges();
    void deactivateRadioGroup(uint8_t group, uint8_t excludeIndex);
    
    struct ControlConfig {
        bool hasConfig;
        uint8_t type;
        uint8_t defaultState;
        uint8_t group;
        uint16_t holdMs[3];     // # milliseconds to hold indicator in a state for visual feedback
        bool reportToHost[3];  // For each of 3 states
    };
    ControlConfig _controlConfigs[SW14_NUM_CONTROLS];
    
    // Animator management
    void updateAnimator(uint8_t controlNum, uint8_t stateNum, 
                    const uint8_t* stateConfig);

    // LED rendering
    void renderLEDs();

};


#endif // BOARD_SW14_H