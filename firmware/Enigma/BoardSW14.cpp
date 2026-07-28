// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

#include "BoardSW14.h"
#include "LEDManager.h"
#include "Config.h"
#include "EnigmaLogger.h"

#define RGB_LED_PIN 48

const int BoardSW14::_switchPins[SW14_NUM_CONTROLS] = {
    17, 16, 15, 6, 10, 9, 3, 8, 14, 13, 12, 11, 1, 2
};

BoardSW14::BoardSW14() : Board() {
    Board::_boardTypeNum = BoardVariant::VARIANT_SW14;
    strcpy(_boardType, "SW14");
    snprintf(_boardID, sizeof(_boardID), "ENG-%s-%02d", _boardType, Config::detectBoardAddress());
    _boardID[sizeof(_boardID)-1] = '\0';
    
    memset(_currentStates, 0, sizeof(_currentStates));
    memset(_ledIndices, 0, sizeof(_ledIndices));
    memset(_animators, 0, sizeof(_animators));
    memset(_lastPhysicalStates, 0, sizeof(_lastPhysicalStates));
    memset(_controlConfigs, 0, sizeof(_controlConfigs));
    
    memset(_pressStartMs, 0, sizeof(_pressStartMs));
    memset(_releaseMs, 0, sizeof(_releaseMs));
    memset(_heldState, 0, sizeof(_heldState));

    // Set default configs (all mom-off-mom, all states reportable)
    for (int controlNum = 0; controlNum < SW14_NUM_CONTROLS; controlNum++) {
      _controlConfigs[controlNum].hasConfig = false;
      _controlConfigs[controlNum].type = TYPE_MOM_OFF_MOM;
      _controlConfigs[controlNum].defaultState = 0;
      _controlConfigs[controlNum].group = 0;
      _controlConfigs[controlNum].reportToHost[0] = false;
      _controlConfigs[controlNum].reportToHost[1] = true;
      _controlConfigs[controlNum].reportToHost[2] = true;
      _controlConfigs[controlNum].holdMs[0] = 0;
      _controlConfigs[controlNum].holdMs[1] = 0;
      _controlConfigs[controlNum].holdMs[2] = 0;
      uint8_t configBuffer[64];  // Large enough for any config
  
      if (Config::loadControlConfig(controlNum+1, configBuffer, sizeof(configBuffer))) {
        // Apply the loaded config
        uint8_t bytesUsed = applyControlConfig(controlNum+1, configBuffer, sizeof(configBuffer));
        
        if (bytesUsed <= 0) {
          EnigmaLogger::warning("Failed to apply stored config for control %d", controlNum+1);
        }
      }
    }

    _board = this;
}

BoardSW14::~BoardSW14() {
    for (int i = 0; i < SW14_NUM_CONTROLS; i++) {
        for (int j = 0; j < 3; j++) {
            if (_animators[i][j]) {
                delete _animators[i][j];
            }
        }
    }
}

void BoardSW14::init() {
    EnigmaLogger::info("Initializing BoardSW14");
    
    // Configure ADC for switches
    analogReadResolution(12);
    analogSetAttenuation(ADC_11db);
    
    for (int i = 0; i < SW14_NUM_CONTROLS; i++) {
        pinMode(_switchPins[i], INPUT);
    }
    
    // Allocate LEDs
    _ledString = LEDManager::getInstance()->addLEDString(RGB_LED_PIN, 15);
    LEDManager::getInstance()->begin();
    
    for (int i = 0; i < SW14_NUM_CONTROLS; i++) {
        _ledIndices[i] = LEDManager::getInstance()->allocateLEDs(1);
        if (_ledIndices[i] == 255) {
            EnigmaLogger::error("Failed to allocate LED for control %d", i + 1);
            return;
        }
    }
    
    LEDManager::getInstance()->finalize();
    
    // Create default animators
    for (int i = 0; i < SW14_NUM_CONTROLS; i++) {
      _animators[i][0] = new SolidAnimator(_ledIndices[i], 1, _ledString, 0, 64, 0, 0);
      _animators[i][1] = new SolidAnimator(_ledIndices[i], 1, _ledString, 0,128, 0, 0);
      _animators[i][2] = new SolidAnimator(_ledIndices[i], 1, _ledString, 0, 128, 0, 0);
    }
    
    // Load configs from NVM and apply them
    for (uint8_t controlNum = 1; controlNum <= SW14_NUM_CONTROLS; controlNum++) {
        uint8_t configBuf[256];
        size_t len = sizeof(configBuf);
        
        if (Config::loadControlConfig(controlNum, configBuf, len)) {
            if (!applyControlConfig(controlNum, configBuf, len)) {
                EnigmaLogger::warning("Failed to apply config for control %d", controlNum);
            }
        } else {
            EnigmaLogger::debug("No config in NVS for control %d", controlNum);
        }
    }

    EnigmaLogger::info("BoardSW14 initialized successfully");
}

void BoardSW14::update() {
    checkSwitchChanges();
    renderLEDs();
    LEDManager::getInstance()->update();
}

uint8_t BoardSW14::getControlCount() {
  return SW14_NUM_CONTROLS;
}

void BoardSW14::sampleSwitches(uint16_t* dest) {
    const int samples = 5;
    uint32_t accumulator[SW14_NUM_CONTROLS] = {0};
    
    for (int s = 0; s < samples; s++) {
        for (int i = 0; i < SW14_NUM_CONTROLS; i++) {
            accumulator[i] += analogRead(_switchPins[i]);
        }
        delay(1);
    }
    
    for (int i = 0; i < SW14_NUM_CONTROLS; i++) {
        dest[i] = accumulator[i] / samples;
    }
}

uint8_t BoardSW14::getSwitchState(uint16_t adcValue) {
    if (adcValue < 1400) {
        return 1;
    } else if (adcValue < 2400) {
        return 0;
    } else {
        return 2;
    }
}

void BoardSW14::checkSwitchChanges() {
    uint16_t switchValues[SW14_NUM_CONTROLS];
    sampleSwitches(switchValues);
    unsigned long now = millis();

    for (int i = 0; i < SW14_NUM_CONTROLS; i++) {
        uint8_t physicalState = getSwitchState(switchValues[i]);
        uint8_t lastPhysical = _lastPhysicalStates[i];
        
        _lastPhysicalStates[i] = physicalState;
        
        if (physicalState == lastPhysical) {
            continue;
        }

        // Skip all state processing for disabled controls
        if (!isControlEnabled(i + 1)) {
            continue;
        }

        // Track press/release timing
        if (physicalState != 0 && lastPhysical == 0) {
            // Button pressed - record press time
            _pressStartMs[i] = now;
        } else if (physicalState == 0 && lastPhysical != 0) {
            // Button released - start hold period
            uint8_t prevState = lastPhysical;  // 1 or 2
            if (_controlConfigs[i].holdMs[prevState] > 0) {
                _releaseMs[i] = now;
                _heldState[i] = prevState;
            }
        }

        SwitchType type = (SwitchType)_controlConfigs[i].type;
        uint8_t newLogicalState = _currentStates[i];
        bool stateChanged = false;
        bool shouldReport = false;
        
        switch (type) {
            case TYPE_MOM_OFF_MOM:
                // Check if this state should be reported
                if (_controlConfigs[i].reportToHost[physicalState]) {
                    // Reportable state - update and report
                    newLogicalState = physicalState;
                    stateChanged = true;
                    shouldReport = true;
                } else {
                    // Non-reportable state - DON'T update logical state
                    // Logical state "sticks" at last reportable position
                }
                break;
            
            case TYPE_PUSHBUTTON:
                // Physical state directly maps to logical state
                newLogicalState = physicalState;
                stateChanged = true;
                shouldReport = _controlConfigs[i].reportToHost[physicalState];
                break;
            
            case TYPE_TOGGLE:
                // Only change state on press (transition FROM 0 TO non-0)
                if (lastPhysical == 0 && physicalState != 0) {
                    // Toggle between 0 and the pressed state (1 or 2)
                    if (_currentStates[i] == 0) {
                        // Currently off, turn on to whichever state was pressed
                        newLogicalState = physicalState;  // Will be 1 or 2
                    } else {
                        // Currently on (1 or 2), turn off
                        newLogicalState = 0;
                    }
                    
                    stateChanged = true;
                    shouldReport = _controlConfigs[i].reportToHost[newLogicalState];
                }
                break;
                case TYPE_RADIO:
                // Only change state on press (transition FROM 0 TO non-0)
                if (lastPhysical == 0 && physicalState != 0) {
                    // Radio button goes to pressed state (1 or 2)
                    newLogicalState = physicalState;
                    stateChanged = true;
                    shouldReport = _controlConfigs[i].reportToHost[newLogicalState];
                    
                    // Deactivate all other controls in the same group
                    uint8_t group = _controlConfigs[i].group;
                    if (group > 0) {
                        deactivateRadioGroup(group, i);
                    }
                }
                break;
        }
        
        if (stateChanged && newLogicalState != _currentStates[i]) {
            _currentStates[i] = newLogicalState; 
            if (shouldReport && isControlEnabled(i + 1)) {
                uint8_t stateBuffer[1];
                Config::setU8(stateBuffer, 0, newLogicalState);
                notifyStateChange(i + 1, stateBuffer, 1);
            }
        }
    }
}

void BoardSW14::deactivateRadioGroup(uint8_t group, uint8_t excludeIndex) {
    // Set all controls in this group (except excludeIndex) to state 0

    for (int i = 0; i < SW14_NUM_CONTROLS; i++) {
        if (i == excludeIndex) {
            continue;
        }
        
        if (_controlConfigs[i].type == TYPE_RADIO && _controlConfigs[i].group == group) {
            if (_currentStates[i] != 0) {
                _currentStates[i] = 0;
                
                // Report if state 0 is reportable
                if (_controlConfigs[i].reportToHost[0] && isControlEnabled(i + 1)) {
                    uint8_t stateBuffer[1];
                    Config::setU8(stateBuffer, 0, 0);
                    notifyStateChange(i + 1, stateBuffer, 1);
                }
            }
        }
    }
}

void BoardSW14::renderLEDs() {
  unsigned long now = millis();
  
  for (int i = 0; i < SW14_NUM_CONTROLS; i++) {
      uint8_t state = _currentStates[i];
      uint8_t renderState = state;  // Which state's animator to actually render
      
      // Check if we're in a hold period
      if (state == 0 && _heldState[i] != 0) {
          // Currently at state 0, but may be holding previous state
          uint8_t heldState = _heldState[i];
          unsigned long pressDuration = _releaseMs[i] - _pressStartMs[i];
          unsigned long holdMs = _controlConfigs[i].holdMs[heldState];
          
          // Display until max(pressDuration, holdMs) has elapsed since press
          unsigned long targetDuration = (pressDuration > holdMs) ? pressDuration : holdMs;
          unsigned long elapsed = now - _pressStartMs[i];
          
          if (elapsed < targetDuration) {
              // Still within hold period - render the held state
              renderState = heldState;
          } else {
              // Hold period expired - clear held state
              _heldState[i] = 0;
          }
      }
      
      if (_animators[i][renderState]) {
          _animators[i][renderState]->render(now);
      }
  }
}

uint8_t BoardSW14::applyControlConfig(uint8_t controlNum, const uint8_t* rawConfig, size_t len) {
  if (controlNum < 1 || controlNum > SW14_NUM_CONTROLS) {
    EnigmaLogger::error("Invalid control number: %d", controlNum);
    return 0;
  }
  
  if (len < 46) {
    EnigmaLogger::error("Config too short: %d bytes (need 46)", len);
    return 0;
  }
  
  uint8_t controlIdx = controlNum - 1;
  
  // Parse control number (should match, but verify)
  uint8_t configControlNum = Config::getU8(rawConfig, 0);
  if (configControlNum != controlNum) {
    EnigmaLogger::warning("Control number mismatch: expected %d, got %d", 
                         controlNum, configControlNum);
  }
  
  // Parse type
  uint8_t type = Config::getU8(rawConfig, 1);
  if (type > TYPE_RADIO) {
    EnigmaLogger::error("Invalid switch type: %d", type);
    return 0;
  }

  // Parse default state
  uint8_t defaultState = Config::getU8(rawConfig, 2);
  if (defaultState > 2) {
    EnigmaLogger::error("Invalid default state: %d", defaultState);
    return 0;
  }

  // Parse group
  uint8_t group = Config::getU8(rawConfig, 3);
  if (group > SW14_NUM_CONTROLS) {
    EnigmaLogger::error("Invalid group: %d", group);
    return 0;
  }

  // Store config
  _controlConfigs[controlIdx].hasConfig = true;
  _controlConfigs[controlIdx].type = (SwitchType)type;
  _controlConfigs[controlIdx].defaultState = defaultState;
  _controlConfigs[controlIdx].group = group;
  
  // Reset state to center/off (state 0)
  _currentStates[controlIdx] = defaultState;
  _lastPhysicalStates[controlIdx] = 0;
  
  // Parse and apply all 3 state configurations
  for (int state = 0; state < 3; state++) {
    size_t offset = 4 + (state * 14);
    
    // Parse state config
    uint8_t reportToHost = Config::getU8(rawConfig, offset + 0);
    uint8_t r1 = Config::getU8(rawConfig, offset + 1);
    uint8_t g1 = Config::getU8(rawConfig, offset + 2);
    uint8_t b1 = Config::getU8(rawConfig, offset + 3);
    uint8_t r2 = Config::getU8(rawConfig, offset + 4);
    uint8_t g2 = Config::getU8(rawConfig, offset + 5);
    uint8_t b2 = Config::getU8(rawConfig, offset + 6);
    uint8_t mode = Config::getU8(rawConfig, offset + 7);
    uint16_t period = Config::getU16(rawConfig, offset + 8);
    uint16_t duty = Config::getU16(rawConfig, offset + 10);
    uint16_t hold = Config::getU16(rawConfig, offset + 12);
    if (duty > period) {
      duty = period / 2;
    }
    
    // Store reportToHost flag
    _controlConfigs[controlIdx].reportToHost[state] = reportToHost;
    
    // store state's indicator hold time
    _controlConfigs[controlIdx].holdMs[state] = hold;

    // Delete old animator
    if (_animators[controlIdx][state]) {
      delete _animators[controlIdx][state];
      _animators[controlIdx][state] = nullptr;
    }
    
    // Create new animator
    uint8_t ledIndex = _ledIndices[controlIdx];
    uint32_t timebase = Config::getTimebase();
    _animators[controlIdx][state] = createAnimator(
      (AnimationMode)mode,
      ledIndex,
      1,  // 1 LED
      _ledString,
      g1, r1, b1,
      g2, r2, b2,
      period,
      duty,
      timebase
    );
  }
  
  return 46;
}

bool BoardSW14::applyControlState(uint8_t controlNum, const uint8_t* stateData, size_t len) {
  if (controlNum < 1 || controlNum > SW14_NUM_CONTROLS || len < 1) {
    return false;
  }
  
  // Parse state using Config helper
  uint8_t state = Config::getU8(stateData, 0);
  
  if (state > 2) {
    return false;
  }
  
  // Update internal state
  _currentStates[controlNum - 1] = state;
  // If this is a radio button being activated, deactivate others in group
  if (_controlConfigs[controlNum - 1].type == TYPE_RADIO && state != 0) {
    uint8_t group = _controlConfigs[controlNum - 1].group;
    if (group > 0) {
      deactivateRadioGroup(group, controlNum - 1);
    }
  }
  
  // State change triggers LED update in next renderLEDs() call
  return true;
}

bool BoardSW14::applyIndicatorUpdate(uint8_t controlNum, const uint8_t* rawStates, size_t len) {
  if (controlNum < 1 || controlNum > SW14_NUM_CONTROLS) {
    return false;
  }
  
  if (len < 39) {  // 3 states x 13 bytes
    return false;
  }
  
  uint8_t controlIdx = controlNum - 1;
  uint8_t ledIndex = _ledIndices[controlIdx];
  
  // Parse SETINDICATOR format: each state is 11 bytes (no reportToHost)
  for (int state = 0; state < 3; state++) {
    size_t offset = state * 13;
    
    uint8_t r1 = Config::getU8(rawStates, offset + 0);
    uint8_t g1 = Config::getU8(rawStates, offset + 1);
    uint8_t b1 = Config::getU8(rawStates, offset + 2);
    uint8_t r2 = Config::getU8(rawStates, offset + 3);
    uint8_t g2 = Config::getU8(rawStates, offset + 4);
    uint8_t b2 = Config::getU8(rawStates, offset + 5);
    uint8_t mode = Config::getU8(rawStates, offset + 6);
    uint16_t period = Config::getU16(rawStates, offset + 7);
    uint16_t duty = Config::getU16(rawStates, offset + 9);
    uint16_t hold = Config::getU16(rawStates, offset + 11);
    _controlConfigs[controlIdx].holdMs[state] = hold;
    if (duty > period) {
      duty = period;
    }

    // Delete old animator
    if (_animators[controlIdx][state]) {
      delete _animators[controlIdx][state];
    }
    
    uint32_t timebase = Config::getTimebase();
    
    // Host sends RGB, LEDs expect GRB
    _animators[controlIdx][state] = createAnimator(
      (AnimationMode)mode,
      ledIndex,
      1,
      _ledString,
      g1, r1, b1,  // RGB -> GRB
      g2, r2, b2,  // RGB -> GRB
      period,
      duty,
      timebase
    );
  }

  return true;
}

uint8_t BoardSW14::getControlState(uint8_t controlNum, uint8_t* buffer, size_t maxLen) {
  if (controlNum < 1 || controlNum > SW14_NUM_CONTROLS || maxLen < 1) {
    return 0;
  }
  
  // SW14 state is just a single uint8
  uint8_t state = _currentStates[controlNum - 1];
  Config::setU8(buffer, 0, state);
  
  return 1;  // Wrote 1 byte
}

void BoardSW14::updateAnimator(uint8_t controlNum, uint8_t stateNum, const uint8_t* stateConfig) {
    if (controlNum < 1 || controlNum > SW14_NUM_CONTROLS || stateNum > 2) {
        return;
    }
    
    uint8_t controlIdx = controlNum - 1;
    uint8_t ledIndex = _ledIndices[controlIdx];
    
    // Parse state config using Config helpers
    // Format: reportToHost(1) + color1(3) + color2(3) + mode(1) + period(2) + duty(2) + hold(2)
    // uint8_t report = Config::getU8(stateConfig, 0);  // Not used yet
    uint8_t r1 = Config::getU8(stateConfig, 1);
    uint8_t g1 = Config::getU8(stateConfig, 2);
    uint8_t b1 = Config::getU8(stateConfig, 3);
    uint8_t r2 = Config::getU8(stateConfig, 4);
    uint8_t g2 = Config::getU8(stateConfig, 5);
    uint8_t b2 = Config::getU8(stateConfig, 6);
    uint8_t mode = Config::getU8(stateConfig, 7);
    uint16_t period = Config::getU16(stateConfig, 8);
    uint16_t duty = Config::getU16(stateConfig, 10);
    uint16_t hold = Config::getU16(stateConfig, 12);
    _controlConfigs[controlIdx].holdMs[stateNum] = hold;

    // Delete old animator
    if (_animators[controlIdx][stateNum]) {
        delete _animators[controlIdx][stateNum];
    }
    
    // Create new animator
    uint32_t timebase = Config::getTimebase();
    _animators[controlIdx][stateNum] = createAnimator(
        (AnimationMode)mode,
        ledIndex,
        1,
        _ledString,
        r1, g1, b1,
        r2, g2, b2,
        period,
        duty,
        timebase
    );
}