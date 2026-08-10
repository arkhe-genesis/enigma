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
