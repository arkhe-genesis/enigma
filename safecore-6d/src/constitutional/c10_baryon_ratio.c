// safecore-6d/src/constitutional/c10_baryon_ratio.c

#include <stdbool.h>

#define MIN_RATIO 2.0f
#define TOL 0.1f

bool baryon_ratio_invariant(float phi_global, float local_coherence) {
    if (local_coherence < 1e-12f) {
        return phi_global >= (MIN_RATIO - TOL);
    }
    float ratio = phi_global / local_coherence;
    return (ratio >= (MIN_RATIO - TOL)) && (ratio <= (MIN_RATIO + 2.0f * TOL));
}