sed -i 's/frobenius_norm/norm/g' safe-core-evidence/src/coherence_inertia.rs
sed -i 's/use nalgebra::{DMatrix, DVector, SymmetricEigen};/use nalgebra::{DMatrix, SymmetricEigen};/' safe-core-evidence/src/coherence_inertia.rs
sed -i 's/self.validators.push(validator);/self.validators.push(validator.clone());/' safe-core-policy/src/trust_tier.rs
