// esp32-c6_coord/main/main.c

#include "esp_zb_zcl.h"
#include "esp_zb_zigbee.h"

float entropia_acumulada = 0.0f;
int num_sensores = 0;

void zb_entropy_report_callback(esp_zb_zcl_report_attr_resp_t *resp) {
    // Extrair temperatura, humidade e lux do payload
    float temp, hum, lux;
    memcpy(&temp, resp->data, 4);
    memcpy(&hum, resp->data+4, 4);
    memcpy(&lux, resp->data+8, 4);

    // Acumular entropia
    float entropy = -logf(temp / 100.0f) - logf(hum / 100.0f) - logf(lux / 1000.0f);
    entropia_acumulada += entropy;
    num_sensores++;

    // Se tivermos dados de todos os sensores, enviar para o CGE via SPI
    if (num_sensores >= 10) {
        float entropia_media = entropia_acumulada / num_sensores;
        // Enviar para ESP32‑S31 via SPI (como parte da métrica Vajra)
        constitutional_packet_t pkt;
        pkt.sync = 0xA5;
        pkt.cmd = 0x01;
        pkt.phi = 0.0; // será preenchido pelo CGE
        pkt.tau = 0.0;
        pkt.z = entropia_media; // Usamos Z como proxy de entropia
        pkt.regime = 0;
        pkt.checksum = crc16((uint8_t*)&pkt, sizeof(pkt)-2);

        spi_send_packet(&pkt);

        // Resetar contadores
        entropia_acumulada = 0.0f;
        num_sensores = 0;
    }
}