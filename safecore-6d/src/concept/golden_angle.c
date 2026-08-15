// safecore-6d/src/concept/golden_angle.c

#include <math.h>
#include <stddef.h>
#include <stdlib.h>

typedef struct {
    float r;
    float phi;
    float psi;
    int level;
    int parent;
} ConceptV2;

typedef struct {
    ConceptV2 *concepts;
    size_t count;
    float aq;
    int depth;
    int branching;
} ConceptSpaceV2;

ConceptSpaceV2* concept_space_v2_new(float aq, int depth, int branching) {
    ConceptSpaceV2 *cs = malloc(sizeof(ConceptSpaceV2));
    cs->aq = aq;
    cs->depth = depth;
    cs->branching = branching;

    // Número total de conceitos: 1 + sum_{l=1}^{depth} branching^l
    size_t total = 1;
    size_t level_count = 1;
    for (int l = 1; l <= depth; l++) {
        level_count *= branching;
        total += level_count;
    }
    cs->count = total;
    cs->concepts = malloc(total * sizeof(ConceptV2));

    // Raiz
    cs->concepts[0] = (ConceptV2){ .r = aq * 0.5f, .phi = 0.0f, .psi = 0.0f, .level = 0, .parent = -1 };

    size_t idx = 1;
    int nodes_at_level = 1;
    int *level_indices = malloc(sizeof(int));
    level_indices[0] = 0;

    const float GOLDEN_ANGLE = M_PI * (3.0f - sqrtf(5.0f));

    for (int lvl = 1; lvl <= depth; lvl++) {
        float r_level = aq * (1.0f + 0.8f * lvl);
        int num_parents = nodes_at_level;
        int *new_indices = malloc(num_parents * branching * sizeof(int));
        int new_count = 0;

        for (int p = 0; p < num_parents; p++) {
            int parent_idx = level_indices[p];
            ConceptV2 *parent = &cs->concepts[parent_idx];
            for (int child = 0; child < branching; child++) {
                float phi = parent->phi + child * GOLDEN_ANGLE + GOLDEN_ANGLE * 0.5f;
                phi = fmodf(phi, 2.0f * M_PI);
                cs->concepts[idx] = (ConceptV2){
                    .r = r_level,
                    .phi = phi,
                    .psi = 0.0f,
                    .level = lvl,
                    .parent = parent_idx
                };
                new_indices[new_count++] = idx;
                idx++;
            }
        }

        free(level_indices);
        level_indices = new_indices;
        nodes_at_level = new_count;
    }

    free(level_indices);
    return cs;
}

void concept_space_v2_free(ConceptSpaceV2 *cs) {
    free(cs->concepts);
    free(cs);
}