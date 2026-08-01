use arkhe_soc_tlm::arkhe_fountain_decoder::{ErasureChannel, FountainDecoder};
use arkhe_soc_tlm::arkhe_fountain_encoder::FountainEncoder;
use rand::thread_rng;
use std::env;

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 5 {
        println!("Usage: {} <K> <loss_rate> <block_size> <n_frames>", args[0]);
        println!("Running default simulation...");
        run_sim(256, 0.5, 32, 20000);

        println!("\nRunning interstellar scenario simulation (loss_rate ~0.1)...");
        run_sim(256, 0.1, 32, 20000);

        println!("\nRunning DSN scenario simulation (loss_rate ~10^-6)...");
        run_sim(256, 0.000001, 32, 20000);
        return;
    }

    let k: usize = args[1].parse().unwrap_or(256);
    let loss_rate: f64 = args[2].parse().unwrap_or(0.5);
    let block_size: usize = args[3].parse().unwrap_or(32);
    let n_frames: usize = args[4].parse().unwrap_or(20000);

    run_sim(k, loss_rate, block_size, n_frames);
}

fn run_sim(k: usize, loss_rate: f64, block_size: usize, n_frames: usize) {
    let mut data = vec![0u8; k * block_size];
    for i in 0..data.len() {
        data[i] = (i % 256) as u8;
    }

    let mut encoder = FountainEncoder::new(&data, block_size, 0.03, 0.5);
    let channel = ErasureChannel::new(loss_rate);
    let mut decoder = FountainDecoder::new();
    let mut rng = thread_rng();

    let mut transmitted = 0;
    let mut received = 0;

    for _ in 0..n_frames {
        let frame = encoder.next_frame();
        transmitted += 1;
        if let Some(received_frame) = channel.transmit(&frame, &mut rng) {
            received += 1;
            if decoder.receive_frame(&received_frame).unwrap() {
                break;
            }
        }
    }

    let success_prob = if decoder.is_complete() { 1.0 } else { 0.0 };
    println!("Simulating K={}, loss_rate={}, block_size={}, max_frames={}", k, loss_rate, block_size, n_frames);
    println!("Transmitted: {}, Received: {}, Progress: {:.1}%",
             transmitted, received, decoder.progress() * 100.0);
    println!("Total transmission time abstract: {} frames", transmitted);
    println!("Success probability: {}", success_prob);
}
