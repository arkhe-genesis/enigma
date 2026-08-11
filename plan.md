1. **Create Project:** Create a new Rust project `arkhe-n-v1.6` in the repository root.
2. **Verify Project Creation:** Use `ls -la` to confirm the `arkhe-n-v1.6` directory structure was created successfully.
3. **Setup Cargo.toml:** Use the dependencies from the v1.4 script, ensuring everything required for the new modules is included.
4. **Migrate and Fix v1.4 Code:** Import the v1.4 codebase (from the user's prompt script) into `src/` and apply fixes for the compilation errors present in the original script:
   - Fix non-ASCII byte strings (e.g., `🚀` -> `\xF0\x9F\x9A\x80`).
   - Fix format string errors (`{:.4f}` -> `{:.4}`).
   - Add `Deserialize` to `NeutrinoProof` in `src/transmission_log.rs`.
   - Fix ambiguous float types (`bg_rate: f64` in `src/seti.rs`).
   - Fix incorrect imports (`crate::main::*` -> `crate::*` in `src/api.rs`).
5. **Verify Compilation:** Run `cargo check` inside `arkhe-n-v1.6` to verify the migrated code and fixes compile without syntax errors.
6. **Implement `src/accelerator.rs`:** Create `src/accelerator.rs` and implement the `SimulationAccelerator` struct with a `process_batch` method that applies dropout and graph aggregation, as sketched in the issue. Include definitions for `Event` and `AgentId`.
7. **Implement `src/validation.rs`:** Create `src/validation.rs` containing the `EmpiricalValidator` struct and `validate_cevns` method to calculate error percentages and validate against tolerance, as sketched in the issue.
8. **Implement `src/telemetry.rs`:** Create `src/telemetry.rs` defining the `Telemetry` struct with fields for events processed, latency, energy, and PQ signature time, and implement the `record` and `report` methods, using definitions from the issue.
9. **Upgrade `src/transmission_log.rs`:** Extend `NeutrinoProof` to support `signature`, `public_key`, and `pq_scheme`. Update the SQLite schema in `TransmissionLedger::init_db` and the `record` method to persist these fields. Implement the `verify_signature` method with stubs for `falcon_verify` and `mldsa_verify`.
10. **Verify Ledger Upgrades:** Use `cat src/transmission_log.rs` to confirm that the modifications to `src/transmission_log.rs` were applied correctly.
11. **Integrate and Wire Up:** Edit `src/main.rs` to import the new modules (`accelerator`, `validation`, `telemetry`). Update `ServerState` to include `telemetry` and `accelerator` if necessary, or just test them. Add `assert_ppm4_capacity_is_valid()` to the constructors in `src/channel.rs`.
12. **Run Tests:** Run `cargo test` in the `arkhe-n-v1.6` directory to ensure all tests pass and no regressions were introduced.
13. **Pre Commit Steps:** Complete pre commit steps to ensure proper testing, verifications, reviews and reflections are done.
14. **Submit:** Commit the changes and submit the branch.
