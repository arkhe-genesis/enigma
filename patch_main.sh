cat << 'INNER_EOF' > arkhe-n-v1.6/src/main.rs
//! src/main.rs
//! ARKHE-N Server v1.6 — WebSocket (porta 8765) + REST API (porta 8080)
//! Integra: Canal Poisson, M-PPM, LDPC, CRC-32, QKD, SETI, SQLite Ledger

use futures::{SinkExt, StreamExt};
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;
use tokio::net::TcpListener;
use tokio::sync::broadcast;
use tokio_tungstenite::accept_async;
use tokio_tungstenite::tungstenite::Message;
use serde::{Deserialize, Serialize};
use rand::SeedableRng;
use rand::rngs::StdRng;
use sha3::{Keccak256, Digest};

pub mod channel;
pub mod modulation;
pub mod coding;
pub mod transmission_log;
pub mod api;
pub mod qkd;
pub mod seti;
pub mod accelerator;
pub mod validation;
pub mod telemetry;

use channel::{PoissonChannel, CosmoState, ChannelMode};
use modulation::{PpmModem, PpmSymbol};
use coding::{LdpcCodec, CrcPacket, MonteCarloSimulator};
use transmission_log::{TransmissionLedger, NeutrinoProof};
use api::AppState;
use telemetry::Telemetry;
use accelerator::SimulationAccelerator;

/// Energia por pulso do feixe NuMI (Joules)
pub const ENERGY_PER_PULSE_J: f64 = 4.33e5;

/// Estado global compartilhado
pub struct ServerState {
    pub active_channel: PoissonChannel,
    pub ldpc_codec: LdpcCodec,
    pub ledger: TransmissionLedger,
    pub rng: StdRng,
    pub telemetry: Telemetry,
    pub accelerator: SimulationAccelerator,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct WsRequest {
    pub action: String,
    pub payload: Option<String>,
    pub physics_mode: Option<String>,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct WsResponse {
    pub status: String,
    pub physics_context: String,
    pub proof: Option<NeutrinoProof>,
    pub error: Option<String>,
}

/// Gera hash Keccak256
pub fn keccak256_hash(input: &[u8]) -> String {
    let mut hasher = Keccak256::new();
    hasher.update(input);
    format!("0x{:x}", hasher.finalize())
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("🚀 ARKHE-N Server v1.6");
    println!("   WebSocket: ws://0.0.0.0:8765");
    println!("   REST API:  http://0.0.0.0:8080");
    println!("   Modos: MINERvA | CEvNS | Saenz | COH-Ar-750 | KM3NeT | Cooled-Muon-Beam");

    // Inicializa estado compartilhado
    let ledger = TransmissionLedger::init_db("arkhe_ledger.db")?;
    let server_state = Arc::new(tokio::sync::Mutex::new(ServerState {
        active_channel: PoissonChannel::minerva_default(),
        ldpc_codec: LdpcCodec::new_4ppm_optimized(),
        ledger,
        rng: StdRng::seed_from_u64(42),
        telemetry: Telemetry::new(),
        accelerator: SimulationAccelerator::new(5, true),
    }));

    // Estado para API REST
    let app_state = AppState {
        ledger: Arc::new(tokio::sync::Mutex::new(
            TransmissionLedger::init_db("arkhe_ledger.db")?
        )),
        channel: Arc::new(tokio::sync::Mutex::new(PoissonChannel::minerva_default())),
    };

    // Canal broadcast para WebSocket
    let (tx, _rx) = broadcast::channel::<Arc<Vec<u8>>>(16);

    // ========== TASK 1: Gerador de dados cosmológicos ==========
    let tx_gen = tx.clone();
    let state_gen = Arc::clone(&server_state);
    tokio::spawn(async move {
        let mut epoch: u64 = 0;
        let mut interval = tokio::time::interval(Duration::from_millis(100));

        loop {
            interval.tick().await;
            epoch += 1;

            let mut state = state_gen.lock().await;
            let mut rng = StdRng::seed_from_u64(epoch);
            let mut state_cosmo = state.active_channel.to_cosmo_state(epoch, &mut rng);

            // Adiciona CRC ao estado
            let state_json = serde_json::to_vec(&state_cosmo).unwrap();
            state_cosmo.crc32 = PoissonChannel::compute_crc32(&state_json);
            drop(state);

            let payload = match rmp_serde::to_vec(&state_cosmo) {
                Ok(v) => v,
                Err(e) => { eprintln!("❌ Serialize error: {}", e); continue; }
            };

            let _ = tx_gen.send(Arc::new(payload));

            if epoch % 100 == 0 {
                let state = state_gen.lock().await;
                println!("📡 Epoch {} | λ={:.2} | err_π={:.2e} | phase={} | explore={:.3} | mode={}",
                    epoch, state_cosmo.lambda, state_cosmo.error_pi,
                    state_cosmo.phase, state_cosmo.exploration,
                    state.active_channel.historical_context());
            }
        }
    });

    // ========== TASK 2: Servidor WebSocket (porta 8765) ==========
    let ws_state = Arc::clone(&server_state);
    let ws_tx = tx.clone();
    tokio::spawn(async move {
        let addr: SocketAddr = "0.0.0.0:8765".parse().unwrap();
        let listener = TcpListener::bind(&addr).await.unwrap();
        println!("✅ WebSocket ouvindo em ws://{}", addr);

        loop {
            let (stream, peer_addr) = listener.accept().await.unwrap();
            let rx = ws_tx.subscribe();
            let state_conn = Arc::clone(&ws_state);

            tokio::spawn(async move {
                let ws_stream = match accept_async(stream).await {
                    Ok(ws) => ws,
                    Err(e) => { eprintln!("❌ WebSocket handshake failed: {}", e); return; }
                };

                let (mut write, mut read) = ws_stream.split();

                // Task de envio (broadcast)
                let mut rx = rx;
                let send_task = tokio::spawn(async move {
                    loop {
                        match rx.recv().await {
                            Ok(payload) => {
                                if write.send(Message::Binary(payload.to_vec())).await.is_err() {
                                    break;
                                }
                            }
                            Err(_) => break,
                        }
                    }
                });

                // Task de recebimento (comandos)
                let recv_task = tokio::spawn(async move {
                    while let Some(msg) = read.next().await {
                        match msg {
                            Ok(Message::Text(text)) => {
                                println!("📥 [{}] Comando: {}", peer_addr, text);
                                if let Ok(cmd) = serde_json::from_str::<WsRequest>(&text) {
                                    if cmd.action == "SET_MODE" {
                                        if let Some(mode) = cmd.physics_mode {
                                            let mut state = state_conn.lock().await;
                                            state.active_channel = match mode.as_str() {
                                                "cevns" => PoissonChannel::cevns_default(),
                                                "saenz" => PoissonChannel::saenz_proposal(),
                                                "coh_ar750" => PoissonChannel::coh_ar750(),
                                                "km3net" => PoissonChannel::km3net(),
                                                "cooled_muon" => PoissonChannel::cooled_muon_beam(),
                                                _ => PoissonChannel::minerva_default(),
                                            };
                                            println!("🔄 Modo alterado: {}", state.active_channel.historical_context());
                                        }
                                    }
                                }
                            }
                            Ok(Message::Close(_)) => break,
                            Ok(_) => {}
                            Err(e) => { eprintln!("❌ WebSocket error: {}", e); break; }
                        }
                    }
                });

                tokio::select! {
                    _ = send_task => {},
                    _ = recv_task => {},
                }
                println!("🔌 Cliente desconectado: {}", peer_addr);
            });
        }
    });

    // ========== TASK 3: Servidor REST API (porta 8080) ==========
    let rest_state = app_state;
    tokio::spawn(async move {
        let addr: SocketAddr = "0.0.0.0:8080".parse().unwrap();
        let app = api::create_router(rest_state);
        let listener = TcpListener::bind(&addr).await.unwrap();
        println!("✅ REST API ouvindo em http://{}", addr);

        axum::serve(listener, app).await.unwrap();
    });

    // Mantém o main vivo
    println!("🌌 ARKHE-N v1.6 operacional. Pressione Ctrl+C para encerrar.");
    tokio::signal::ctrl_c().await?;
    println!("\n👋 Encerrando ARKHE-N...");

    Ok(())
}

/// Lógica de transmissão de prova (usada por endpoints futuros)
pub fn handle_transmission(
    req: &WsRequest,
    hw: &mut ServerState,
) -> WsResponse {
    match req.action.as_str() {
        "TRANSMIT_PROOF" => {
            let message = req.payload.as_deref().unwrap_or("");

            // 1. Hash do testemunho
            let payload_hash = keccak256_hash(message.as_bytes());

            // 2. CRC do payload
            let crc_packet = CrcPacket::new(message.as_bytes().to_vec());
            if !crc_packet.verify() {
                return WsResponse {
                    status: "ERROR".into(),
                    physics_context: String::new(),
                    proof: None,
                    error: Some("CRC verification failed".into()),
                };
            }

            // 3. Codificação FEC
            let encoded_bytes = hw.ldpc_codec.encode(&crc_packet.into_payload());

            // 4. Modulação M-PPM (respeita slots, não bits soltos)
            let (_symbols, total_bits, bits_success, total_energy_j, soft_llr_stream) =
                match hw.active_channel.modulation {
                    channel::ModulationScheme::Ook => {
                        // OOK: transmite bits serializados
                        let mut bits_success = 0usize;
                        let mut total_energy = 0.0;
                        let mut llrs = Vec::new();
                        let total_bits = encoded_bytes.len() * 8;

                        for &byte in &encoded_bytes {
                            for i in 0..8 {
                                let bit = (byte >> i) & 1 == 1;
                                total_energy += ENERGY_PER_PULSE_J;
                                let (det, conf) = hw.active_channel.transmit_bit(bit, &mut hw.rng);
                                let llr = if det {
                                    10.0 * conf
                                } else {
                                    -10.0 * (1.0 - conf)
                                };
                                llrs.push(llr);
                                if det == bit { bits_success += 1; }
                            }
                        }
                        (Vec::new(), total_bits, bits_success, total_energy, llrs)
                    }
                    channel::ModulationScheme::Ppm { slots } => {
                        let m = slots;
                        let modem = PpmModem::new(m).unwrap();
                        let symbols = modem.encode(&encoded_bytes);
                        let mut bits_success = 0usize;
                        let mut total_energy = 0.0;
                        let mut all_llrs = Vec::new();
                        let total_bits = symbols.len() * (m as f64).log2() as usize;

                        for sym in &symbols {
                            total_energy += ENERGY_PER_PULSE_J;
                            let (detected, llrs) = hw.active_channel.transmit_ppm_symbol(
                                sym.slot, m as usize, &mut hw.rng
                            );
                            all_llrs.extend(llrs);
                            if detected == sym.slot { bits_success += 1; }
                        }
                        (symbols, total_bits, bits_success, total_energy, all_llrs)
                    }
                };

            // 5. Decodificação LDPC
            let (_decoded_bytes, syndrome_ok) = hw.ldpc_codec.decode(&soft_llr_stream);
            let final_success = syndrome_ok && (bits_success as f64 / total_bits.max(1) as f64) > 0.8;

            // 6. Taxa de dados
            let data_rate = hw.active_channel.capacity_with_background()
                * (1.0 / hw.active_channel.pulse_period_sec);

            // 7. Registro de testemunho
            let doi = match hw.active_channel.mode {
                ChannelMode::Minerva => "10.1126/science.198.4319.295",
                ChannelMode::Cevns => "10.1103/PhysRevLett.134.231801",
                ChannelMode::Saenz => "10.1126/science.198.4319.295",
                ChannelMode::CohAr750 => "10.1103/PhysRevLett.2026.COHAr750",
                ChannelMode::Km3Net => "10.1103/PhysRevLett.2026.KM3NeT",
                ChannelMode::CooledMuonBeam => "10.1103/PhysRevLett.2026.MuonBeam",
            };

            let year = match hw.active_channel.mode {
                ChannelMode::Minerva => 2012,
                ChannelMode::Cevns => 2017,
                ChannelMode::Saenz => 1977,
                _ => 2026,
            };

            let proof = NeutrinoProof::new(
                &payload_hash,
                &hw.active_channel.historical_context(),
                total_energy_j,
                data_rate,
                final_success,
                1.035, // distância MINERvA em km
                doi,
                year,
            );

            if let Err(e) = hw.ledger.record(proof.clone()) {
                eprintln!("❌ Erro ao registrar no ledger: {}", e);
            }

            WsResponse {
                status: if final_success { "ANCHORED" } else { "DEGRADED" }.into(),
                physics_context: hw.active_channel.historical_context(),
                proof: Some(proof),
                error: if final_success { None } else { Some("Falha na decodificação LDPC ou perda Poisson excessiva".into()) },
            }
        }

        "GET_LEDGER_STATS" => {
            let total_energy_mj = hw.ledger.total_energy_consumed_megajoules();
            let stats = format!(
                "Transmissões: {} | Energia Total: {:.3} MJ | Modo: {}",
                hw.ledger.proofs_len(),
                total_energy_mj,
                hw.active_channel.historical_context()
            );
            WsResponse {
                status: "OK".into(),
                physics_context: stats,
                proof: hw.ledger.get_last(),
                error: None,
            }
        }

        "RUN_MONTE_CARLO" => {
            let result = MonteCarloSimulator::run_ber(
                &hw.active_channel.historical_context(),
                10000,
                ENERGY_PER_PULSE_J,
                |bit| {
                    let (det, _conf) = hw.active_channel.transmit_bit(bit, &mut hw.rng);
                    (det, det == bit)
                },
            );
            let stats = format!(
                "Monte Carlo | BER={:.4e} | FER={:.4e} | Cap={:.4} | CI95=[{:.4e}, {:.4e}]",
                result.ber, result.fer, result.capacity_estimated,
                result.confidence_interval_95.0, result.confidence_interval_95.1
            );
            WsResponse {
                status: "OK".into(),
                physics_context: stats,
                proof: None,
                error: None,
            }
        }

        _ => WsResponse {
            status: "ERROR".into(),
            physics_context: String::new(),
            proof: None,
            error: Some("Ação inválida. Use TRANSMIT_PROOF, SET_MODE, GET_LEDGER_STATS, ou RUN_MONTE_CARLO.".into()),
        }
    }
}
INNER_EOF
