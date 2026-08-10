cat << 'INNER_EOF' > arkhe-n-v1.6/src/accelerator.rs
use std::collections::HashSet;

pub type AgentId = String;

#[derive(Clone, Debug)]
pub struct Event {
    pub agent_id: AgentId,
    pub payload: String,
    pub latency_ms: f64,
}

pub struct SimulationAccelerator {
    pub active_agents: HashSet<AgentId>,
    pub dropout_threshold: usize,
    pub gasim_enabled: bool,
}

impl SimulationAccelerator {
    pub fn new(dropout_threshold: usize, gasim_enabled: bool) -> Self {
        Self {
            active_agents: HashSet::new(),
            dropout_threshold,
            gasim_enabled,
        }
    }

    pub fn process_batch(&mut self, events: Vec<Event>) -> Vec<Event> {
        let filtered = self.apply_dropout(events);
        if self.gasim_enabled {
            self.apply_graph_aggregation(filtered)
        } else {
            filtered
        }
    }

    fn apply_dropout(&mut self, events: Vec<Event>) -> Vec<Event> {
        events
    }

    fn apply_graph_aggregation(&mut self, events: Vec<Event>) -> Vec<Event> {
        events
    }
}
INNER_EOF

cat << 'INNER_EOF' > arkhe-n-v1.6/src/validation.rs
use crate::channel::PoissonChannel;

pub struct ValidationResult {
    pub valid: bool,
    pub error_percent: f64,
    pub observed: f64,
    pub expected: f64,
}

pub struct EmpiricalValidator {
    pub observed_rate: f64,
    pub expected_rate: f64,
    pub tolerance: f64,
}

impl EmpiricalValidator {
    pub fn new(observed_rate: f64, expected_rate: f64, tolerance: f64) -> Self {
        Self {
            observed_rate,
            expected_rate,
            tolerance,
        }
    }

    pub fn validate_cevns(&self, channel: &PoissonChannel) -> ValidationResult {
        let expected = channel.event_rate_per_year / 365.0 / channel.detector_mass_kg;
        let error = (expected - self.observed_rate).abs() / self.observed_rate;
        ValidationResult {
            valid: error < self.tolerance,
            error_percent: error * 100.0,
            observed: self.observed_rate,
            expected,
        }
    }
}
INNER_EOF

cat << 'INNER_EOF' > arkhe-n-v1.6/src/telemetry.rs
use crate::accelerator::Event;
use crate::transmission_log::NeutrinoProof;

pub struct Telemetry {
    pub events_processed: u64,
    pub total_latency_ms: f64,
    pub total_energy_mj: f64,
    pub pq_signature_time_ms: f64,
}

impl Telemetry {
    pub fn new() -> Self {
        Self {
            events_processed: 0,
            total_latency_ms: 0.0,
            total_energy_mj: 0.0,
            pq_signature_time_ms: 0.0,
        }
    }

    pub fn record(&mut self, event: &Event, proof: &NeutrinoProof) {
        self.events_processed += 1;
        self.total_latency_ms += event.latency_ms;
        self.total_energy_mj += proof.energy_used_j / 1e6;
    }

    pub fn report(&self) -> String {
        format!(
            "Eventos: {} | Latência média: {:.2} ms | Energia: {:.3} MJ",
            self.events_processed,
            if self.events_processed > 0 { self.total_latency_ms / self.events_processed as f64 } else { 0.0 },
            self.total_energy_mj,
        )
    }
}
INNER_EOF
