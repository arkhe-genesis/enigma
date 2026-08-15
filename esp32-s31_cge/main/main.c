// esp32-s31_cge/main/main.c

#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "driver/spi_master.h"
#include "safecore_protocol.h"

#include "partition.h"          // partition_function_fast()
#include "c10_baryon_ratio.h"
#include "c11_parity_violation.h"
#include "concept_space_v2.h"   // golden‑angle concept space
#include "deflection_unwrap.h"

static const char *TAG = "CGE";

// Parâmetros constitucionais
float phi_global = 1.030f;
float tau = 0.5f;
float z = 100.0f;
float polarization = 0.9f;
float asymmetry = 0.15f;
float efficiency = 0.025f;
float local_coherence = 0.48f;

void cge_task(void *pvParameter) {
    spi_device_handle_t spi_ellis, spi_sasc, spi_karnak;

    // Inicializar SPI master
    spi_bus_config_t buscfg = {
        .mosi_io_num = 11,
        .miso_io_num = 12,
        .sclk_io_num = 13,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
    };
    spi_bus_initialize(SPI2_HOST, &buscfg, SPI_DMA_DISABLED);

    // Configurar slaves (Ellis, SASC, Karnak)
    spi_device_interface_config_t devcfg = {
        .mode = 0,                 // SPI mode 0
        .clock_speed_hz = 10*1000*1000,
        .spics_io_num = 10,        // CS Ellis
        .queue_size = 7,
    };
    spi_bus_add_device(SPI2_HOST, &devcfg, &spi_ellis);
    devcfg.spics_io_num = 9;       // CS SASC
    spi_bus_add_device(SPI2_HOST, &devcfg, &spi_sasc);
    devcfg.spics_io_num = 8;       // CS Karnak
    spi_bus_add_device(SPI2_HOST, &devcfg, &spi_karnak);

    // Inicializar lookup table para partição
    float aq = 3.086e-10f; // 0.3086 nm em metros
    float mass = 0.4f * 9.10938356e-31f;
    init_partition_lookup(aq, 1.1f, 10.0f);

    while (1) {
        // 1. Calcular Z via função de partição (Ellis Engine)
        float beta = efficiency; // η
        z = partition_function_fast(aq, mass, beta, 1.1f, 10.0f);

        // 2. Atualizar métricas locais (simuladas)
        // Em produção, viriam de sensores ou do Ellis/Vajra via SPI
        phi_global = 1.030f;
        tau = 0.5f;
        polarization = 0.9f;
        asymmetry = 0.15f;
        efficiency = 0.025f;
        local_coherence = phi_global * 0.5f;

        // 3. Verificar invariantes
        bool c10_ok = baryon_ratio_invariant(phi_global, local_coherence);
        bool c11_ok = parity_violation_invariant(asymmetry, polarization, efficiency);

        if (!c10_ok || !c11_ok) {
            // Enviar Quench para Karnak imediatamente
            ConstitutionalPacket quench_pkt = {
                .sync = 0xA5,
                .cmd = 0x02,
                .timestamp = esp_timer_get_time() / 1000,
                .phi = phi_global,
                .tau = tau,
                .z = z,
                .regime = REGIME_QUENCH,
                .checksum = 0
            };
            quench_pkt.checksum = crc16((uint8_t*)&quench_pkt, sizeof(quench_pkt)-2);
            spi_transmit(spi_karnak, (uint8_t*)&quench_pkt, sizeof(quench_pkt));

            ESP_LOGW(TAG, "⚠️ Invariantes violados! Quench acionado.");
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }

        // 4. Decidir regime
        RegimeAction regime;
        if (z > 1000.0f && phi_global > 1.03f) {
            regime = REGIME_MAINTAIN;
        } else if (z > 100.0f && phi_global > 1.02f) {
            regime = REGIME_EXPLORE;
        } else if (z > 10.0f) {
            regime = REGIME_DECOUPLE;
        } else {
            regime = REGIME_QUENCH;
        }

        // 5. Construir e enviar pacote para todos os slaves
        ConstitutionalPacket pkt = {
            .sync = 0xA5,
            .cmd = 0x02,
            .timestamp = esp_timer_get_time() / 1000,
            .phi = phi_global,
            .tau = tau,
            .z = z,
            .regime = regime,
            .checksum = 0
        };
        pkt.checksum = crc16((uint8_t*)&pkt, sizeof(pkt)-2);

        // Enviar via SPI para Ellis/Vajra, SASC e Karnak
        spi_transmit(spi_ellis, (uint8_t*)&pkt, sizeof(pkt));
        spi_transmit(spi_sasc, (uint8_t*)&pkt, sizeof(pkt));
        spi_transmit(spi_karnak, (uint8_t*)&pkt, sizeof(pkt));

        ESP_LOGI(TAG, "📊 Φ=%.3f τ=%.3f Z=%.4f Regime=%d", phi_global, tau, z, regime);

        // Aguardar próximo ciclo (10 Hz)
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

void app_main() {
    esp_log_level_set("*", ESP_LOG_INFO);
    xTaskCreate(cge_task, "cge_task", 8192, NULL, 5, NULL);
}