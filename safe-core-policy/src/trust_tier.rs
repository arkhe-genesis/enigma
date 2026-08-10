// safe-core-policy/src/trust_tier.rs
//! Trust Tiers para validação de artefatos de AGI.
//!
//! Inspirado no processo de validação do artigo zeta-23:
//! 1. InternalOnly → geração por IA sem verificação externa
//! 2. CrossModel → verificação por múltiplos modelos de IA
//! 3. SymbolicVerified → verificação por sistema formal (ex: Lean, Coq)
//! 4. FormalVerified → verificação formal completa com auditoria de axiomas
//! 5. HumanAudited → revisão por especialista humano de domínio

use serde::{Deserialize, Serialize};
use std::fmt;

// ============================================================================
// 1. Níveis de Confiança
// ============================================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum TrustTier {
    /// Geração por IA, sem verificação externa ou formal.
    /// **Nunca deployar em produção.**
    InternalOnly = 0,

    /// Verificação por múltiplos modelos de IA independentes (≥2 famílias).
    CrossModel = 1,

    /// Verificação por sistema formal (Lean, Coq, etc.) com especificação simbólica.
    /// Ainda requer auditoria de axiomas e convenções.
    SymbolicVerified = 2,

    /// Verificação formal completa: `sorry`-free, `#print axioms` audit, sem axiomas
    /// além dos padrões.
    FormalVerified = 3,

    /// Revisão por especialista humano de domínio.
    /// O mais alto nível de confiança.
    HumanAudited = 4,
}

impl TrustTier {
    /// Retorna uma descrição textual do nível.
    pub fn description(&self) -> &'static str {
        match self {
            TrustTier::InternalOnly => "Geração por IA — não verificado externamente",
            TrustTier::CrossModel => "Verificação por múltiplos modelos de IA",
            TrustTier::SymbolicVerified => "Verificação simbólica por sistema formal",
            TrustTier::FormalVerified => "Verificação formal completa (Lean/Coq)",
            TrustTier::HumanAudited => "Revisão por especialista humano",
        }
    }

    /// Retorna o critério de promoção para o próximo nível.
    pub fn promotion_criterion(&self) -> &'static str {
        match self {
            TrustTier::InternalOnly => "≥2 modelos de IA independentes + especificação formal",
            TrustTier::CrossModel => "Formalização `sorry`-free + auditoria de axiomas",
            TrustTier::SymbolicVerified => "`#print axioms` retorna apenas axiomas padrão",
            TrustTier::FormalVerified => "Revisão por especialista humano de domínio",
            TrustTier::HumanAudited => "Nível máximo — nenhuma promoção adicional",
        }
    }

    /// Verifica se um artefato neste nível pode ser deployado em produção.
    pub fn is_deployable(&self) -> bool {
        matches!(self, TrustTier::FormalVerified | TrustTier::HumanAudited)
    }

    /// Verifica se este nível é considerado "verificado" (não apenas gerado).
    pub fn is_verified(&self) -> bool {
        !matches!(self, TrustTier::InternalOnly)
    }

    /// Retorna o próximo nível, se existir.
    pub fn next_level(&self) -> Option<TrustTier> {
        match self {
            TrustTier::InternalOnly => Some(TrustTier::CrossModel),
            TrustTier::CrossModel => Some(TrustTier::SymbolicVerified),
            TrustTier::SymbolicVerified => Some(TrustTier::FormalVerified),
            TrustTier::FormalVerified => Some(TrustTier::HumanAudited),
            TrustTier::HumanAudited => None,
        }
    }

    /// Ordena por confiança (crescente).
    pub fn sort_by_trust(tiers: &[TrustTier]) -> Vec<TrustTier> {
        let mut v = tiers.to_vec();
        v.sort();
        v
    }

    /// Retorna a confiança mínima necessária para um dado uso.
    pub fn minimum_for_use(usage: ArtifactUsage) -> TrustTier {
        match usage {
            ArtifactUsage::Research => TrustTier::InternalOnly,
            ArtifactUsage::Prototype => TrustTier::CrossModel,
            ArtifactUsage::Simulation => TrustTier::SymbolicVerified,
            ArtifactUsage::Production => TrustTier::FormalVerified,
            ArtifactUsage::SafetyCritical => TrustTier::HumanAudited,
        }
    }
}

impl fmt::Display for TrustTier {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:?}", self)
    }
}

// ============================================================================
// 2. Uso de Artefato
// ============================================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ArtifactUsage {
    /// Pesquisa exploratória — qualquer nível é aceitável
    Research,
    /// Protótipo para testes internos
    Prototype,
    /// Simulação controlada
    Simulation,
    /// Deploy em produção
    Production,
    /// Sistema crítico de segurança
    SafetyCritical,
}

// ============================================================================
// 3. Artefato com Nível de Confiança
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrustedArtifact<T> {
    pub content: T,
    pub tier: TrustTier,
    pub validators: Vec<ValidatorInfo>,
    pub timestamp: chrono::DateTime<chrono::Utc>,
    pub audit_trail: Vec<AuditEntry>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidatorInfo {
    pub name: String,
    pub tier: TrustTier,
    pub result: ValidationResult,
    pub timestamp: chrono::DateTime<chrono::Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ValidationResult {
    Pass,
    Fail { reason: String },
    Conditional { caveat: String },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuditEntry {
    pub from_tier: TrustTier,
    pub to_tier: TrustTier,
    pub reason: String,
    pub validators: Vec<String>,
    pub timestamp: chrono::DateTime<chrono::Utc>,
}

impl<T> TrustedArtifact<T> {
    pub fn new(content: T) -> Self {
        Self {
            content,
            tier: TrustTier::InternalOnly,
            validators: Vec::new(),
            timestamp: chrono::Utc::now(),
            audit_trail: Vec::new(),
        }
    }

    /// Promove o artefato para o próximo nível de confiança.
    pub fn promote(&mut self, validator: ValidatorInfo) -> Result<(), TrustError> {
        if validator.tier < self.tier {
            return Err(TrustError::CannotDowngrade);
        }

        let next_tier = self.tier.next_level();
        if let Some(target) = next_tier {
            // Verifica se o validador tem tier suficiente para a promoção
            if validator.tier < target {
                return Err(TrustError::InsufficientValidatorTier);
            }

            // Verifica se há quorum (mínimo 2 validadores para CrossModel)
            if target == TrustTier::CrossModel {
                let cross_model_count = self.validators.iter()
                    .filter(|v| v.tier >= TrustTier::CrossModel)
                    .count();
                if cross_model_count < 2 {
                    return Err(TrustError::InsufficientQuorum);
                }
            }

            let old_tier = self.tier;
            self.tier = target;
            self.validators.push(validator.clone());
            self.audit_trail.push(AuditEntry {
                from_tier: old_tier,
                to_tier: target,
                reason: format!("Promoção por validador: {}", validator.name),
                validators: self.validators.iter().map(|v| v.name.clone()).collect(),
                timestamp: chrono::Utc::now(),
            });
            Ok(())
        } else {
            Err(TrustError::AlreadyMaxTier)
        }
    }

    /// Verifica se o artefato atende ao nível mínimo para um dado uso.
    pub fn meets_usage(&self, usage: ArtifactUsage) -> bool {
        self.tier >= TrustTier::minimum_for_use(usage)
    }
}

// ============================================================================
// 4. Erros
// ============================================================================

#[derive(Debug, Clone, PartialEq, thiserror::Error)]
pub enum TrustError {
    #[error("Não é possível fazer downgrade de confiança")]
    CannotDowngrade,
    #[error("Validador com tier insuficiente para a promoção")]
    InsufficientValidatorTier,
    #[error("Quorum insuficiente para CrossModel (mínimo 2)")]
    InsufficientQuorum,
    #[error("Artefato já está no nível máximo de confiança")]
    AlreadyMaxTier,
    #[error("Validador inválido: {0}")]
    InvalidValidator(String),
}

// ============================================================================
// 5. Testes
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_tier_ordering() {
        assert!(TrustTier::InternalOnly < TrustTier::CrossModel);
        assert!(TrustTier::CrossModel < TrustTier::SymbolicVerified);
        assert!(TrustTier::SymbolicVerified < TrustTier::FormalVerified);
        assert!(TrustTier::FormalVerified < TrustTier::HumanAudited);
    }

    #[test]
    fn test_minimum_for_use() {
        assert_eq!(TrustTier::minimum_for_use(ArtifactUsage::Research), TrustTier::InternalOnly);
        assert_eq!(TrustTier::minimum_for_use(ArtifactUsage::Prototype), TrustTier::CrossModel);
        assert_eq!(TrustTier::minimum_for_use(ArtifactUsage::Simulation), TrustTier::SymbolicVerified);
        assert_eq!(TrustTier::minimum_for_use(ArtifactUsage::Production), TrustTier::FormalVerified);
        assert_eq!(TrustTier::minimum_for_use(ArtifactUsage::SafetyCritical), TrustTier::HumanAudited);
    }

    #[test]
    fn test_deployable() {
        assert!(!TrustTier::InternalOnly.is_deployable());
        assert!(!TrustTier::CrossModel.is_deployable());
        assert!(!TrustTier::SymbolicVerified.is_deployable());
        assert!(TrustTier::FormalVerified.is_deployable());
        assert!(TrustTier::HumanAudited.is_deployable());
    }
}
