use mneme_providers::{app, state_from_env};

#[tokio::main]
async fn main() {
    let state =
        state_from_env().unwrap_or_else(|err| panic!("failed to initialize provider state: {err}"));
    #[cfg(unix)]
    if let Ok(socket_path) = std::env::var("MNEME_PROVIDERS_UNIX_SOCKET") {
        let trimmed = socket_path.trim();
        if !trimmed.is_empty() {
            use std::os::unix::fs::PermissionsExt;
            let path = std::path::Path::new(trimmed);
            if let Some(parent) = path.parent() {
                if !parent.as_os_str().is_empty() {
                    std::fs::create_dir_all(parent).unwrap_or_else(|err| {
                        panic!("failed to create socket parent directory: {err}")
                    });
                    let _ = std::fs::set_permissions(parent, std::fs::Permissions::from_mode(0o700));
                }
            }
            let _ = std::fs::remove_file(path);
            let listener = tokio::net::UnixListener::bind(path)
                .unwrap_or_else(|err| panic!("failed to bind Unix socket {trimmed}: {err}"));
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
                .unwrap_or_else(|err| panic!("failed to chmod Unix socket {trimmed}: {err}"));
            axum::serve(listener, app(state)).await.unwrap();
            return;
        }
    }
    let bind =
        std::env::var("MNEME_PROVIDERS_BIND").unwrap_or_else(|_| "127.0.0.1:8000".to_string());
    let listener = tokio::net::TcpListener::bind(&bind)
        .await
        .unwrap_or_else(|err| panic!("failed to bind {bind}: {err}"));
    axum::serve(listener, app(state)).await.unwrap();
}
