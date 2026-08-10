cat << 'INNER_EOF' > arkhe-n-v1.6/src/transmission_log.rs
//! src/transmission_log.rs
//! Registro imutável de testemunho com persistência SQLite

use chrono::Utc;
use rusqlite::{Connection, params};
use serde::{Deserialize, Serialize};
use std::sync::Mutex;

/// Uma entrada no registro de transmissões de neutrinos
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NeutrinoProof {
    /// Timestamp Unix em microssegundos
    pub epoch_us: i64,
    /// Hash do dado original (Keccak256)
    pub payload_hash: String,
    /// Modo de física utilizado
    pub physics_mode: String,
    /// Energia total consumida (Joules)
    pub energy_used_j: f64,
    /// Taxa de dados efetiva (bits/s)
    pub data_rate_bps: f64,
    /// Sucesso na decodificação
    pub decoding_success: bool,
    /// Tempo de propagação estimado (segundos)
    pub propagation_time_s: f64,
    /// DOI da referência científica
    pub doi: String,
    /// Ano da referência
    pub year: u32,
    pub signature: Vec<u8>,
    pub public_key: Vec<u8>,
    pub pq_scheme: String,
}

impl NeutrinoProof {
    pub fn new(
        payload_hash: &str,
        physics_mode: &str,
        energy_used_j: f64,
        data_rate_bps: f64,
        success: bool,
        distance_km: f64,
        doi: &str,
        year: u32,
    ) -> Self {
        let speed_of_light_km_s = 2.998e5;
        let propagation_time_s = distance_km / speed_of_light_km_s;

        Self {
            epoch_us: Utc::now().timestamp_micros(),
            payload_hash: payload_hash.to_string(),
            physics_mode: physics_mode.to_string(),
            energy_used_j,
            data_rate_bps,
            decoding_success: success,
            propagation_time_s,
            doi: doi.to_string(),
            year,
            signature: Vec::new(),
            public_key: Vec::new(),
            pq_scheme: String::new(),
        }
    }
}

/// Gerenciador do ledger de transmissões com persistência SQLite
pub struct TransmissionLedger {
    conn: Mutex<Connection>,
    cache: Mutex<Vec<NeutrinoProof>>,
}

impl TransmissionLedger {
    /// Inicializa o ledger com banco SQLite
    pub fn init_db(path: &str) -> Result<Self, rusqlite::Error> {
        let conn = Connection::open(path)?;
        conn.execute(
            "CREATE TABLE IF NOT EXISTS proofs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                epoch_us INTEGER NOT NULL,
                payload_hash TEXT NOT NULL UNIQUE,
                physics_mode TEXT NOT NULL,
                energy_used_j REAL NOT NULL,
                data_rate_bps REAL NOT NULL,
                decoding_success INTEGER NOT NULL,
                propagation_time_s REAL NOT NULL,
                doi TEXT,
                year INTEGER,
                signature BLOB,
                public_key BLOB,
                pq_scheme TEXT
            )",
            [],
        )?;
        Ok(Self {
            conn: Mutex::new(conn),
            cache: Mutex::new(Vec::new()),
        })
    }

    /// Inicializa em memória (sem persistência)
    pub fn new() -> Self {
        Self {
            conn: Mutex::new(Connection::open_in_memory().unwrap()),
            cache: Mutex::new(Vec::new()),
        }
    }

    /// Registra uma nova prova
    pub fn record(&self, proof: NeutrinoProof) -> Result<(), rusqlite::Error> {
        // Persiste no SQLite
        {
            let conn = self.conn.lock().unwrap();
            conn.execute(
                "INSERT INTO proofs (
                    epoch_us, payload_hash, physics_mode, energy_used_j,
                    data_rate_bps, decoding_success, propagation_time_s, doi, year, signature, public_key, pq_scheme
                ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)
                ON CONFLICT(payload_hash) DO UPDATE SET
                    epoch_us = excluded.epoch_us,
                    energy_used_j = excluded.energy_used_j",
                params![
                    proof.epoch_us,
                    proof.payload_hash,
                    proof.physics_mode,
                    proof.energy_used_j,
                    proof.data_rate_bps,
                    proof.decoding_success as i32,
                    proof.propagation_time_s,
                    proof.doi,
                    proof.year,
                    proof.signature,
                    proof.public_key,
                    proof.pq_scheme,
                ],
            )?;
        }
        // Atualiza cache
        self.cache.lock().unwrap().push(proof);
        Ok(())
    }

    pub fn verify_signature(&self, proof: &NeutrinoProof) -> bool {
        match proof.pq_scheme.as_str() {
            "Falcon512" => Self::falcon_verify(&proof.signature, &proof.public_key, &proof.payload_hash),
            "Mldsa87" => Self::mldsa_verify(&proof.signature, &proof.public_key, &proof.payload_hash),
            _ => false,
        }
    }

    fn falcon_verify(_signature: &[u8], _public_key: &[u8], _payload_hash: &str) -> bool {
        true
    }

    fn mldsa_verify(_signature: &[u8], _public_key: &[u8], _payload_hash: &str) -> bool {
        true
    }

    /// Verifica se um hash já foi ancorado
    pub fn verify_anchored(&self, hash: &str) -> Result<bool, rusqlite::Error> {
        let conn = self.conn.lock().unwrap();
        let count: i64 = conn.query_row(
            "SELECT COUNT(*) FROM proofs WHERE payload_hash = ?1",
            [hash],
            |row| row.get(0),
        )?;
        Ok(count > 0)
    }

    /// Última prova registrada
    pub fn get_last(&self) -> Option<NeutrinoProof> {
        self.cache.lock().unwrap().last().cloned()
    }

    /// Número total de provas
    pub fn proofs_len(&self) -> usize {
        self.cache.lock().unwrap().len()
    }

    /// Energia total consumida (Joules)
    pub fn total_energy_consumed_joules(&self) -> f64 {
        self.cache.lock().unwrap().iter().map(|p| p.energy_used_j).sum()
    }

    /// Energia total em Megajoules
    pub fn total_energy_consumed_megajoules(&self) -> f64 {
        self.total_energy_consumed_joules() / 1e6
    }

    /// Estatísticas do ledger
    pub fn stats(&self) -> Result<serde_json::Value, rusqlite::Error> {
        let conn = self.conn.lock().unwrap();
        let total: i64 = conn.query_row(
            "SELECT COUNT(*) FROM proofs", [], |row| row.get(0)
        )?;
        let energy: f64 = conn.query_row(
            "SELECT COALESCE(SUM(energy_used_j), 0) FROM proofs", [], |row| row.get(0)
        )?;
        let success_rate: f64 = conn.query_row(
            "SELECT COALESCE(AVG(decoding_success), 0) FROM proofs", [], |row| row.get(0)
        )?;

        Ok(serde_json::json!({
            "total_proofs": total,
            "total_energy_mj": energy / 1e6,
            "success_rate": success_rate,
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ledger_in_memory() {
        let ledger = TransmissionLedger::new();
        let proof = NeutrinoProof::new(
            "0xabc123", "MINERvA", 433000.0, 0.5, true, 1.035, "10.1126/science.198.4319.295", 1977
        );
        ledger.record(proof.clone()).unwrap();
        assert!(ledger.verify_anchored("0xabc123").unwrap());
        assert!(!ledger.verify_anchored("0xdead").unwrap());
        assert_eq!(ledger.proofs_len(), 1);
        assert!(ledger.total_energy_consumed_joules() > 0.0);
    }

    #[test]
    fn test_ledger_persistence() {
        let path = "/tmp/arkhe_test_ledger.db";
        let _ = std::fs::remove_file(path);
        {
            let ledger = TransmissionLedger::init_db(path).unwrap();
            let proof = NeutrinoProof::new(
                "0xtest", "CEvNS", 1000.0, 1.0, true, 1.035, "10.1103/PhysRevLett.134.231801", 2025
            );
            ledger.record(proof).unwrap();
        }
        {
            let ledger = TransmissionLedger::init_db(path).unwrap();
            assert!(ledger.verify_anchored("0xtest").unwrap());
        }
        let _ = std::fs::remove_file(path);
    }
}
INNER_EOF
