pub mod protocol;
pub mod runtime;

use std::io::{self, BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpListener};

use protocol::MAX_REQUEST_BYTES;
pub use protocol::{handle_json, ApiError, ErrorCode, Request, Response};
pub use runtime::{shared_runtime, Deadline, Runtime, RuntimeConfig};

pub const DEFAULT_TCP_ADDR: &str = "127.0.0.1:9294";

pub fn bind_tcp(address: SocketAddr) -> io::Result<TcpListener> {
    if !address.ip().is_loopback() {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "TCP address must be loopback",
        ));
    }
    TcpListener::bind(address)
}

pub fn serve_tcp(address: SocketAddr) -> io::Result<()> {
    let listener = bind_tcp(address)?;
    for connection in listener.incoming() {
        handle_connection(connection?, shared_runtime().as_ref())?;
    }
    Ok(())
}

fn handle_connection<S: Read + Write>(stream: S, runtime: &Runtime) -> io::Result<()> {
    let mut stream = BufReader::new(stream);
    let mut body = Vec::new();
    stream
        .by_ref()
        .take((MAX_REQUEST_BYTES + 2) as u64)
        .read_until(b'\n', &mut body)?;

    if body.last() == Some(&b'\n') {
        body.pop();
        if body.last() == Some(&b'\r') {
            body.pop();
        }
    }

    let response = handle_json(&body, runtime, Deadline::default());
    serde_json::to_writer(stream.get_mut(), &response)?;
    stream.get_mut().write_all(b"\n")?;
    stream.get_mut().flush()
}

#[cfg(unix)]
pub fn bind_unix(path: &std::path::Path) -> io::Result<std::os::unix::net::UnixListener> {
    use std::os::unix::fs::{FileTypeExt, PermissionsExt};
    use std::os::unix::net::{UnixListener, UnixStream};

    match std::fs::symlink_metadata(path) {
        Ok(metadata) => {
            if !metadata.file_type().is_socket() {
                return Err(io::Error::new(
                    io::ErrorKind::AlreadyExists,
                    "Unix socket path exists and is not a socket",
                ));
            }
            match UnixStream::connect(path) {
                Ok(_) => {
                    return Err(io::Error::new(
                        io::ErrorKind::AddrInUse,
                        "Unix socket is already accepting connections",
                    ))
                }
                Err(error) if error.kind() == io::ErrorKind::ConnectionRefused => {
                    std::fs::remove_file(path)?;
                }
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(error) => return Err(error),
            }
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        Err(error) => return Err(error),
    }

    let listener = UnixListener::bind(path)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    Ok(listener)
}

#[cfg(unix)]
pub fn serve_unix(path: &std::path::Path) -> io::Result<()> {
    let listener = bind_unix(path)?;
    for connection in listener.incoming() {
        handle_connection(connection?, shared_runtime().as_ref())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpStream;
    use std::sync::Arc;
    use std::thread;

    #[test]
    fn rejects_non_loopback_before_binding() {
        let address = "0.0.0.0:0".parse().unwrap();
        let error = bind_tcp(address).expect_err("non-loopback bind must fail");
        assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
        let error = serve_tcp(address).expect_err("non-loopback serve must fail");
        assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
    }

    #[test]
    fn loopback_transport_returns_deterministic_fail_closed_response() {
        let listener = bind_tcp("127.0.0.1:0".parse().unwrap()).unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let (stream, _) = listener.accept().unwrap();
            handle_connection(stream, shared_runtime().as_ref()).unwrap();
        });

        let mut client = TcpStream::connect(address).unwrap();
        client
            .write_all(b"{\"operation\":\"embed\",\"query\":\"bounded\"}\n")
            .unwrap();
        let mut response = String::new();
        BufReader::new(client).read_line(&mut response).unwrap();
        server.join().unwrap();

        assert_eq!(
            response,
            "{\"ok\":false,\"error\":{\"code\":\"runtime_unavailable\",\"message\":\"ONNX session is unavailable\"}}\n"
        );
        assert!(Arc::ptr_eq(&shared_runtime(), &shared_runtime()));
    }

    #[cfg(unix)]
    #[test]
    fn unix_bind_replaces_stale_socket_and_sets_owner_only_permissions() {
        use std::os::unix::fs::PermissionsExt;
        use std::os::unix::net::UnixListener;
        use std::time::{SystemTime, UNIX_EPOCH};

        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path =
            std::path::PathBuf::from(format!("/tmp/aort-{}-{unique}.sock", std::process::id()));
        let stale = UnixListener::bind(&path).unwrap();
        drop(stale);

        let listener = bind_unix(&path).unwrap();
        assert_eq!(
            std::fs::metadata(&path).unwrap().permissions().mode() & 0o777,
            0o600
        );
        drop(listener);
        std::fs::remove_file(path).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn unix_bind_does_not_remove_non_socket_paths() {
        use std::io::Write as _;
        use std::time::{SystemTime, UNIX_EPOCH};

        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path =
            std::path::PathBuf::from(format!("/tmp/aort-{}-{unique}.txt", std::process::id()));
        std::fs::File::create(&path)
            .unwrap()
            .write_all(b"keep")
            .unwrap();

        let error = bind_unix(&path).expect_err("regular file must be preserved");
        assert_eq!(error.kind(), io::ErrorKind::AlreadyExists);
        assert_eq!(std::fs::read(&path).unwrap(), b"keep");
        std::fs::remove_file(path).unwrap();
    }
}
