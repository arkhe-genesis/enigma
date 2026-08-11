#[derive(Debug, Clone)]
pub enum DeflationClass {
    EquivalentToTarget,
    KnownTheoremRestated,
    Tautological,
    Novel,
}
#[derive(Debug, Clone)]
pub struct FailureEntry {
    pub strategy_id: String,
    pub deflation_class: DeflationClass,
    pub kill_reason: String,
    pub validators: Vec<String>,
    pub timestamp: chrono::DateTime<chrono::Utc>,
    pub source_campaign: String,
}
pub struct FailureLedger;
impl FailureLedger {
    pub fn new() -> Self { Self }
    pub fn add(&self, _entry: FailureEntry) -> Result<(), ()> { Ok(()) }
}
