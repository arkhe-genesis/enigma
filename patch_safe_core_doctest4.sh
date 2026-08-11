sed -i 's/\/\/! Para c > 0, P ⪰ 0 com rank ≤ r, Q com n₊(Q) ≤ b:/\/\/! Para c > 0, P >= 0 com rank <= r, Q com n+(Q) <= b:/g' safe-core-evidence/src/coherence_inertia.rs
sed -i 's/\/\/!     ||P + Q||^2_F >= c.tr(P) - (c^2\/4).r + 2c.tr(Q) - c^2.b/    \/\/ ||P + Q||^2_F >= c.tr(P) - (c^2\/4).r + 2c.tr(Q) - c^2.b/g' safe-core-evidence/src/coherence_inertia.rs
sed -i 's/\/\/! Portanto:/\/\/ Portanto:/g' safe-core-evidence/src/coherence_inertia.rs
sed -i 's/\/\/!     r >= (4\/c).tr(P) + (8\/c).tr(Q) - 4.b - (4\/c^2).||P+Q||^2_F/    \/\/ r >= (4\/c).tr(P) + (8\/c).tr(Q) - 4.b - (4\/c^2).||P+Q||^2_F/g' safe-core-evidence/src/coherence_inertia.rs
sed -i 's/\/\/! Para c = 2 (caso do Teorema A\/B):/\/\/ Para c = 2 (caso do Teorema A\/B):/g' safe-core-evidence/src/coherence_inertia.rs
sed -i 's/\/\/!     r >= 2.tr(P) + 4.tr(Q) - 4.b - ||P+Q||^2_F/    \/\/ r >= 2.tr(P) + 4.tr(Q) - 4.b - ||P+Q||^2_F/g' safe-core-evidence/src/coherence_inertia.rs
sed -i 's/\/\/! Para c = 3 (caso do Teorema C, m^2 >= 3m - 2):/\/\/ Para c = 3 (caso do Teorema C, m^2 >= 3m - 2):/g' safe-core-evidence/src/coherence_inertia.rs
sed -i 's/\/\/!     r >= (4\/3).tr(P) + (8\/3).tr(Q) - 4.b - (4\/9).||P+Q||^2_F/    \/\/ r >= (4\/3).tr(P) + (8\/3).tr(Q) - 4.b - (4\/9).||P+Q||^2_F/g' safe-core-evidence/src/coherence_inertia.rs
