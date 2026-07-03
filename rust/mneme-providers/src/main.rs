use mneme_providers::{app, state_from_env};

#[tokio::main]
async fn main() {
    let bind =
        std::env::var("MNEME_PROVIDERS_BIND").unwrap_or_else(|_| "127.0.0.1:8000".to_string());
    let listener = tokio::net::TcpListener::bind(&bind)
        .await
        .unwrap_or_else(|err| panic!("failed to bind {bind}: {err}"));
    let state =
        state_from_env().unwrap_or_else(|err| panic!("failed to initialize provider state: {err}"));
    axum::serve(listener, app(state)).await.unwrap();
}
