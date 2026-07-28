// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

/*
 * BoardAN08.cpp - 8-channel 10-bit ADC board (MCP3008T-I/SL)
 */

#include "BoardAN08.h"
#include <math.h>

static const SPISettings kMCP3008_SPI(2000000, MSBFIRST, SPI_MODE0);

// PCB wiring runs MCP3008 hardware channels in reverse order relative to logical
// control_num: control_num 1 reads HW CH7, control_num 8 reads HW CH0.
static inline uint8_t logicalToHwChannel(uint8_t logical) {
    return (AN08_NUM_CHANNELS - 1) - logical;
}

// ============================================================================
// Constructor
// ============================================================================

BoardAN08::BoardAN08() : Board() {
    strcpy(_boardType, "AN08");
    _boardTypeNum = VARIANT_AN08;

    memset(_configs, 0, sizeof(_configs));
    memset(_lastReported, 0xFF, sizeof(_lastReported));  // Force report on first reading
    memset(_hasConfig, 0, sizeof(_hasConfig));

    // Set safe defaults for all channels (pass-through, disabled until configured)
    for (uint8_t i = 0; i < AN08_NUM_CHANNELS; i++) {
        _configs[i].sensorMin  = 0;
        _configs[i].sensorMax  = 1023;
        _configs[i].deadband   = 2;
        _configs[i].gammaX1000 = 1000;
        _configs[i].invert     = 0;
        _configs[i].enabled    = 0;  // Disabled until SETCONFIG received
    }

    _board = this;
}

// ============================================================================
// init() - called once at startup
// ============================================================================

void BoardAN08::init() {
    EnigmaLogger::info("BoardAN08::init()");

    // SPI bus init (SCK, MISO, MOSI, SS=-1 for manual CS)
    SPI.begin(AN08_PIN_SCLK, AN08_PIN_MISO, AN08_PIN_MOSI, -1);

    // CS pin - idle high
    pinMode(AN08_PIN_CS, OUTPUT);
    digitalWrite(AN08_PIN_CS, HIGH);

    // Load stored configs from NVS
    for (uint8_t i = 0; i < AN08_NUM_CHANNELS; i++) {
        uint8_t configBuffer[AN08_CONFIG_SIZE + 4];  // Small buffer, config is only 10 bytes
        if (Config::loadControlConfig(i + 1, configBuffer, sizeof(configBuffer))) {
            uint8_t bytesUsed = applyControlConfig(i + 1, configBuffer, sizeof(configBuffer));
            if (bytesUsed == 0) {
                EnigmaLogger::warning("AN08: Failed to apply stored config for CH%d", i + 1);
            }
        }
    }

    EnigmaLogger::info("BoardAN08::init() complete");
}

// ============================================================================
// update() - called every main loop iteration
// ============================================================================

void BoardAN08::update() {
    for (uint8_t i = 0; i < AN08_NUM_CHANNELS; i++) {
        if (!_hasConfig[i]) continue;

        uint16_t raw       = readMCP3008(logicalToHwChannel(i));
        uint16_t processed = processChannel(i, raw);

        // Signed delta to handle wrap-around correctly
        int32_t delta = (int32_t)processed - (int32_t)_lastReported[i];
        if (delta < 0) delta = -delta;

        if ((uint32_t)delta > _configs[i].deadband) {
            // Always update last-reported (even if disabled) to prevent burst on re-enable
            _lastReported[i] = processed;

            // Channel must be both SETCONFIG-enabled (NVS) and runtime-enabled (CMD_ENABLE mask).
            // The runtime mask matches SW14/QD04 behavior so the host can disable channels
            // without re-flashing, e.g. for damage simulation.
            if (_configs[i].enabled && isControlEnabled(i + 1)) {
                uint8_t stateData[2];
                stateData[0] = (uint8_t)(processed & 0xFF);
                stateData[1] = (uint8_t)((processed >> 8) & 0xFF);
                notifyStateChange(i + 1, stateData, 2);
            }
        }
    }
}

// ============================================================================
// applyControlConfig() - parse and store SETCONFIG payload, returns bytes to save
// ============================================================================

uint8_t BoardAN08::applyControlConfig(uint8_t controlNum, const uint8_t* rawConfig, size_t len) {
    if (controlNum < 1 || controlNum > AN08_NUM_CHANNELS) {
        EnigmaLogger::error("AN08: Invalid control number: %d", controlNum);
        return 0;
    }
    if (len < AN08_CONFIG_SIZE) {
        EnigmaLogger::error("AN08: Config too short: %d bytes (need %d)", (int)len, AN08_CONFIG_SIZE);
        return 0;
    }

    uint8_t idx = controlNum - 1;

    // Parse payload: control_num(1) + sensor_min_mv(2) + sensor_max_mv(2) +
    //                deadband(1) + gamma_x1000(2) + invert(1) + enabled(1)
    // sensor_min_mv / sensor_max_mv are voltage * 1000 (integer millivolts, 0-3300).
    // Convert to ADC counts using the board's 3.3V precision reference.
    uint16_t sensorMinMv = Config::getU16(rawConfig, 1);
    uint16_t sensorMaxMv = Config::getU16(rawConfig, 3);
    uint8_t  deadband    = Config::getU8(rawConfig, 5);
    uint16_t gammaX1000  = Config::getU16(rawConfig, 6);
    uint8_t  invert      = Config::getU8(rawConfig, 8);
    uint8_t  enabled     = Config::getU8(rawConfig, 9);

    // Convert millivolts to 10-bit ADC counts (reference = 3300 mV)
    uint16_t sensorMin = (uint16_t)((uint32_t)sensorMinMv * 1023 / 3300);
    uint16_t sensorMax = (uint16_t)((uint32_t)sensorMaxMv * 1023 / 3300);

    // Validate sensor range
    if (sensorMax <= sensorMin) {
        EnigmaLogger::warning("AN08: CH%d sensor_max_mv (%d) must be > sensor_min_mv (%d), resetting to defaults",
                              controlNum, sensorMaxMv, sensorMinMv);
        sensorMin = 0;
        sensorMax = 1023;
    }

    // Validate gamma (0 would cause powf domain error; clamp to reasonable range)
    if (gammaX1000 == 0) {
        EnigmaLogger::warning("AN08: CH%d gamma_x1000 is 0, resetting to 1000 (linear)", controlNum);
        gammaX1000 = 1000;
    }

    _configs[idx].sensorMin  = sensorMin;
    _configs[idx].sensorMax  = sensorMax;
    _configs[idx].deadband   = deadband;
    _configs[idx].gammaX1000 = gammaX1000;
    _configs[idx].invert     = invert ? 1 : 0;
    _configs[idx].enabled    = enabled ? 1 : 0;

    // Force a report on the next update() so host gets current value after reconfigure
    _lastReported[idx] = 0xFFFF;
    _hasConfig[idx] = true;

    return AN08_CONFIG_SIZE;  // All 10 bytes saved to NVS
}

// ============================================================================
// applyControlState() - SETSTATE is a NOP for read-only hardware
// ============================================================================

bool BoardAN08::applyControlState(uint8_t controlNum, const uint8_t* stateData, size_t len) {
    (void)controlNum; (void)stateData; (void)len;
    return true;  // ACK success, no action
}

// ============================================================================
// applyIndicatorUpdate() - SETINDICATOR is a NOP (no LEDs)
// ============================================================================

bool BoardAN08::applyIndicatorUpdate(uint8_t controlNum, const uint8_t* data, size_t len) {
    (void)controlNum; (void)data; (void)len;
    return true;  // ACK success, no action
}

// ============================================================================
// getControlState() - called by GETSTATE handler; bypasses deadband
// ============================================================================

uint8_t BoardAN08::getControlState(uint8_t controlNum, uint8_t* buffer, size_t maxLen) {
    if (controlNum < 1 || controlNum > AN08_NUM_CHANNELS || maxLen < 2) return 0;

    uint8_t idx = controlNum - 1;
    uint16_t raw = readMCP3008(logicalToHwChannel(idx));
    uint16_t processed = processChannel(idx, raw);

    buffer[0] = (uint8_t)(processed & 0xFF);
    buffer[1] = (uint8_t)((processed >> 8) & 0xFF);
    return 2;
}

// ============================================================================
// readMCP3008() - 3-byte SPI exchange to read one channel
//
// Protocol (MCP3008 single-ended mode):
//   TX: [0x01] [0x80|(ch<<4)] [0x00]
//   RX: [  --] [result_hi  ] [result_lo]
//   result = ((rx[1] & 0x03) << 8) | rx[2]   -> 10-bit, 0-1023
// ============================================================================

uint16_t BoardAN08::readMCP3008(uint8_t channel) {
    SPI.beginTransaction(kMCP3008_SPI);
    digitalWrite(AN08_PIN_CS, LOW);

    SPI.transfer(0x01);                          // Start bit
    uint8_t hi = SPI.transfer(0x80 | (channel << 4));  // SGL=1, channel select
    uint8_t lo = SPI.transfer(0x00);             // Clock out remaining bits

    digitalWrite(AN08_PIN_CS, HIGH);
    SPI.endTransaction();

    return ((uint16_t)(hi & 0x03) << 8) | lo;
}

// ============================================================================
// processChannel() - apply sensor remapping, gamma, and invert
// ============================================================================

uint16_t BoardAN08::processChannel(uint8_t idx, uint16_t raw) {
    const AN08ChannelConfig& cfg = _configs[idx];

    // Clamp to sensor range
    uint16_t clamped = raw;
    if (clamped < cfg.sensorMin) clamped = cfg.sensorMin;
    if (clamped > cfg.sensorMax) clamped = cfg.sensorMax;

    // Normalize to 0.0-1.0
    float norm = (float)(clamped - cfg.sensorMin) / (float)(cfg.sensorMax - cfg.sensorMin);

    // Apply gamma (skip powf when linear to avoid FPU overhead in hot path)
    float curved;
    if (cfg.gammaX1000 == 1000) {
        curved = norm;
    } else {
        float gamma = (float)cfg.gammaX1000 / 1000.0f;
        curved = powf(norm, gamma);
    }

    // Scale to 0-1023
    uint16_t out = (uint16_t)(curved * 1023.0f);
    if (out > 1023) out = 1023;

    // Invert if requested
    if (cfg.invert) out = 1023 - out;

    return out;
}
