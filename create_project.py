import os

base_dir = "./arkhe-n-v1.4"
os.makedirs(f"{base_dir}/src", exist_ok=True)

cargo_toml = """[package]
name = "arkhe-server"
version = "1.4.0"
edition = "2021"
authors = ["ARKHE <arkhe@example.com>"]
description = "ARKHE-N v1.4 — Servidor WebSocket + REST + Canal Poisson + QKD + SETI"

[dependencies]
tokio = { version = "1.40", features = ["full"] }
tokio-tungstenite = "0.24"
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
rmp-serde = "1.3"
futures = "0.3"
rand = { version = "0.8", features = ["std_rng"] }
chrono = { version = "0.4", features = ["serde"] }
sha3 = "0.10"
axum = "0.7"
tower-http = { version = "0.5", features = ["cors"] }
tower = "0.4"
rusqlite = { version = "0.32", features = ["bundled", "chrono"] }
crc32fast = "1.4"

[dev-dependencies]
tokio-test = "0.4"
"""

with open(f"{base_dir}/Cargo.toml", "w") as f:
    f.write(cargo_toml)
