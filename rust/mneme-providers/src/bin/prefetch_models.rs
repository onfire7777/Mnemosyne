fn main() {
    mneme_providers::state_from_env()
        .unwrap_or_else(|err| panic!("failed to prefetch provider models: {err}"));
    println!("provider models initialized");
}
