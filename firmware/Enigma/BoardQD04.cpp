// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

/*
 * BoardQD04.cpp - Implementation of QD04 board
 */

#include "BoardQD04.h"
#include "Config.h"
#include "LEDManager.h"
#include "EnigmaLogger.h"
#include <Arduino.h>

#include "driver/gpio.h"
#include "soc/gpio_reg.h"
#include "esp_attr.h"
#include "esp_intr_alloc.h"

// Static pin assignments
const uint8_t BoardQD04::ENC_A[]   = { 8, 15, 10, 12};
const uint8_t BoardQD04::ENC_B[]   = { 3, 16,  1, 13};
const uint8_t BoardQD04::BTN[]     = {17,  7,  9, 11};
const uint8_t BoardQD04::LED_PIN[] = {6,  38, 21, 48};

// Quadrature decoder lookup table (kept for compatibility)
const int8_t BoardQD04::ENCODER_TABLE[16] = {
   0, -1,  1,  0,
   1,  0,  0, -1,
  -1,  0,  0,  1,
   0,  1, -1,  0
};

namespace {

static uint32_t kENCODER_DEGLITCH_US = 20;    // very small A-edge reject
static uint32_t kBUTTON_DEBOUNCE_US  = 2500;  // ~2.5 ms debounce
// One context per control for encoder and button ISRs
static BoardQD04::ISRContext s_ctxA[QD04_NUM_CONTROLS];   // used for ENC_A and ENC_B
static BoardQD04::ISRContext s_ctxBtn[QD04_NUM_CONTROLS]; // used for BTN

static bool     s_isrInstalled       = false;

static inline uint8_t fast_read(uint8_t pin) {
  return (uint8_t)gpio_get_level((gpio_num_t)pin);
}

// IRAM-safe GPIO reads on ESP32-S3
// IRAM-safe GPIO read (ESP32-S3)
static inline __attribute__((always_inline)) uint8_t fast_read_iram(uint8_t pin) {
  if (pin < 32) return (REG_READ(GPIO_IN_REG)  >> pin) & 1U;
  return (REG_READ(GPIO_IN1_REG) >> (pin - 32)) & 1U;
}

// Clear any latched GPIO interrupt for a pin before enabling it
static inline __attribute__((always_inline)) void clear_gpio_int(uint8_t pin) {
  if (pin < 32) REG_WRITE(GPIO_STATUS_W1TC_REG,  (1UL << pin));
  else          REG_WRITE(GPIO_STATUS1_W1TC_REG, (1UL << (pin - 32)));
}

// Ticks (ISR-safe) for deglitch/debounce
static const TickType_t kENCODER_DEGLITCH_TICKS = pdMS_TO_TICKS(1);  // ~1 ms
static const TickType_t kBUTTON_DEBOUNCE_TICKS  = pdMS_TO_TICKS(3);  // ~3 ms

// How many quadrature edges per detent for your encoders
static const int kEDGES_PER_DETENT = 2;  // typical: 4 transitions per click
} // namespace

// ============================================================================
// BoardQD04 Implementation
// ============================================================================

BoardQD04::BoardQD04() {
  strcpy(_boardType, "QD04");
  _boardTypeNum = VARIANT_QD04;
  
  // Initialize controls with "unconfigured" defaults
  for (uint8_t i = 0; i < QD04_NUM_CONTROLS; i++) {
    _controls[i].numLEDs = 23;  // Default 23 LEDs
    _controls[i].buttonMode = 0;
    _controls[i].buttonReports = 1;
    _controls[i].modeFlags = 0;
    _controls[i].mode = DIAL_MODE_GRADIENT;
    _controls[i].position = 0;
    _controls[i].buttonState = 0;
    _controls[i].lastReportedPos = 0;
    _controls[i].lastReportedBtn = 0;
    _controls[i].ledArray = nullptr;
    _controls[i].ledStartIndex = 0;
    _controls[i].animator = nullptr;
    
    _encoderRawPos[i].store(0);
    _buttonPhysicalState[i].store(0);
    _encoderChanged[i].store(false);
    _buttonChanged[i].store(false);
    
    _lastEncoderState[i] = 0;
    _lastEncoderTime[i] = 0;
    _lastButtonTime[i] = 0;
    _lastButtonReading[i] = HIGH;
    _encQuarterAccum[i] = 0;
  }

  EnigmaLogger::info("QD04 constructor complete");
}

BoardQD04::~BoardQD04() {
  for (uint8_t i = 0; i < QD04_NUM_CONTROLS; i++) {
    if (_controls[i].animator) {
      delete _controls[i].animator;
      _controls[i].animator = nullptr;
    }
  }
}

void BoardQD04::init() {
  EnigmaLogger::info("Initializing QD04 board");
  
  LEDManager* ledMgr = LEDManager::getInstance();
  ledMgr->begin();
  
  // Allocate LED strings for each control
  for (uint8_t i = 0; i < QD04_NUM_CONTROLS; i++) {
    _controls[i].ledArray = ledMgr->addLEDString(LED_PIN[i], MAX_LEDS_PER_DIAL);
    _controls[i].ledStartIndex = 1;
    
    uint8_t configBuffer[64];  // Large enough for any config
  
    if (Config::loadControlConfig(i+1, configBuffer, sizeof(configBuffer))) {
      // Apply the loaded config
      uint8_t bytesUsed = applyControlConfig(i+1, configBuffer, sizeof(configBuffer));
      
      if (bytesUsed > 0) {
        EnigmaLogger::debug("Loaded config for control %d", i+1);
      } else {
        EnigmaLogger::warning("Failed to apply stored config for control %d", i+1);
        // Create "unconfigured" default: 10-30% gradient, screen blend, blink 500ms
        _controls[i].animator = new DialGradientAnimator(
          _controls[i].ledStartIndex,
          _controls[i].numLEDs,
          _controls[i].ledArray,
          25, 0, 0,      // Start: 10% red (dim red)
          75, 0, 0,     // End: 30% red (mid red)
          500, 0,        // 500ms period
         Config::getTimebase()
        );
        ((DialAnimator*)_controls[i].animator)->setActiveBlendMode(BLEND_SCREEN);
        ((DialAnimator*)_controls[i].animator)->setOverlayColor(255, 128, 0, 0);
        ((DialAnimator*)_controls[i].animator)->setAnimationMode(ANIM_MODE_BLINK);
        ((DialAnimator*)_controls[i].animator)->setPosition(0);
      }
    }
  }

  ledMgr->finalize();
 
  // Setup encoder hardware and interrupts
 // setupEncoderHardware();
  xTaskCreatePinnedToCore(
    [](void* param) {
      BoardQD04* board = (BoardQD04*)param;
      board->setupEncoderHardware();
      vTaskDelete(NULL);  // Delete this init task when done
    },
    "EncoderInit",
    4096,
    this,  // Pass board pointer
    1,
    NULL,
    0        // Core 0
  );
  
  delay(100);  // Give it time to complete
  
  EnigmaLogger::info("QD04 board initialized");
}

uint8_t BoardQD04::getControlCount() {
  return QD04_NUM_CONTROLS;
}

void BoardQD04::setupEncoderHardware() {
  EnigmaLogger::info("QD04: Setting up encoder hardware on Core %d", xPortGetCoreID());

  if (!s_isrInstalled) {
    delay(50);
//    gpio_install_isr_service(ESP_INTR_FLAG_IRAM);
    gpio_install_isr_service(ESP_INTR_FLAG_IRAM );
    delay(50);
    s_isrInstalled = true;
  }

  // 1) Configure as inputs with INTERNAL PULLUPS and IRQs DISABLED
  for (uint8_t i = 0; i < QD04_NUM_CONTROLS; ++i) {
    gpio_config_t io = {};
    io.pin_bit_mask  = (1ULL << ENC_A[i]) | (1ULL << ENC_B[i]) | (1ULL << BTN[i]);
    io.mode          = GPIO_MODE_INPUT;
    io.intr_type     = GPIO_INTR_DISABLE;
    io.pull_up_en    = GPIO_PULLUP_ENABLE;   // avoids floating when unplugged
    io.pull_down_en  = GPIO_PULLDOWN_DISABLE;
    gpio_config(&io);
  }

  // 2) Seed state BEFORE enabling IRQs
  TickType_t t0 = xTaskGetTickCount();
  for (uint8_t i = 0; i < QD04_NUM_CONTROLS; ++i) {
    uint8_t a = fast_read_iram(ENC_A[i]);
    uint8_t b = fast_read_iram(ENC_B[i]);
    _lastEncoderState[i]   = (uint8_t)((a << 1) | b);
    _lastEncoderTime[i]    = (uint32_t)t0;

    _lastButtonReading[i]  = fast_read_iram(BTN[i]);
    _lastButtonTime[i]     = (uint32_t)t0;

    _encQuarterAccum[i]    = 0;

    _encoderRawPos[i].store(0, std::memory_order_relaxed);
    _encoderChanged[i].store(false, std::memory_order_relaxed);

    _buttonPhysicalState[i].store((_lastButtonReading[i] == LOW) ? 1 : 0, std::memory_order_relaxed);
    _buttonChanged[i].store(false, std::memory_order_relaxed);
  }

  // 3) Register handlers (same context for A and B)
  for (uint8_t i = 0; i < QD04_NUM_CONTROLS; ++i) {
    s_ctxA[i]   = { this, i };
    s_ctxBtn[i] = { this, i };
    // Same encoder ISR for A and B pins:
    gpio_isr_handler_add((gpio_num_t)ENC_A[i], &BoardQD04::EncoderAB_ISR, (void*)&s_ctxA[i]);
    gpio_isr_handler_add((gpio_num_t)ENC_B[i], &BoardQD04::EncoderAB_ISR, (void*)&s_ctxA[i]);
    // Button ISR:
    gpio_isr_handler_add((gpio_num_t)BTN[i],   &BoardQD04::Button_ISR,   (void*)&s_ctxBtn[i]);
  }

  // 4) Clear any latched interrupts before enabling
  for (uint8_t i = 0; i < QD04_NUM_CONTROLS; ++i) {
    clear_gpio_int(ENC_A[i]);
    clear_gpio_int(ENC_B[i]);
    clear_gpio_int(BTN[i]);
  }

  // 5) Arm types and enable (ANYEDGE for A & B; ANYEDGE for BTN)
  for (uint8_t i = 0; i < QD04_NUM_CONTROLS; ++i) {
    gpio_set_intr_type((gpio_num_t)ENC_A[i], GPIO_INTR_ANYEDGE);
    gpio_set_intr_type((gpio_num_t)ENC_B[i], GPIO_INTR_ANYEDGE);
    gpio_set_intr_type((gpio_num_t)BTN[i],   GPIO_INTR_ANYEDGE);

    gpio_intr_enable((gpio_num_t)ENC_A[i]);
    gpio_intr_enable((gpio_num_t)ENC_B[i]);
    gpio_intr_enable((gpio_num_t)BTN[i]);
  }

  EnigmaLogger::info("QD04: ISRs armed on A+B (ANYEDGE) and BTN");
}

// ===== Static member ISRs (detent-only) =====

void IRAM_ATTR BoardQD04::EncoderAB_ISR(void* arg) {
  auto* c = (ISRContext*)arg;
  if (!c || !c->self || c->idx >= QD04_NUM_CONTROLS) return;
  BoardQD04* self = c->self;
  const uint8_t i = c->idx;

  // Skip if control is disabled (bit i in mask, 0-based)
  if (!(self->_enableMask & (1U << i))) return;

  // Basic deglitch using ticks (cheap and ISR-safe)
  TickType_t now = xTaskGetTickCountFromISR();
  if ((now - (TickType_t)self->_lastEncoderTime[i]) < kENCODER_DEGLITCH_TICKS) return;
  self->_lastEncoderTime[i] = (uint32_t)now;

  // Read current 2-bit state atomically
  uint8_t a = fast_read_iram(self->ENC_A[i]);
  uint8_t b = fast_read_iram(self->ENC_B[i]);
  uint8_t newState = (uint8_t)((a << 1) | b);

  uint8_t last = self->_lastEncoderState[i];
  if (newState == last) return;  // ignore bounces that don't change state
  self->_lastEncoderState[i] = newState;

  // Quadrature decode: -1/0/+1 per transition
  uint8_t idx4 = (uint8_t)((last << 2) | newState);
  int8_t delta = BoardQD04::ENCODER_TABLE[idx4];
  if (delta == 0) return;  // illegal or no-op transition

  // Check for A/B reversal flag and negate delta if set
  if (self->_controls[i].modeFlags & MODE_FLAG_AB_REVERSED) {
    delta = -delta;
  }

  // Accumulate quarter steps; emit only on full detent
  int8_t acc = self->_encQuarterAccum[i] + delta;

  // Check if we're in incremental mode
  bool incrementalMode = (self->_controls[i].modeFlags & MODE_FLAG_INCREMENTAL) != 0;

  // Normalize overshoot (handle +/- 4 cleanly)
  if (acc >= kEDGES_PER_DETENT) {
    // +1 detent
    int32_t v = self->_encoderRawPos[i].load(std::memory_order_relaxed);
    if (incrementalMode) {
      // Incremental mode: accumulate delta (no clamping)
      ++v;
    } else {
      // Absolute mode: clamp to 0..numLEDs
      const uint16_t vmax = self->_controls[i].numLEDs;
      if (v < (int32_t)vmax) ++v;
    }
    self->_encoderRawPos[i].store(v, std::memory_order_relaxed);
    self->_encoderChanged[i].store(true, std::memory_order_relaxed);
    acc = 0;  // reset after committing detent
  } else if (acc <= -kEDGES_PER_DETENT) {
    // -1 detent
    int32_t v = self->_encoderRawPos[i].load(std::memory_order_relaxed);
    if (incrementalMode) {
      // Incremental mode: accumulate delta (no clamping)
      --v;
    } else {
      // Absolute mode: clamp to 0..numLEDs
      if (v > 0) --v;
    }
    self->_encoderRawPos[i].store(v, std::memory_order_relaxed);
    self->_encoderChanged[i].store(true, std::memory_order_relaxed);
    acc = 0;
  }

  self->_encQuarterAccum[i] = acc;
}

void IRAM_ATTR BoardQD04::Button_ISR(void* arg) {
  auto* c = (ISRContext*)arg;
  if (!c || !c->self || c->idx >= QD04_NUM_CONTROLS) return;
  BoardQD04* self = c->self;
  const uint8_t i = c->idx;

  // Skip if control is disabled (bit i in mask, 0-based)
  if (!(self->_enableMask & (1U << i))) return;

  TickType_t now = xTaskGetTickCountFromISR();
  if ((now - (TickType_t)self->_lastButtonTime[i]) < kBUTTON_DEBOUNCE_TICKS) return;
  self->_lastButtonTime[i] = (uint32_t)now;

  uint8_t raw  = fast_read_iram(self->BTN[i]);
  uint8_t phys = (raw == LOW) ? 1 : 0;
  self->_lastButtonReading[i] = raw;

  self->_buttonPhysicalState[i].store(phys, std::memory_order_relaxed);
  self->_buttonChanged[i].store(true, std::memory_order_relaxed);
}

// ============================================================================
// Protocol Handlers
// ============================================================================

uint8_t BoardQD04::applyControlConfig(uint8_t controlNum, const uint8_t* rawConfig, size_t len) {
  if (controlNum < 1 || controlNum > QD04_NUM_CONTROLS) {
    EnigmaLogger::warning("Invalid control number: %d", controlNum);
    return 0;
  }
  
  uint8_t idx = controlNum - 1;  // Convert to 0-based
  
  // Parse config header (starts after controlNum in HID packet)
  if (len < 15) {
    EnigmaLogger::warning("Config too short: %d bytes", (int)len);
    return 0;
  }
  size_t offset = 1;
  
  // Parse base config
  uint8_t numLEDs = Config::getU8(rawConfig, offset++);
  uint8_t buttonMode = Config::getU8(rawConfig, offset++);
  uint8_t buttonReports = Config::getU8(rawConfig, offset++);
  uint8_t modeFlags = Config::getU8(rawConfig, offset++);
  uint8_t activeRender = Config::getU8(rawConfig, offset++);

  // Extract individual mode flags
  uint8_t backgroundMode = (modeFlags & MODE_FLAG_BACKGROUND_RANGED) ? DIAL_MODE_RANGED : DIAL_MODE_GRADIENT;
  bool tickMode = (modeFlags & MODE_FLAG_ACTIVE_TICK) != 0;
  bool abReversed = (modeFlags & MODE_FLAG_AB_REVERSED) != 0;
  bool incrementalMode = (modeFlags & MODE_FLAG_INCREMENTAL) != 0;

  // Active overlay color (ARGB)
  uint8_t overlayA = Config::getU8(rawConfig, offset++);
  uint8_t overlayR = Config::getU8(rawConfig, offset++);
  uint8_t overlayG = Config::getU8(rawConfig, offset++);
  uint8_t overlayB = Config::getU8(rawConfig, offset++);

  // Animation config
  uint8_t animMode = Config::getU8(rawConfig, offset++);
  uint16_t animPeriod = Config::getU16(rawConfig, offset); offset += 2;
  uint16_t animDuty = Config::getU16(rawConfig, offset); offset += 2;
  if (animDuty > animPeriod) {
     animDuty = animPeriod;
  }
     
 //EnigmaLogger::debug("leds %d, bm %d, br %d, mo %d, ar %d, ov=%02x%02x%02x%02x, am %d, ap %d, aM %d", numLEDs,buttonMode,buttonReports,mode, activeRender, overlayA, overlayR, overlayG, overlayB, animMode, animPeriod, animDuty); 
  
  // Validate
  if (numLEDs == 0 || numLEDs > MAX_LEDS_PER_DIAL) {
    EnigmaLogger::warning("Invalid numLEDs: %d", numLEDs);
    return 0;
  }
  if (activeRender > 5) {
    EnigmaLogger::warning("Invalid active render mode: %d", activeRender);
    return 0;
  }
  
  // Update control state
  QD04ControlState& ctrl = _controls[idx];
  ctrl.numLEDs = numLEDs;
  ctrl.buttonMode = buttonMode;
  ctrl.buttonReports = buttonReports;
  ctrl.modeFlags = modeFlags;
  ctrl.mode = (DialMode)backgroundMode;

  // Delete old animator
  if (ctrl.animator) {
    delete ctrl.animator;
    ctrl.animator = nullptr;
  }

  // In incremental mode, skip animator creation (LEDs not supported)
  if (incrementalMode) {
    // Still need to parse mode-specific data to return correct offset
    if (backgroundMode == DIAL_MODE_GRADIENT) {
      if (len < offset + 6) {
        EnigmaLogger::warning("Gradient config too short");
        return 0;
      }
      offset += 6;  // Skip gradient colors
    } else if (backgroundMode == DIAL_MODE_RANGED) {
      if (len < offset + 1) {
        EnigmaLogger::warning("Ranged config too short");
        return 0;
      }
      uint8_t numZones = Config::getU8(rawConfig, offset++);
      if (numZones == 0 || numZones > 12) {
        EnigmaLogger::warning("Invalid numZones: %d", numZones);
        return 0;
      }
      if (len < offset + (numZones * 4)) {
        EnigmaLogger::warning("Ranged zone data too short");
        return 0;
      }
      offset += numZones * 4;  // Skip zone data
    }

//    EnigmaLogger::info("Control %d configured: incremental mode (no LEDs)", controlNum);
    return (uint8_t)offset;
  }

  // Parse mode-specific data and create animator
  if (backgroundMode == DIAL_MODE_GRADIENT) {
    if (len < offset + 6) {
      EnigmaLogger::warning("Gradient config too short");
      return 0;
    }
    
    uint8_t r1 = Config::getU8(rawConfig, offset++);
    uint8_t g1 = Config::getU8(rawConfig, offset++);
    uint8_t b1 = Config::getU8(rawConfig, offset++);
    uint8_t r2 = Config::getU8(rawConfig, offset++);
    uint8_t g2 = Config::getU8(rawConfig, offset++);
    uint8_t b2 = Config::getU8(rawConfig, offset++);
//EnigmaLogger::debug("r1=%02x%02x%02x, r2=%02x%02x%02x", r1,g1,b1,r2,g2,b2); 
    
    // Create gradient animator
    DialGradientAnimator* gradAnim = new DialGradientAnimator(
      ctrl.ledStartIndex,
      ctrl.numLEDs,
      ctrl.ledArray,
      r1, g1, b1,
      r2, g2, b2,
      animPeriod,
      animDuty,
      Config::getTimebase()
    );
    
    gradAnim->setActiveBlendMode((ActiveBlendMode)activeRender);
    gradAnim->setOverlayColor(overlayA, overlayR, overlayG, overlayB);
    gradAnim->setAnimationMode((AnimationMode)animMode);
    gradAnim->setTickMode(tickMode);
    gradAnim->setPosition(ctrl.position);

    ctrl.animator = gradAnim;

  } else if (backgroundMode == DIAL_MODE_RANGED) {
    if (len < offset + 1) {
      EnigmaLogger::warning("Ranged config too short");
      return 0;
    }
    
    uint8_t numZones = Config::getU8(rawConfig, offset++);
//EnigmaLogger::debug("nz=%d", numZones);     
    if (numZones == 0 || numZones > 12) {
      EnigmaLogger::warning("Invalid numZones: %d", numZones);
      return 0;
    }
    
    if (len < offset + (numZones * 4)) {
      EnigmaLogger::warning("Ranged zone data too short");
      return 0;
    }
    
    // Parse zones
    uint8_t thresholds[12];
    CRGB colors[12];
    
    for (uint8_t z = 0; z < numZones; z++) {
      thresholds[z] = Config::getU8(rawConfig, offset++);
      colors[z].r = Config::getU8(rawConfig, offset++);
      colors[z].g = Config::getU8(rawConfig, offset++);
      colors[z].b = Config::getU8(rawConfig, offset++);
//EnigmaLogger::debug("z @%d = %02x%02x%02x", thresholds[z], colors[z].r, colors[z].g, colors[z].b);     

    }
    
    // Create ranged animator
    DialRangedAnimator* rangedAnim = new DialRangedAnimator(
      ctrl.ledStartIndex,
      ctrl.numLEDs,
      ctrl.ledArray,
      animPeriod,
      animDuty,
      Config::getTimebase()
    );
    
    rangedAnim->setZones(numZones, thresholds, colors);
    rangedAnim->setActiveBlendMode((ActiveBlendMode)activeRender);
    rangedAnim->setOverlayColor(overlayA, overlayR, overlayG, overlayB);
    rangedAnim->setAnimationMode((AnimationMode)animMode);
    rangedAnim->setTickMode(tickMode);
    rangedAnim->setPosition(ctrl.position);

    ctrl.animator = rangedAnim;
  }

//  EnigmaLogger::info("Control %d configured: %d LEDs, mode %d",
//                     controlNum, numLEDs, backgroundMode);

  return (uint8_t)offset;  // Return bytes consumed
}

bool BoardQD04::applyControlState(uint8_t controlNum, const uint8_t* stateData, size_t len) {
  if (controlNum < 1 || controlNum > QD04_NUM_CONTROLS) {
    return false;
  }
  if (len < 2) {
    return false;
  }
  
  uint8_t idx = controlNum - 1;
  QD04ControlState& ctrl = _controls[idx];
  
  uint8_t position = stateData[0];
  uint8_t button = stateData[1];
  
  // Validate position
  if (position > ctrl.numLEDs) {
    return false;
  }
  
  // Update state
  ctrl.position = position;
  ctrl.buttonState = button ? 1 : 0;
  
  // Update raw position for encoder (keeps ISR & UI in sync)
  _encoderRawPos[idx].store(position, std::memory_order_relaxed);
  _encoderChanged[idx].store(true, std::memory_order_relaxed);
  
  // Update animator
  if (ctrl.animator) {
    ((DialAnimator*)ctrl.animator)->setPosition(ctrl.position);
  }
  
  return true;
}

bool BoardQD04::applyIndicatorUpdate(uint8_t controlNum, const uint8_t* rawStates, size_t len) {
  if (controlNum < 1 || controlNum > QD04_NUM_CONTROLS) {
    return false;
  }
  
  uint8_t idx = controlNum - 1;
  QD04ControlState& ctrl = _controls[idx];
  
  // Parse indicator data (same structure as SETCONFIG but without hardware config)
  if (len < 11) {
    return false;
  }
  
  size_t offset = 0;

  uint8_t modeFlags = Config::getU8(rawStates, offset++);
  uint8_t activeRender = Config::getU8(rawStates, offset++);

  // Extract mode flags (only background mode and tick mode are relevant for indicator update)
  uint8_t backgroundMode = (modeFlags & MODE_FLAG_BACKGROUND_RANGED) ? DIAL_MODE_RANGED : DIAL_MODE_GRADIENT;
  bool tickMode = (modeFlags & MODE_FLAG_ACTIVE_TICK) != 0;
  // Note: A/B reversal and incremental mode are hardware config, not changed via indicator update

  uint8_t overlayA = Config::getU8(rawStates, offset++);
  uint8_t overlayR = Config::getU8(rawStates, offset++);
  uint8_t overlayG = Config::getU8(rawStates, offset++);
  uint8_t overlayB = Config::getU8(rawStates, offset++);

  uint8_t animMode = Config::getU8(rawStates, offset++);
  uint16_t animPeriod = Config::getU16(rawStates, offset); offset += 2;
  uint16_t animDuty = Config::getU16(rawStates, offset); offset += 2;
  if( animDuty > animPeriod ) {
    animDuty = animPeriod;
  }

  // If in incremental mode, no animator updates are meaningful
  if (ctrl.modeFlags & MODE_FLAG_INCREMENTAL) {
    return true;
  }

  // If background mode changed, need to recreate animator
  if ((DialMode)backgroundMode != ctrl.mode) {
    ctrl.mode = (DialMode)backgroundMode;
    
    if (ctrl.animator) {
      delete ctrl.animator;
      ctrl.animator = nullptr;
    }

    if (backgroundMode == DIAL_MODE_GRADIENT) {
      if (len < offset + 6) return false;

      uint8_t r1 = Config::getU8(rawStates, offset++);
      uint8_t g1 = Config::getU8(rawStates, offset++);
      uint8_t b1 = Config::getU8(rawStates, offset++);
      uint8_t r2 = Config::getU8(rawStates, offset++);
      uint8_t g2 = Config::getU8(rawStates, offset++);
      uint8_t b2 = Config::getU8(rawStates, offset++);

      DialGradientAnimator* gradAnim = new DialGradientAnimator(
        ctrl.ledStartIndex,
        ctrl.numLEDs,
        ctrl.ledArray,
        r1, g1, b1,
        r2, g2, b2,
        animPeriod,
        animDuty,
        Config::getTimebase()
      );
      gradAnim->setTickMode(tickMode);
      ctrl.animator = gradAnim;

    } else if (backgroundMode == DIAL_MODE_RANGED) {
      if (len < offset + 1) return false;

      uint8_t numZones = Config::getU8(rawStates, offset++);
      if (numZones == 0 || numZones > 12 || len < offset + (numZones * 4)) {
        return false;
      }

      uint8_t thresholds[12];
      CRGB colors[12];

      for (uint8_t z = 0; z < numZones; z++) {
        thresholds[z] = Config::getU8(rawStates, offset++);
        colors[z].r = Config::getU8(rawStates, offset++);
        colors[z].g = Config::getU8(rawStates, offset++);
        colors[z].b = Config::getU8(rawStates, offset++);
      }

      DialRangedAnimator* rangedAnim = new DialRangedAnimator(
        ctrl.ledStartIndex,
        ctrl.numLEDs,
        ctrl.ledArray,
        animPeriod,
        animDuty,
        Config::getTimebase()
      );

      rangedAnim->setZones(numZones, thresholds, colors);
      rangedAnim->setTickMode(tickMode);
      ctrl.animator = rangedAnim;
    }
  } else {
    // Same background mode, just update colors/params
    if (backgroundMode == DIAL_MODE_GRADIENT && ctrl.animator) {
      if (len < offset + 6) return false;

      uint8_t r1 = Config::getU8(rawStates, offset++);
      uint8_t g1 = Config::getU8(rawStates, offset++);
      uint8_t b1 = Config::getU8(rawStates, offset++);
      uint8_t r2 = Config::getU8(rawStates, offset++);
      uint8_t g2 = Config::getU8(rawStates, offset++);
      uint8_t b2 = Config::getU8(rawStates, offset++);

      ((DialGradientAnimator*)ctrl.animator)->setGradientColors(r1, g1, b1, r2, g2, b2);
      ((DialAnimator*)ctrl.animator)->setTickMode(tickMode);

    } else if (backgroundMode == DIAL_MODE_RANGED && ctrl.animator) {
      if (len < offset + 1) return false;

      uint8_t numZones = Config::getU8(rawStates, offset++);
      if (numZones == 0 || numZones > 12 || len < offset + (numZones * 4)) {
        return false;
      }

      uint8_t thresholds[12];
      CRGB colors[12];

      for (uint8_t z = 0; z < numZones; z++) {
        thresholds[z] = Config::getU8(rawStates, offset++);
        colors[z].r = Config::getU8(rawStates, offset++);
        colors[z].g = Config::getU8(rawStates, offset++);
        colors[z].b = Config::getU8(rawStates, offset++);
      }

      ((DialRangedAnimator*)ctrl.animator)->setZones(numZones, thresholds, colors);
      ((DialAnimator*)ctrl.animator)->setTickMode(tickMode);
    }
  }

  // Update common animator properties
  if (ctrl.animator) {
    DialAnimator* dialAnim = (DialAnimator*)ctrl.animator;
    dialAnim->setActiveBlendMode((ActiveBlendMode)activeRender);
    dialAnim->setOverlayColor(overlayA, overlayR, overlayG, overlayB);
    dialAnim->setAnimationMode((AnimationMode)animMode);
    dialAnim->setPeriod(animPeriod);
    dialAnim->setDutyCycle(animDuty);
    dialAnim->setPosition(ctrl.position);
  }
  
  return true;
}

uint8_t BoardQD04::getControlState(uint8_t controlNum, uint8_t* buffer, size_t maxLen) {
  if (controlNum < 1 || controlNum > QD04_NUM_CONTROLS || maxLen < 2) {
    return 0;
  }

  uint8_t idx = controlNum - 1;
  QD04ControlState& ctrl = _controls[idx];

  // In incremental mode, position is always 0 (no position tracking)
  if (ctrl.modeFlags & MODE_FLAG_INCREMENTAL) {
    buffer[0] = 0;
  } else {
    buffer[0] = ctrl.position;
  }
  buffer[1] = ctrl.buttonState;

  return 2;
}

// ============================================================================
// Update & helpers
// ============================================================================

void BoardQD04::update() {
  // Check for encoder/button changes and report to host
  for (uint8_t i = 0; i < QD04_NUM_CONTROLS; i++) {
    QD04ControlState& ctrl = _controls[i];
    bool incrementalMode = (ctrl.modeFlags & MODE_FLAG_INCREMENTAL) != 0;

    // Skip input processing for disabled controls (drain flags only)
    if (!isControlEnabled(i + 1)) {
      _buttonChanged[i].store(false, std::memory_order_relaxed);
      _encoderChanged[i].store(false, std::memory_order_relaxed);
      if (incrementalMode) _encoderRawPos[i].store(0, std::memory_order_relaxed);
    } else {
      // Check button changes first
      bool buttonChanged = false;
      if (_buttonChanged[i].exchange(false)) {
        updateButtonState(i);
        buttonChanged = true;
      }

      if (incrementalMode) {
        // INCREMENTAL MODE: Send one report per detent
        // Atomically swap the accumulated delta to 0
        int32_t delta = _encoderRawPos[i].exchange(0);
        _encoderChanged[i].store(false, std::memory_order_relaxed);

        if (delta != 0) {
          // Send one report per unit of delta
          int8_t direction = (delta > 0) ? 1 : -1;
          int32_t count = (delta > 0) ? delta : -delta;

          for (int32_t d = 0; d < count; d++) {
            uint8_t stateData[2];
            stateData[0] = (uint8_t)(int8_t)direction;  // Cast to signed then to byte
            stateData[1] = ctrl.buttonState;
            notifyStateChange(i + 1, stateData, 2);
          }
          ctrl.lastReportedBtn = ctrl.buttonState;
        } else if (buttonChanged && ctrl.buttonReports) {
          // Button changed but no rotation - send report with delta=0
          if (ctrl.buttonState != ctrl.lastReportedBtn) {
            uint8_t stateData[2];
            stateData[0] = 0;  // No rotation
            stateData[1] = ctrl.buttonState;
            notifyStateChange(i + 1, stateData, 2);
            ctrl.lastReportedBtn = ctrl.buttonState;
          }
        }

      } else {
        // ABSOLUTE MODE: Original behavior
        bool encoderChanged = false;
        if (_encoderChanged[i].exchange(false)) {
          int32_t rawPos = _encoderRawPos[i].load();
          updateEncoderPosition(i, rawPos);
          encoderChanged = true;
        }

        // Report state changes to host
        if (encoderChanged || buttonChanged) {
          // Only report if state actually changed from last report
          if (ctrl.position != ctrl.lastReportedPos ||
              (ctrl.buttonReports && ctrl.buttonState != ctrl.lastReportedBtn)) {

            uint8_t stateData[2];
            stateData[0] = ctrl.position;
            stateData[1] = ctrl.buttonState;
            notifyStateChange(i + 1, stateData, 2);  // controlNum is 1-based

            ctrl.lastReportedPos = ctrl.position;
            ctrl.lastReportedBtn = ctrl.buttonState;
          }
        }
      }
    }

    // Render animator (only for absolute mode, incremental has no LEDs)
    if (!incrementalMode && ctrl.animator) {
      ctrl.animator->render(millis());
    }
  }

  // Update LEDs
  LEDManager::getInstance()->update();
}

int8_t BoardQD04::decodeQuadrature(uint8_t lastState, uint8_t newState) {
  uint8_t index = (lastState << 2) | newState;
  return ENCODER_TABLE[index];
}

void BoardQD04::updateEncoderPosition(uint8_t controlNum, int32_t rawPos) {
  QD04ControlState& ctrl = _controls[controlNum];
  
  // Clamp raw position to valid range
  if (rawPos < 0) rawPos = 0;
  if (rawPos > ctrl.numLEDs) rawPos = ctrl.numLEDs;
  
  uint8_t newPosition = (uint8_t)rawPos;
  
  if (newPosition != ctrl.position) {
    ctrl.position = newPosition;
    
    // Update animator position
    if (ctrl.animator) {
      ((DialAnimator*)ctrl.animator)->setPosition(ctrl.position);
    }
  }
}

void BoardQD04::updateButtonState(uint8_t controlNum) {
  QD04ControlState& ctrl = _controls[controlNum];
  uint8_t physicalState = _buttonPhysicalState[controlNum].load();
  
  if (ctrl.buttonMode == 0) {
    // Momentary mode - report physical state directly
    ctrl.buttonState = physicalState;
  } else {
    // Toggle mode - toggle on press (rising edge of physical state)
    static uint8_t lastPhysical[QD04_NUM_CONTROLS] = {0};
    
    if (physicalState == 1 && lastPhysical[controlNum] == 0) {
      // Button just pressed - toggle state
      ctrl.buttonState = ctrl.buttonState ? 0 : 1;
    }
    lastPhysical[controlNum] = physicalState;
  }
}
