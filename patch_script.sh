sed -i 's/let original = b"Hello, ARKHE-N! 🚀";/let original = b"Hello, ARKHE-N! \xF0\x9F\x9A\x80";/' arkhe-n-v1.4/src/modulation.rs
sed -i 's/let bg_rate = 1e-3;/let bg_rate: f64 = 1e-3;/' arkhe-n-v1.4/src/seti.rs
sed -i 's/pub struct NeutrinoProof {/#[derive(Deserialize)]\npub struct NeutrinoProof {/' arkhe-n-v1.4/src/transmission_log.rs
sed -i 's/use serde::Serialize;/use serde::{Deserialize, Serialize};/' arkhe-n-v1.4/src/transmission_log.rs
sed -i 's/use crate::main::{handle_transmission, WsRequest};//' arkhe-n-v1.4/src/api.rs
