cat << 'INNER_EOF' > safe-core-orchestrator/src/level25.rs
use crate::policy::barrier::{BarrierChecker, BarrierVerdict, TheoremClaim};
use crate::policy::ledger::{FailureLedger, DeflationClass, FailureEntry};
use crate::policy::trust_tier::{TrustTier, TrustedArtifact, ValidatorInfo, ValidationResult};
use chrono::{DateTime, Utc};
use std::collections::HashMap;

// ============================================================================
// 1. Orçamento de Validação
// ============================================================================

#[derive(Debug, Clone)]
pub struct ValidationBudget {
    pub max_llm_calls: usize,
    pub max_subagents: usize,
    pub max_runtime_secs: f64,
    pub remaining_llm_calls: usize,
    pub remaining_subagents: usize,
    start_time: DateTime<Utc>,
}

impl ValidationBudget {
    pub fn new(max_llm_calls: usize, max_subagents: usize, max_runtime_secs: f64) -> Self {
        Self {
            max_llm_calls,
            max_subagents,
            max_runtime_secs,
            remaining_llm_calls: max_llm_calls,
            remaining_subagents: max_subagents,
            start_time: Utc::now(),
        }
    }

    pub fn can_afford(&self, cost: ValidationCost) -> bool {
        match cost {
            ValidationCost::LlmCall => self.remaining_llm_calls > 0,
            ValidationCost::Subagent => self.remaining_subagents > 0,
            ValidationCost::Composite(costs) => {
                costs.iter().all(|c| self.can_afford(*c))
            }
        }
    }

    pub fn consume(&mut self, cost: ValidationCost) -> Result<(), BudgetError> {
        if !self.can_afford(cost) {
            return Err(BudgetError::InsufficientBudget);
        }
        match cost {
            ValidationCost::LlmCall => {
                self.remaining_llm_calls -= 1;
            }
            ValidationCost::Subagent => {
                self.remaining_subagents -= 1;
            }
            ValidationCost::Composite(costs) => {
                for c in costs {
                    self.consume(*c)?;
                }
            }
        }
        Ok(())
    }

    pub fn remaining_fraction(&self) -> f64 {
        let llm_frac = self.remaining_llm_calls as f64 / self.max_llm_calls as f64;
        let sub_frac = self.remaining_subagents as f64 / self.max_subagents as f64;
        (llm_frac + sub_frac) / 2.0
    }

    pub fn is_runtime_exceeded(&self) -> bool {
        let elapsed = Utc::now() - self.start_time;
        elapsed.num_seconds() as f64 > self.max_runtime_secs
    }
}

#[derive(Debug, Clone, Copy)]
pub enum ValidationCost {
    LlmCall,
    Subagent,
    Composite(&'static [ValidationCost]),
}

#[derive(Debug, Clone, thiserror::Error)]
pub enum BudgetError {
    #[error("Orçamento insuficiente para a operação")]
    InsufficientBudget,
    #[error("Tempo de execução excedido")]
    RuntimeExceeded,
}

// ============================================================================
// 2. Estruturas de Triage
// ============================================================================

#[derive(Debug, Clone)]
pub struct Strategy {
    pub id: String,
    pub claim: TheoremClaim,
    pub estimated_cost: ValidationCost,
}

#[derive(Debug, Clone)]
pub enum TriageVerdict {
    Deflated(DeflationClass),
    Novel { forecast: f64 },
}

// ============================================================================
// 3. Orquestrador Nível 2.5
// ============================================================================

pub struct Level25Orchestrator {
    triage: MetaCognitiveTriage,
    barrier: BarrierChecker,
    ledger: FailureLedger,
    budget: ValidationBudget,
    trust_registry: TrustRegistry,
}

impl Level25Orchestrator {
    pub fn new(budget: ValidationBudget) -> Self {
        Self {
            triage: MetaCognitiveTriage::new(),
            barrier: BarrierChecker::new(),
            ledger: FailureLedger::new(),
            budget,
            trust_registry: TrustRegistry::new(),
        }
    }

    pub fn evaluate(&mut self, proposal: Strategy) -> Result<OrchestratorDecision, OrchestratorError> {
        if !self.budget.can_afford(proposal.estimated_cost) {
            return Err(OrchestratorError::BudgetExhausted);
        }
        if self.budget.is_runtime_exceeded() {
            return Err(OrchestratorError::RuntimeExceeded);
        }

        let triage = self.triage.classify(&proposal);
        match triage {
            TriageVerdict::Deflated(class) => {
                let entry = FailureEntry {
                    strategy_id: proposal.id.clone(),
                    deflation_class: class.clone(),
                    kill_reason: format!("Deflated by triage: {:?}", class),
                    validators: vec!["triage-engine".to_string()],
                    timestamp: Utc::now(),
                    source_campaign: "auto".to_string(),
                };
                let _ = self.ledger.add(entry);
                return Ok(OrchestratorDecision::Reject {
                    reason: format!("Deflated: {:?}", class),
                });
            }
            TriageVerdict::Novel { forecast } => {
                let barrier = self.barrier.classify(&proposal.claim);
                if let BarrierVerdict::Barred { model, reason, .. } = barrier {
                    let entry = FailureEntry {
                        strategy_id: proposal.id.clone(),
                        deflation_class: DeflationClass::Novel,
                        kill_reason: format!("Barred by {}: {}", model, reason),
                        validators: vec!["barrier-checker".to_string()],
                        timestamp: Utc::now(),
                        source_campaign: "auto".to_string(),
                    };
                    let _ = self.ledger.add(entry);
                    return Ok(OrchestratorDecision::Reject {
                        reason: format!("Barred by {}: {}", model, reason),
                    });
                }

                if let Err(e) = self.budget.consume(proposal.estimated_cost) {
                    return Err(OrchestratorError::Internal(format!("Budget error: {}", e)));
                }

                let checkpoint = DurableCheckpoint::new(&proposal);
                Ok(OrchestratorDecision::Launch {
                    proposal,
                    forecast,
                    checkpoint,
                })
            }
        }
    }

    pub fn recover_orphan(&self, failed_agent: &AgentId) -> Result<AgentState, RecoveryError> {
        self.resilience_engine().recover(failed_agent)
    }

    fn resilience_engine(&self) -> &ResilienceEngine {
        &RESILIENCE_ENGINE
    }

    pub fn budget_status(&self) -> BudgetStatus {
        BudgetStatus {
            remaining_llm_calls: self.budget.remaining_llm_calls,
            remaining_subagents: self.budget.remaining_subagents,
            remaining_fraction: self.budget.remaining_fraction(),
            is_runtime_exceeded: self.budget.is_runtime_exceeded(),
            elapsed_secs: (Utc::now() - self.budget.start_time).num_seconds() as f64,
            max_runtime_secs: self.budget.max_runtime_secs,
        }
    }

    pub fn register_trusted<T>(&mut self, artifact: TrustedArtifact<T>) {
        self.trust_registry.register(artifact);
    }
}

// ============================================================================
// 4. Componentes Auxiliares
// ============================================================================

#[derive(Debug, Clone)]
pub struct MetaCognitiveTriage {}

impl MetaCognitiveTriage {
    pub fn new() -> Self {
        Self {}
    }

    pub fn classify(&self, proposal: &Strategy) -> TriageVerdict {
        if proposal.claim.statement.contains("Riemann Hypothesis") {
            TriageVerdict::Deflated(DeflationClass::EquivalentToTarget)
        } else if proposal.claim.statement.contains("known theorem") {
            TriageVerdict::Deflated(DeflationClass::KnownTheoremRestated)
        } else if proposal.claim.confidence < 0.3 {
            TriageVerdict::Deflated(DeflationClass::Tautological)
        } else {
            TriageVerdict::Novel { forecast: 0.6 + 0.3 * proposal.claim.confidence }
        }
    }
}

#[derive(Debug, Clone)]
pub struct DurableCheckpoint {
    pub strategy_id: String,
    pub state_hash: String,
    pub timestamp: DateTime<Utc>,
    pub signatures: Vec<String>,
}

impl DurableCheckpoint {
    pub fn new(proposal: &Strategy) -> Self {
        Self {
            strategy_id: proposal.id.clone(),
            state_hash: format!("hash:{}", proposal.claim.statement.len()),
            timestamp: Utc::now(),
            signatures: Vec::new(),
        }
    }
}

pub struct AgentState {
    pub agent_id: String,
    pub status: String,
    pub checkpoint: DurableCheckpoint,
}

#[derive(Debug, Clone)]
pub struct AgentId(pub String);

pub struct ResilienceEngine;

impl ResilienceEngine {
    pub fn recover(&self, agent_id: &AgentId) -> Result<AgentState, RecoveryError> {
        Ok(AgentState {
            agent_id: agent_id.0.clone(),
            status: "recovered".to_string(),
            checkpoint: DurableCheckpoint {
                strategy_id: agent_id.0.clone(),
                state_hash: "recovered".to_string(),
                timestamp: Utc::now(),
                signatures: Vec::new(),
            },
        })
    }
}

pub struct TrustRegistry {
    artifacts: Vec<TrustedArtifact<TheoremClaim>>,
}

impl TrustRegistry {
    pub fn new() -> Self {
        Self { artifacts: Vec::new() }
    }

    pub fn register<T>(&mut self, artifact: TrustedArtifact<T>) {
        let _ = artifact;
    }
}

// ============================================================================
// 5. Decisões e Erros
// ============================================================================

#[derive(Debug, Clone)]
pub enum OrchestratorDecision {
    Reject { reason: String },
    Launch { proposal: Strategy, forecast: f64, checkpoint: DurableCheckpoint },
}

#[derive(Debug, Clone, thiserror::Error)]
pub enum OrchestratorError {
    #[error("Orçamento de validação exaurido")]
    BudgetExhausted,
    #[error("Tempo de execução excedido")]
    RuntimeExceeded,
    #[error("Falha interna do orquestrador: {0}")]
    Internal(String),
}

#[derive(Debug, Clone, thiserror::Error)]
pub enum RecoveryError {
    #[error("Checkpoint não encontrado para o agente")]
    CheckpointNotFound,
    #[error("Assinaturas inválidas ou insuficientes")]
    InvalidSignatures,
    #[error("Falha na recuperação: {0}")]
    Other(String),
}

#[derive(Debug, Clone)]
pub struct BudgetStatus {
    pub remaining_llm_calls: usize,
    pub remaining_subagents: usize,
    pub remaining_fraction: f64,
    pub is_runtime_exceeded: bool,
    pub elapsed_secs: f64,
    pub max_runtime_secs: f64,
}

// ============================================================================
// 6. Constantes Globais (Stubs)
// ============================================================================

static RESILIENCE_ENGINE: ResilienceEngine = ResilienceEngine;

// ============================================================================
// 7. Testes
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_budget_consume() {
        let mut budget = ValidationBudget::new(10, 5, 60.0);
        assert!(budget.can_afford(ValidationCost::LlmCall));
        budget.consume(ValidationCost::LlmCall).unwrap();
        assert_eq!(budget.remaining_llm_calls, 9);
    }

    #[test]
    fn test_budget_exhausted() {
        let mut budget = ValidationBudget::new(1, 1, 60.0);
        budget.consume(ValidationCost::LlmCall).unwrap();
        assert!(budget.consume(ValidationCost::LlmCall).is_err());
    }

    #[test]
    fn test_orchestrator_rejects_deflated() {
        let budget = ValidationBudget::new(10, 5, 60.0);
        let mut orchestrator = Level25Orchestrator::new(budget);
        let proposal = Strategy {
            id: "test-1".to_string(),
            claim: TheoremClaim {
                statement: "Riemann Hypothesis is proven".to_string(),
                domain: "number-theory".to_string(),
                confidence: 0.9,
            },
            estimated_cost: ValidationCost::LlmCall,
        };

        let decision = orchestrator.evaluate(proposal).unwrap();
        match decision {
            OrchestratorDecision::Reject { reason } => {
                assert!(reason.contains("Deflated"));
            }
            _ => panic!("Deveria ter sido rejeitado"),
        }
    }
}
INNER_EOF
