//! Arkhe SoC TLM v2.0 — Transaction-Level Model
//! Selo: ARKHE-SOC-TLM-v2.0-2026-07-31

use serde::{Deserializer, Serializer};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

pub const DOMAIN_NODES: usize = 8;
pub const FULL_NODES: usize = 16;
pub const MAX_SWARMS: usize = 15;
pub const SENTINEL: u64 = u64::MAX;
pub const REFERENCE_SOL_US: f64 = 2.37; // arXiv:2607.16100

// ==========================================================
// ERROS DE BARRAMENTO (AXI4-Lite-like)
// ==========================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SocError {
    InvalidAddress(u32),
    AlignmentError(u32),
    Busy,
    SecurityViolation,
    Timeout,
}

// ==========================================================
// TRAITS DE PERIFÉRICO (Lei do RTL futuro)
// ==========================================================

pub trait ArkhePeripheral {
    fn read_reg(&mut self, addr: u32) -> Result<u32, SocError>;
    fn write_reg(&mut self, addr: u32, val: u32) -> Result<(), SocError>;
}

// ==========================================================
// CONTADORES DE PERFORMANCE (Memory-mapped)
// ==========================================================

#[repr(C)]
#[derive(Debug, Clone, Copy, PartialEq, Default, serde::Serialize)]
pub struct PerformanceCounters {
    pub qpl_cycles: u64,
    pub expand_cycles: u64,
    pub encode_cycles: u64,
    pub verify_cycles: u64,
    pub frames_emitted: u64,
    pub frames_dropped: u64,
    pub frames_rejected: u64,
    pub swarms_completed: u64,
    pub power_mw: u32,
    pub bus_contentions: u32,
}

impl PerformanceCounters {
    pub fn merge(&mut self, other: &Self) {
        self.qpl_cycles += other.qpl_cycles;
        self.expand_cycles += other.expand_cycles;
        self.encode_cycles += other.encode_cycles;
        self.verify_cycles += other.verify_cycles;
        self.frames_emitted += other.frames_emitted;
        self.frames_dropped += other.frames_dropped;
        self.frames_rejected += other.frames_rejected;
        self.swarms_completed += other.swarms_completed;
        self.bus_contentions += other.bus_contentions;
    }
}

// ==========================================================
// CLOCK DOMAIN (Simulação temporal)
// ==========================================================

pub struct ClockDomain {
    pub freq_mhz: u32,
    cycle_count: AtomicU64,
}

impl ClockDomain {
    pub fn new(freq_mhz: u32) -> Self {
        Self {
            freq_mhz,
            cycle_count: AtomicU64::new(0),
        }
    }

    pub fn tick(&self, cycles: u64) -> Duration {
        self.cycle_count.fetch_add(cycles, Ordering::SeqCst);
        let ns = (cycles * 1_000) / self.freq_mhz as u64;
        Duration::from_nanos(ns)
    }

    pub fn cycles_to_us(&self, cycles: u64) -> f64 {
        (cycles as f64) / (self.freq_mhz as f64)
    }

    pub fn total_cycles(&self) -> u64 {
        self.cycle_count.load(Ordering::SeqCst)
    }
}

// ==========================================================
// TIPOS CORE DO DOMÍNIO
// ==========================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BufferId {
    Domain,
    Full,
}

#[derive(Debug, Clone, Copy, PartialEq, serde::Serialize)]
pub struct QplResult {
    pub node: usize,
    pub input: f64,
    pub output: f64,
}

fn serialize_signature<S>(sig: &[u8; 64], serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    use serde::ser::SerializeTuple;
    let mut seq = serializer.serialize_tuple(64)?;
    for e in sig.iter() {
        seq.serialize_element(e)?;
    }
    seq.end()
}

fn deserialize_signature<'de, D>(deserializer: D) -> Result<[u8; 64], D::Error>
where
    D: Deserializer<'de>,
{
    struct SigVisitor;

    impl<'de> serde::de::Visitor<'de> for SigVisitor {
        type Value = [u8; 64];

        fn expecting(&self, formatter: &mut std::fmt::Formatter) -> std::fmt::Result {
            formatter.write_str("an array of 64 bytes")
        }

        fn visit_seq<A>(self, mut seq: A) -> Result<[u8; 64], A::Error>
        where
            A: serde::de::SeqAccess<'de>,
        {
            let mut arr = [0u8; 64];
            for i in 0..64 {
                arr[i] = seq
                    .next_element()?
                    .ok_or_else(|| serde::de::Error::invalid_length(i, &self))?;
            }
            Ok(arr)
        }
    }

    deserializer.deserialize_tuple(64, SigVisitor)
}

#[repr(C)]
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AotbFrame {
    pub session_id: [u8; 16],
    pub sequence: u64,
    pub nonce: u64,
    pub proof_hash: [u8; 32],
    pub domain_values: [f64; DOMAIN_NODES],
    pub weights: [u8; DOMAIN_NODES],
    #[serde(
        serialize_with = "serialize_signature",
        deserialize_with = "deserialize_signature"
    )]
    pub signature: [u8; 64], // tamanho fixo para determinismo de layout
}

impl AotbFrame {
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(16 + 8 + 8 + 32 + 64 + 8);
        bytes.extend_from_slice(&self.session_id);
        bytes.extend_from_slice(&self.sequence.to_le_bytes());
        bytes.extend_from_slice(&self.nonce.to_le_bytes());
        bytes.extend_from_slice(&self.proof_hash);
        for value in &self.domain_values {
            // Canonical big-endian para evitar divergência f64 LE/BE
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.extend_from_slice(&self.weights);
        bytes
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VerifyError {
    BadSignature,
    Replay,
    Sentinel,
    SessionMismatch,
    SequenceMismatch,
    BadNonce,
}

pub fn hash_state(domain: &[f64; DOMAIN_NODES]) -> [u8; 32] {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    for value in domain {
        hasher.update(value.to_be_bytes());
    }
    hasher.finalize().into()
}

pub fn micros(cycles: u64, freq_mhz: u32) -> f64 {
    (cycles as f64) / (freq_mhz as f64)
}

pub mod aotb;
pub mod power;
pub mod qpl;
pub mod soc;
pub mod sram;
pub mod arkhe_fountain_encoder;
pub mod arkhe_fountain_decoder;
