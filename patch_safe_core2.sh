cat << 'INNER_EOF' > safe-core-policy/src/barrier.rs
#[derive(Debug, Clone)]
pub enum BarrierVerdict {
    Barred { model: String, reason: String, confidence: f64 },
    Pass,
}

// Dummy TheoremClaim for tests here as it belongs to orchestrator
#[derive(Debug, Clone)]
pub struct DummyClaim {
    pub statement: String,
}

pub struct BarrierChecker;
impl BarrierChecker {
    pub fn new() -> Self { Self }
    // Using a generic here or referencing something local
    // Let's accept anything string-like for the claim statement, or make it generic over T
    // Since Level25Orchestrator uses it, let's keep it simple
}

impl BarrierChecker {
    // In Rust, cross-crate cyclic dependencies are bad.
    // If barrier checker needs TheoremClaim from orchestrator, orchestrator should define barrier or TheoremClaim should be in policy.
    // Given the previous code, TheoremClaim is defined in orchestrator but used in policy. We will move TheoremClaim to policy to fix E0433.
}
INNER_EOF

# We will move TheoremClaim to safe-core-policy/src/barrier.rs
cat << 'INNER_EOF' > safe-core-policy/src/barrier.rs
#[derive(Debug, Clone)]
pub struct TheoremClaim {
    pub statement: String,
    pub domain: String,
    pub confidence: f64,
}

#[derive(Debug, Clone)]
pub enum BarrierVerdict {
    Barred { model: String, reason: String, confidence: f64 },
    Pass,
}

pub struct BarrierChecker;
impl BarrierChecker {
    pub fn new() -> Self { Self }
    pub fn classify(&self, _claim: &TheoremClaim) -> BarrierVerdict { BarrierVerdict::Pass }
}
INNER_EOF

# Remove TheoremClaim from safe-core-orchestrator/src/level25.rs
sed -i '/pub struct TheoremClaim {/,/}/d' safe-core-orchestrator/src/level25.rs
sed -i 's/pub claim: TheoremClaim,/pub claim: safe_core_policy::barrier::TheoremClaim,/' safe-core-orchestrator/src/level25.rs
