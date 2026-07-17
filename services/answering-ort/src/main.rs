use std::io;
use std::net::SocketAddr;

fn main() -> io::Result<()> {
    #[cfg(unix)]
    if let Some(path) = std::env::var_os("ANSWERING_ORT_UNIX_SOCKET") {
        return answering_ort::serve_unix(std::path::Path::new(&path));
    }

    let configured = std::env::var("ANSWERING_ORT_TCP_ADDR")
        .unwrap_or_else(|_| answering_ort::DEFAULT_TCP_ADDR.to_owned());
    let address: SocketAddr = configured.parse().map_err(|error| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("ANSWERING_ORT_TCP_ADDR must be a socket address: {error}"),
        )
    })?;
    answering_ort::serve_tcp(address)
}
