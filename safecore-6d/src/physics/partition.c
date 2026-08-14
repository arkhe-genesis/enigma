// safecore-6d/src/physics/partition.c

#include <math.h>
#include "ellis_metric.h"
#include "geodesic_rk4.h"

// Tabela de lookup para valores de b/a_q e Θ pré‑calculados
// (reduz o custo de ellipk em RISC‑V)
#define LOOKUP_SIZE 100
static float theta_lookup[LOOKUP_SIZE];
static float b_over_aq_lookup[LOOKUP_SIZE];

void init_partition_lookup(float aq, float b_min_ratio, float b_max_ratio) {
    for (int i = 0; i < LOOKUP_SIZE; i++) {
        float ratio = b_min_ratio + (b_max_ratio - b_min_ratio) * i / (LOOKUP_SIZE - 1);
        b_over_aq_lookup[i] = ratio;
        theta_lookup[i] = deflection_angle_exact(ratio * aq, aq);
    }
}

// Função de partição com interpolação linear (aproximação rápida para RISC‑V)
float partition_function_fast(float aq, float mass, float beta, float b_min_ratio, float b_max_ratio) {
    float z = 0.0f;
    float b_min = b_min_ratio * aq;
    float b_max = b_max_ratio * aq;

    // Amostragem uniforme (apenas 10 pontos para velocidade)
    for (int i = 0; i < 10; i++) {
        float b = b_min + (b_max - b_min) * i / 9.0f;
        float ratio = b / aq;

        // Interpolação de theta a partir da lookup table
        float theta = interp1d(b_over_aq_lookup, theta_lookup, LOOKUP_SIZE, ratio);
        if (theta < 0.0f) continue;

        float s_eff = 0.5f * mass * aq * aq * theta * theta;
        z += expf(-beta * s_eff);
    }
    return z;
}