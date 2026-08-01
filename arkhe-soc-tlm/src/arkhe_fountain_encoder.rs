// Arkhe_Fountain_Encoder.rs
// SPDX-License-Identifier: MIT
// Selo: ARKHE-FOUNTAIN-ENCODER-v1.0-2026-08-01
//
// Codificador Fountain (Luby Transform) para transmissão de estados
// OrchOR em canais com alta taxa de perda (interestelar).
//
// Baseado em: bashalarmistalt/decimen-optical-transfer
// Adaptado para: pulsos THz / radio X-band / laser óptico

use rand::{Rng, SeedableRng};
use rand::rngs::StdRng;
use crc32fast::Hasher as Crc32Hasher;

/// Tamanho do header AFT (bytes)
pub const AFT_HEADER_SIZE: usize = 20;
/// Tamanho do trailer CRC (bytes)
pub const AFT_TRAILER_SIZE: usize = 4;
/// Magic number: "ARTH" em ASCII
pub const AFT_MAGIC: u32 = 0x41525448;

/// Estado de consciência OrchOR serializável
#[derive(Debug, Clone)]
pub struct OrchORState {
    /// Timestamp em nanosegundos desde epoch
    pub timestamp: u64,
    /// Tempo de coerência t (segundos)
    pub coherence_time: f64,
    /// Frequência f = 1/t (Hz)
    pub frequency: f64,
    /// Energia E = h/t (joules)
    pub energy: f64,
    /// Estado do hexágono: 6 vértices × 2 canais (I, Q) em Q1.15
    pub hexagon_state: [u16; 12],
    /// Regime de frequência: 0=Hz, 1=kHz, 2=MHz, 3=GHz, 4=THz
    pub regime: u8,
}

impl OrchORState {
    /// Serializa o estado em bytes (little-endian)
    pub fn to_bytes(&self) -> Vec<u8> {
        let mut buf = Vec::with_capacity(128);
        buf.extend_from_slice(&self.timestamp.to_le_bytes());
        buf.extend_from_slice(&self.coherence_time.to_le_bytes());
        buf.extend_from_slice(&self.frequency.to_le_bytes());
        buf.extend_from_slice(&self.energy.to_le_bytes());
        for &v in &self.hexagon_state {
            buf.extend_from_slice(&v.to_le_bytes());
        }
        buf.push(self.regime);
        buf
    }

    /// Deserializa a partir de bytes
    pub fn from_bytes(bytes: &[u8]) -> Option<Self> {
        if bytes.len() < 57 {
            return None;
        }
        let mut offset = 0;
        let timestamp = u64::from_le_bytes(bytes[offset..offset+8].try_into().ok()?);
        offset += 8;
        let coherence_time = f64::from_le_bytes(bytes[offset..offset+8].try_into().ok()?);
        offset += 8;
        let frequency = f64::from_le_bytes(bytes[offset..offset+8].try_into().ok()?);
        offset += 8;
        let energy = f64::from_le_bytes(bytes[offset..offset+8].try_into().ok()?);
        offset += 8;
        let mut hexagon_state = [0u16; 12];
        for i in 0..12 {
            hexagon_state[i] = u16::from_le_bytes(bytes[offset..offset+2].try_into().ok()?);
            offset += 2;
        }
        let regime = bytes[offset];
        Some(OrchORState {
            timestamp, coherence_time, frequency, energy, hexagon_state, regime,
        })
    }
}

/// Distribuição robust-soliton para grau d
pub struct RobustSoliton {
    /// Número de blocos fonte
    pub k: usize,
    /// Parâmetro de robustez c
    pub c: f64,
    /// Probabilidade de falha δ
    pub delta: f64,
    /// Distribuição acumulada (para amostragem por inversão)
    cdf: Vec<f64>,
}

impl RobustSoliton {
    pub fn new(k: usize, c: f64, delta: f64) -> Self {
        let r = (c * (k as f64) / (k as f64).ln()).ceil() as usize;
        let mut rho = vec![0.0; k + 1];
        let mut tau = vec![0.0; k + 1];

        // Distribuição ideal ρ(d)
        rho[1] = 1.0 / (k as f64);
        for d in 2..=k {
            rho[d] = 1.0 / ((d * (d - 1)) as f64);
        }

        // Componente robusta τ(d)
        for d in 1..=(k / r).saturating_sub(1) {
            tau[d] = 1.0 / ((d * r) as f64);
        }
        if k >= r {
            tau[k / r] = (r as f64) * (k as f64).ln() / (k as f64);
        }

        // Normalização
        let z: f64 = (1..=k).map(|d| rho[d] + tau[d]).sum();
        let mut cdf = vec![0.0; k + 1];
        let mut acc = 0.0;
        for d in 1..=k {
            acc += (rho[d] + tau[d]) / z;
            cdf[d] = acc;
        }
        cdf[k] = 1.0; // garantir

        Self { k, c, delta, cdf }
    }

    /// Amostra um grau d da distribuição
    pub fn sample<R: Rng>(&self, rng: &mut R) -> usize {
        let u: f64 = rng.gen();
        // Busca binária na CDF
        let mut lo = 1usize;
        let mut hi = self.k;
        while lo < hi {
            let mid = (lo + hi) / 2;
            if self.cdf[mid] < u {
                lo = mid + 1;
            } else {
                hi = mid;
            }
        }
        lo
    }
}

/// Codificador Fountain AFT
pub struct FountainEncoder {
    /// Blocos fonte (K blocos de B bytes)
    pub blocks: Vec<Vec<u8>>,
    /// Número de blocos fonte
    pub k: usize,
    /// Tamanho de cada bloco
    pub block_size: usize,
    /// Distribuição soliton
    pub soliton: RobustSoliton,
    /// Session ID
    pub session_id: u32,
    /// Contador de sequência
    pub seq_num: u32,
    /// PRNG para seleção de blocos
    pub rng: StdRng,
}

impl FountainEncoder {
    pub fn new(data: &[u8], block_size: usize, c: f64, delta: f64) -> Self {
        let k = (data.len() + block_size - 1) / block_size;
        let mut blocks = Vec::with_capacity(k);
        for i in 0..k {
            let start = i * block_size;
            let end = (start + block_size).min(data.len());
            let mut block = data[start..end].to_vec();
            block.resize(block_size, 0); // padding
            blocks.push(block);
        }

        let soliton = RobustSoliton::new(k, c, delta);
        let session_id = rand::thread_rng().gen();
        let rng = StdRng::from_entropy();

        Self { blocks, k, block_size, soliton, session_id, seq_num: 0, rng }
    }

    /// Gera o próximo quadro Fountain
    pub fn next_frame(&mut self) -> Vec<u8> {
        let d = self.soliton.sample(&mut self.rng);
        let seed = self.seq_num.wrapping_mul(0x9E3779B9);
        let mut block_rng = StdRng::seed_from_u64(seed as u64);

        // Selecionar d blocos distintos
        let mut selected = Vec::with_capacity(d);
        while selected.len() < d {
            let idx = block_rng.gen_range(0..self.k);
            if !selected.contains(&idx) {
                selected.push(idx);
            }
        }

        // XOR dos blocos selecionados
        let mut payload = vec![0u8; self.block_size];
        for &idx in &selected {
            for (i, byte) in self.blocks[idx].iter().enumerate() {
                payload[i] ^= byte;
            }
        }

        // Montar quadro
        let mut frame = Vec::with_capacity(AFT_HEADER_SIZE + 6 + payload.len() + AFT_TRAILER_SIZE);
        frame.extend_from_slice(&AFT_MAGIC.to_le_bytes());
        frame.extend_from_slice(&self.session_id.to_le_bytes());
        frame.extend_from_slice(&self.seq_num.to_le_bytes());
        frame.extend_from_slice(&(self.k as u16).to_le_bytes());
        frame.extend_from_slice(&(self.block_size as u16).to_le_bytes());
        frame.extend_from_slice(&(payload.len() as u32).to_le_bytes());
        frame.extend_from_slice(&(d as u16).to_le_bytes());
        frame.extend_from_slice(&seed.to_le_bytes());
        frame.extend_from_slice(&payload);

        // CRC-32
        let mut crc_hasher = Crc32Hasher::new();
        crc_hasher.update(&frame);
        let crc = crc_hasher.finalize();
        frame.extend_from_slice(&crc.to_le_bytes());

        self.seq_num = self.seq_num.wrapping_add(1);
        frame
    }

    /// Gera N quadros de uma vez
    pub fn generate_frames(&mut self, n: usize) -> Vec<Vec<u8>> {
        (0..n).map(|_| self.next_frame()).collect()
    }
}

/// Codifica um estado OrchOR em um fluxo Fountain
pub fn encode_orchor_state(state: &OrchORState, block_size: usize) -> FountainEncoder {
    let data = state.to_bytes();
    FountainEncoder::new(&data, block_size, 0.03, 0.5)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_orchor_roundtrip() {
        let state = OrchORState {
            timestamp: 1722470400000000000,
            coherence_time: 8.33e-13, // ~1.2 THz
            frequency: 1.2e12,
            energy: 7.95e-22, // h·f
            hexagon_state: [16384; 12], // 0.5 em Q1.15 para todos
            regime: 4, // THz
        };

        let bytes = state.to_bytes();
        let decoded = OrchORState::from_bytes(&bytes).unwrap();
        assert_eq!(state.timestamp, decoded.timestamp);
        assert_eq!(state.frequency, decoded.frequency);
        assert_eq!(state.regime, decoded.regime);
    }

    #[test]
    fn test_fountain_encoding() {
        let data = b"Arkhe OrchOR Fountain Test Message";
        let mut encoder = FountainEncoder::new(data, 8, 0.03, 0.5);
        let frame = encoder.next_frame();
        assert!(frame.len() > AFT_HEADER_SIZE + AFT_TRAILER_SIZE);
        assert_eq!(&frame[0..4], &AFT_MAGIC.to_le_bytes());
    }
}
