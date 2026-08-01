// Arkhe_Fountain_Decoder.rs
// SPDX-License-Identifier: MIT
// Selo: ARKHE-FOUNTAIN-DECODER-v1.0-2026-08-01
//
// Decodificador Fountain (Luby Transform) com peeling decoder.
// Reconstrói estados OrchOR a partir de quadros recebidos em
// canais com alta taxa de perda.

use std::collections::{HashMap, HashSet, VecDeque};
use rand::{Rng, SeedableRng};
use rand::rngs::StdRng;
use crc32fast::Hasher as Crc32Hasher;

use crate::arkhe_fountain_encoder::{AFT_MAGIC, AFT_HEADER_SIZE, AFT_TRAILER_SIZE, OrchORState};

/// Quadro Fountain recebido
#[derive(Debug, Clone)]
pub struct FountainFrame {
    pub session_id: u32,
    pub seq_num: u32,
    pub k: usize,
    pub block_size: usize,
    pub degree: usize,
    pub seed: u32,
    pub payload: Vec<u8>,
}

impl FountainFrame {
    /// Parse de um quadro a partir de bytes brutos
    pub fn parse(data: &[u8]) -> Option<Self> {
        if data.len() < AFT_HEADER_SIZE + 6 + AFT_TRAILER_SIZE {
            return None;
        }

        let magic = u32::from_le_bytes(data[0..4].try_into().ok()?);
        if magic != AFT_MAGIC {
            return None;
        }

        // Verificar CRC-32
        let payload_end = data.len() - AFT_TRAILER_SIZE;
        let expected_crc = u32::from_le_bytes(data[payload_end..].try_into().ok()?);
        let mut crc_hasher = Crc32Hasher::new();
        crc_hasher.update(&data[..payload_end]);
        let computed_crc = crc_hasher.finalize();
        if computed_crc != expected_crc {
            return None;
        }

        let session_id = u32::from_le_bytes(data[4..8].try_into().ok()?);
        let seq_num = u32::from_le_bytes(data[8..12].try_into().ok()?);
        let k = u16::from_le_bytes(data[12..14].try_into().ok()?) as usize;
        let block_size = u16::from_le_bytes(data[14..16].try_into().ok()?) as usize;
        let payload_len = u32::from_le_bytes(data[16..20].try_into().ok()?) as usize;
        let degree = u16::from_le_bytes(data[20..22].try_into().ok()?) as usize;
        let seed = u32::from_le_bytes(data[22..26].try_into().ok()?);

        let payload = data[26..26+payload_len].to_vec();
        Some(FountainFrame { session_id, seq_num, k, block_size, degree, seed, payload })
    }

    /// Reconstrói os índices dos blocos fonte usados neste quadro
    pub fn source_indices(&self) -> Vec<usize> {
        let mut rng = StdRng::seed_from_u64(self.seed as u64);
        let mut selected = HashSet::with_capacity(self.degree);
        while selected.len() < self.degree {
            let idx = rng.gen_range(0..self.k);
            selected.insert(idx);
        }
        selected.into_iter().collect()
    }
}

/// Decodificador Fountain com peeling (belief propagation)
pub struct FountainDecoder {
    /// Blocos fonte resolvidos (índice → dados)
    pub decoded_blocks: HashMap<usize, Vec<u8>>,
    /// Quadros pendentes (ainda não resolvidos)
    pub pending_frames: Vec<FountainFrame>,
    /// Mapeamento: bloco resolvido → quadros que o contêm
    pub block_to_frames: HashMap<usize, Vec<usize>>,
    /// Session ID atual
    pub current_session: Option<u32>,
    /// K esperado
    pub expected_k: usize,
    /// Tamanho do bloco
    pub block_size: usize,
}

impl FountainDecoder {
    pub fn new() -> Self {
        Self {
            decoded_blocks: HashMap::new(),
            pending_frames: Vec::new(),
            block_to_frames: HashMap::new(),
            current_session: None,
            expected_k: 0,
            block_size: 0,
        }
    }

    /// Processa um novo quadro recebido
    pub fn receive_frame(&mut self, raw_data: &[u8]) -> Result<bool, &'static str> {
        let frame = match FountainFrame::parse(raw_data) {
            Some(f) => f,
            None => return Err("Invalid frame or CRC mismatch"),
        };

        // Verificar/resetar sessão
        match self.current_session {
            None => {
                self.current_session = Some(frame.session_id);
                self.expected_k = frame.k;
                self.block_size = frame.block_size;
            }
            Some(sid) if sid != frame.session_id => {
                // Nova sessão detectada — resetar
                self.decoded_blocks.clear();
                self.pending_frames.clear();
                self.block_to_frames.clear();
                self.current_session = Some(frame.session_id);
                self.expected_k = frame.k;
                self.block_size = frame.block_size;
            }
            _ => {}
        }

        // Se já temos todos os blocos, ignorar
        if self.is_complete() {
            return Ok(true);
        }

        // Obter índices dos blocos fonte
        let indices = frame.source_indices();

        // Verificar se algum bloco já está resolvido — reduzir degree
        let mut unresolved_indices = Vec::new();
        let mut resolved_xor = vec![0u8; frame.payload.len()];


        for &idx in &indices {
            if let Some(block) = self.decoded_blocks.get(&idx) {
                for (i, &byte) in block.iter().enumerate() {
                    resolved_xor[i] ^= byte;
                }

            } else {
                unresolved_indices.push(idx);
            }
        }

        let effective_degree = unresolved_indices.len();

        if effective_degree == 0 {
            // Quadro redundante — todos os blocos já conhecidos
            return Ok(self.is_complete());
        }

        // XOR do payload com blocos resolvidos
        let mut effective_payload = frame.payload.clone();
        for (i, byte) in effective_payload.iter_mut().enumerate() {
            *byte ^= resolved_xor[i];
        }

        if effective_degree == 1 {
            // Resolver o bloco restante!
            let resolved_idx = unresolved_indices[0];
            self.decoded_blocks.insert(resolved_idx, effective_payload.clone());

            // Propagar: reduzir degree de quadros pendentes que contêm este bloco
            let new_deg1 = self.propagate_resolution(resolved_idx, &effective_payload);

            // Tentar resolver em cascata
            self.peel_cascade(new_deg1);
        } else {
            // Armazenar quadro pendente
            let frame_idx = self.pending_frames.len();
            self.pending_frames.push(FountainFrame {
                session_id: frame.session_id,
                seq_num: frame.seq_num,
                k: frame.k,
                block_size: frame.block_size,
                degree: effective_degree,
                seed: frame.seed, // seed original, mas índices já filtrados
                payload: effective_payload,
            });

            // Mapear blocos não resolvidos → quadros pendentes
            for &idx in &unresolved_indices {
                self.block_to_frames.entry(idx).or_insert_with(Vec::new).push(frame_idx);
            }
        }

        Ok(self.is_complete())
    }

    /// Propaga a resolução de um bloco para quadros pendentes
    /// Retorna os índices dos quadros que acabaram de atingir degree = 1
    fn propagate_resolution(&mut self, resolved_idx: usize, resolved_data: &[u8]) -> Vec<usize> {
        let mut new_deg1 = Vec::new();
        if let Some(frame_indices) = self.block_to_frames.remove(&resolved_idx) {
            for &frame_idx in &frame_indices {
                if frame_idx >= self.pending_frames.len() {
                    continue;
                }
                let frame = &mut self.pending_frames[frame_idx];
                if frame.degree == 0 {
                    continue; // Already resolved
                }
                // Reduzir payload
                for (i, byte) in frame.payload.iter_mut().enumerate() {
                    if i < resolved_data.len() {
                        *byte ^= resolved_data[i];
                    }
                }
                frame.degree -= 1;
                if frame.degree == 1 {
                    new_deg1.push(frame_idx);
                }
            }
        }
        new_deg1
    }

    /// Executa peeling em cascata até não haver mais quadros de degree 1
    fn peel_cascade(&mut self, initial_queue: Vec<usize>) {
        let mut queue: VecDeque<usize> = VecDeque::from(initial_queue);

        while let Some(frame_idx) = queue.pop_front() {
            if frame_idx >= self.pending_frames.len() {
                continue;
            }
            let frame = &self.pending_frames[frame_idx];
            if frame.degree != 1 {
                continue;
            }

            // Reconstruir qual bloco restante
            let remaining_idx = self.find_remaining_block(frame_idx);
            if let Some(idx) = remaining_idx {
                if self.decoded_blocks.contains_key(&idx) {
                    continue;
                }
                let data = frame.payload.clone();
                self.decoded_blocks.insert(idx, data.clone());
                let new_deg1 = self.propagate_resolution(idx, &data);
                for new_idx in new_deg1 {
                    queue.push_back(new_idx);
                }
            }
        }
    }

    /// Encontra o único bloco não resolvido em um quadro de degree 1
    fn find_remaining_block(&self, frame_idx: usize) -> Option<usize> {
        let frame = &self.pending_frames[frame_idx];
        let indices = frame.source_indices();
        for &idx in &indices {
            if !self.decoded_blocks.contains_key(&idx) {
                return Some(idx);
            }
        }
        None
    }

    /// Verifica se a mensagem está completa
    pub fn is_complete(&self) -> bool {
        if self.expected_k == 0 {
            return false;
        }
        self.decoded_blocks.len() >= self.expected_k
    }

    /// Reconstrói os dados originais
    pub fn reconstruct(&self) -> Option<Vec<u8>> {
        if !self.is_complete() {
            return None;
        }

        let mut result = Vec::with_capacity(self.expected_k * self.block_size);
        for i in 0..self.expected_k {
            let block = self.decoded_blocks.get(&i)?;
            result.extend_from_slice(block);
        }
        Some(result)
    }

    /// Reconstrói um estado OrchOR
    pub fn reconstruct_orchor(&self) -> Option<OrchORState> {
        let data = self.reconstruct()?;
        OrchORState::from_bytes(&data)
    }

    /// Progresso da decodificação (0.0 a 1.0)
    pub fn progress(&self) -> f64 {
        if self.expected_k == 0 {
            return 0.0;
        }
        self.decoded_blocks.len() as f64 / self.expected_k as f64
    }
}

/// Simula um canal de perda (erasure channel)
pub struct ErasureChannel {
    pub loss_rate: f64,
}

impl ErasureChannel {
    pub fn new(loss_rate: f64) -> Self {
        Self { loss_rate: loss_rate.clamp(0.0, 1.0) }
    }

    /// Transmite um quadro; retorna None se perdido
    pub fn transmit<R: Rng>(&self, frame: &[u8], rng: &mut R) -> Option<Vec<u8>> {
        if rng.gen::<f64>() < self.loss_rate {
            None
        } else {
            Some(frame.to_vec())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rand::thread_rng;

    #[test]
    fn test_decoder_with_loss() {
        let data = b"Arkhe OrchOR Fountain Decoder Test \xe2\x80\x94 This message must survive 90% loss!";
        let mut encoder = crate::arkhe_fountain_encoder::FountainEncoder::new(data, 16, 0.03, 0.5);
        let channel = ErasureChannel::new(0.90); // 90% de perda
        let mut decoder = FountainDecoder::new();
        let mut rng = thread_rng();

        let mut transmitted = 0;
        let mut received = 0;

        for _ in 0..20000 {
            let frame = encoder.next_frame();
            transmitted += 1;
            if let Some(received_frame) = channel.transmit(&frame, &mut rng) {
                received += 1;
                if decoder.receive_frame(&received_frame).unwrap() {
                    break;
                }
            }
        }

        println!("Transmitted: {}, Received: {}, Progress: {:.1}%",
                 transmitted, received, decoder.progress() * 100.0);

        assert!(decoder.is_complete(), "Decoding failed! Progress: {:.1}%", decoder.progress() * 100.0);
        let reconstructed = decoder.reconstruct().unwrap();
        assert_eq!(&reconstructed[..data.len()], &data[..]);
    }
}
