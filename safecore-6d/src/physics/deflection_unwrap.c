// safecore-6d/src/physics/deflection_unwrap.c

#include <math.h>
#include <stdbool.h>

// Função para desembrulhar uma sequência de ângulos (simula np.unwrap)
void unwrap_angles(float *phi, int n) {
    float last = phi[0];
    for (int i = 1; i < n; i++) {
        float diff = phi[i] - last;
        if (diff > M_PI) {
            phi[i] -= 2.0f * M_PI;
        } else if (diff < -M_PI) {
            phi[i] += 2.0f * M_PI;
        }
        last = phi[i];
    }
}

float compute_deflection_cumulative(float *phi, float *r, int n, float aq, float frac) {
    // Selecionar últimos pontos (assintóticos)
    int n_use = (int)(frac * n);
    if (n_use < 5) n_use = 5;

    // Desembrulhar os ângulos da cauda
    float *phi_tail = &phi[n - n_use];
    unwrap_angles(phi_tail, n_use);

    // Média dos ângulos de entrada (primeiros n_use) e saída (últimos n_use)
    float phi_in = 0.0f, phi_out = 0.0f;
    for (int i = 0; i < n_use; i++) {
        phi_in += phi[i];
        phi_out += phi[n - n_use + i];
    }
    phi_in /= n_use;
    phi_out /= n_use;

    float delta = phi_out - phi_in;
    if (delta < 0.0f) delta += 2.0f * M_PI; // Correção para ângulos negativos

    float theta = 2.0f * delta - M_PI;
    // Normalizar para [-π, π]
    theta = fmodf(theta, 2.0f * M_PI);
    if (theta > M_PI) theta -= 2.0f * M_PI;
    return theta;
}