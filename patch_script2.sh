sed -i 's/let original = b"Hello, ARKHE-N! 🚀";/let original = b"Hello, ARKHE-N! \\xF0\\x9F\\x9A\\x80";/' arkhe-n-v1.4/src/modulation.rs
sed -i 's/Cap={:.4f}/Cap={:.4}/' arkhe-n-v1.4/src/main.rs
