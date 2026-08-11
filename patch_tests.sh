sed -i 's/let err = rand::random::<f64>() < 0.1;/let err = bit ^ (rand::random::<f64>() < 0.1);/' arkhe-n-v1.6/src/coding.rs
sed -i 's/let mut tampered = packet.clone();/let mut tampered = packet.clone();/' arkhe-n-v1.6/src/coding.rs
cat << 'INNER_EOF' > /tmp/test_ledger_patch.txt
<<<<<<< SEARCH
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
=======
    #[test]
    fn test_ledger_in_memory() {
        let ledger = TransmissionLedger::init_db(":memory:").unwrap();
        let proof = NeutrinoProof::new(
            "0xabc123", "MINERvA", 433000.0, 0.5, true, 1.035, "10.1126/science.198.4319.295", 1977
        );
        ledger.record(proof.clone()).unwrap();
        assert!(ledger.verify_anchored("0xabc123").unwrap());
        assert!(!ledger.verify_anchored("0xdead").unwrap());
        assert_eq!(ledger.proofs_len(), 1);
        assert!(ledger.total_energy_consumed_joules() > 0.0);
    }
>>>>>>> REPLACE
INNER_EOF
