// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

/*
 * BoardAN08.h - 8-channel 10-bit ADC board (MCP3008T-I/SL)
 *
 * SPI pin assignments:
 *   GPIO10: CS (manual)
 *   GPIO11: MOSI
 *   GPIO12: SCLK
 *   GPIO13: MISO
 *
 * SETCONFIG payload per channel (10 bytes total):
 *   [0]   control_num    uint8
 *   [1-2] sensor_min_mv  uint16 LE   sensor floor in millivolts (voltage * 1000, default 0)
 *   [3-4] sensor_max_mv  uint16 LE   sensor ceiling in millivolts (voltage * 1000, default 3300)
 *   [5]   deadband       uint8       min change in processed output to trigger report (default 2)
 *   [6-7] gamma_x1000    uint16 LE   gamma * 1000 (default 1000 = linear)
 *   [8]   invert         uint8       0=normal, 1=invert output
 *   [9]   enabled        uint8       0=disabled, 1=enabled
 *
 *   Millivolts are converted to ADC counts by applyControlConfig() using the
 *   board's 3.3V precision reference: adc = mv * 1023 / 3300
 *
 * REPORTSTATE payload per channel (2 bytes):
 *   [0-1] raw_value     uint16 LE   0-1023, post-pipeline
 *
 * Firmware pipeline per channel:
 *   raw   = MCP3008_read(ch)
 *   clamp = clamp(raw, sensor_min_adc, sensor_max_adc)   // converted from mV at config time
 *   norm  = (clamp - sensor_min_adc) / (sensor_max_adc - sensor_min_adc)
 *   curved = powf(norm, gamma)
 *   out   = (uint16_t)(curved * 1023)
 *   if invert: out = 1023 - out
 *   if enabled && |out - last_reported| > deadband -> REPORTSTATE
 *   last_reported = out  (updated even when disabled, to avoid burst on re-enable)
 */

#ifndef BOARD_AN08_H
#define BOARD_AN08_H

#include <Arduino.h>
#include <SPI.h>
#include "Board.h"
#include "Config.h"
#include "EnigmaLogger.h"

#define AN08_NUM_CHANNELS 8

// MCP3008 SPI pins
#define AN08_PIN_CS   10
#define AN08_PIN_MOSI 11
#define AN08_PIN_SCLK 12
#define AN08_PIN_MISO 13

// SETCONFIG payload size (including leading control_num byte)
#define AN08_CONFIG_SIZE 10

// Per-channel configuration - sensor range stored as ADC counts (converted from mV at config time)
struct AN08ChannelConfig {
    uint16_t sensorMin;     // ADC floor (converted from sensor_min_mv)
    uint16_t sensorMax;     // ADC ceiling (converted from sensor_max_mv)
    uint8_t  deadband;      // Min change in remapped output to trigger report
    uint16_t gammaX1000;    // Gamma * 1000 (1000 = linear, no pow() needed)
    uint8_t  invert;        // 1 = flip output (1023 - out)
    uint8_t  enabled;       // 1 = send REPORTSTATE on change
};

class BoardAN08 : public Board {
public:
    BoardAN08();
    ~BoardAN08() {}

    void    init() override;
    void    update() override;

    // Board interface
    uint8_t applyControlConfig(uint8_t controlNum, const uint8_t* rawConfig, size_t len) override;
    bool    applyControlState(uint8_t controlNum, const uint8_t* stateData, size_t len) override;
    bool    applyIndicatorUpdate(uint8_t controlNum, const uint8_t* data, size_t len) override;
    uint8_t getControlState(uint8_t controlNum, uint8_t* buffer, size_t maxLen) override;
    uint8_t getControlCount() override { return AN08_NUM_CHANNELS; }

private:
    AN08ChannelConfig _configs[AN08_NUM_CHANNELS];
    uint16_t          _lastReported[AN08_NUM_CHANNELS];
    bool              _hasConfig[AN08_NUM_CHANNELS];

    // Read one channel from the MCP3008 via SPI. Returns raw 0-1023.
    uint16_t readMCP3008(uint8_t channel);

    // Apply sensor_min/max remapping, gamma, and invert. Returns 0-1023.
    uint16_t processChannel(uint8_t idx, uint16_t raw);
};

#endif // BOARD_AN08_H
