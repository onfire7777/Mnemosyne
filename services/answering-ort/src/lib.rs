pub mod protocol;
pub mod runtime;

use std::io::{self, Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::time::Duration;

use protocol::MAX_REQUEST_BYTES;
pub use protocol::{handle_json, ApiError, ErrorCode, Request, Response};
pub use runtime::{shared_runtime, Deadline, Runtime, RuntimeConfig, REQUEST_DEADLINE};

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
    serve_tcp_listener(listener)
}

fn serve_tcp_listener(listener: TcpListener) -> io::Result<()> {
    loop {
        let (stream, _) = match listener.accept() {
            Ok(connection) => connection,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        };
        if let Err(error) = handle_connection(stream, shared_runtime(), Deadline::default()) {
            eprintln!("answering-ort: TCP connection failed: {:?}", error.kind());
        }
    }
}

trait TimedStream: Read + Write {
    fn set_read_deadline(&self, timeout: Option<Duration>) -> io::Result<()>;
    fn set_write_deadline(&self, timeout: Option<Duration>) -> io::Result<()>;
}

impl TimedStream for TcpStream {
    fn set_read_deadline(&self, timeout: Option<Duration>) -> io::Result<()> {
        self.set_read_timeout(timeout)
    }

    fn set_write_deadline(&self, timeout: Option<Duration>) -> io::Result<()> {
        self.set_write_timeout(timeout)
    }
}

fn handle_connection<S: TimedStream>(
    mut stream: S,
    runtime: &Runtime,
    deadline: Deadline,
) -> io::Result<()> {
    let mut body = Vec::new();
    let mut chunk = [0_u8; 4096];
    let response = loop {
        let Some(remaining) = deadline.remaining() else {
            break Response::failure(ApiError::timed_out());
        };
        stream.set_read_deadline(Some(remaining))?;
        let capacity = MAX_REQUEST_BYTES + 2 - body.len();
        if capacity == 0 {
            break handle_json(&body, runtime, deadline);
        }
        let read_len = capacity.min(chunk.len());
        match stream.read(&mut chunk[..read_len]) {
            Ok(0) => break handle_json(&body, runtime, deadline),
            Ok(count) => {
                body.extend_from_slice(&chunk[..count]);
                if let Some(newline) = body.iter().position(|byte| *byte == b'\n') {
                    body.truncate(newline + 1);
                    break handle_json(trim_line_ending(&mut body), runtime, deadline);
                }
            }
            Err(error)
                if matches!(
                    error.kind(),
                    io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock
                ) =>
            {
                break Response::failure(ApiError::timed_out());
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        }
    };

    stream.set_write_deadline(Some(
        deadline.remaining().unwrap_or(Duration::from_millis(100)),
    ))?;
    serde_json::to_writer(&mut stream, &response)?;
    stream.write_all(b"\n")?;
    stream.flush()
}

fn trim_line_ending(body: &mut Vec<u8>) -> &[u8] {
    body.pop();
    if body.last() == Some(&b'\r') {
        body.pop();
    }
    body
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
    loop {
        let (stream, _) = match listener.accept() {
            Ok(connection) => connection,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        };
        if let Err(error) = handle_connection(stream, shared_runtime(), Deadline::default()) {
            eprintln!("answering-ort: Unix connection failed: {:?}", error.kind());
        }
    }
}

#[cfg(unix)]
impl TimedStream for std::os::unix::net::UnixStream {
    fn set_read_deadline(&self, timeout: Option<Duration>) -> io::Result<()> {
        self.set_read_timeout(timeout)
    }

    fn set_write_deadline(&self, timeout: Option<Duration>) -> io::Result<()> {
        self.set_write_timeout(timeout)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufRead, BufReader};
    use std::thread;

    #[cfg(unix)]
    struct TestPath(std::path::PathBuf);

    #[cfg(unix)]
    impl TestPath {
        fn new(suffix: &str) -> Self {
            use std::time::{SystemTime, UNIX_EPOCH};

            let unique = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos();
            Self(std::path::PathBuf::from(format!(
                "/tmp/aort-{}-{unique}.{suffix}",
                std::process::id()
            )))
        }
    }

    #[cfg(unix)]
    impl Drop for TestPath {
        fn drop(&mut self) {
            let _ = std::fs::remove_file(&self.0);
        }
    }

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
            handle_connection(stream, shared_runtime(), Deadline::default()).unwrap();
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
        assert!(std::ptr::eq(shared_runtime(), shared_runtime()));
    }

    #[test]
    fn request_deadline_covers_incomplete_frames() {
        let listener = bind_tcp("127.0.0.1:0".parse().unwrap()).unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let (stream, _) = listener.accept().unwrap();
            handle_connection(
                stream,
                shared_runtime(),
                Deadline::after(Duration::from_millis(20)),
            )
            .unwrap();
        });

        let mut client = TcpStream::connect(address).unwrap();
        client.write_all(b"{").unwrap();
        let mut response = String::new();
        BufReader::new(client).read_line(&mut response).unwrap();
        server.join().unwrap();
        assert!(response.contains("request_timed_out"));
    }

    #[test]
    fn framing_accepts_crlf_and_rejects_oversized_bodies() {
        fn exchange(body: Vec<u8>) -> String {
            let listener = bind_tcp("127.0.0.1:0".parse().unwrap()).unwrap();
            let address = listener.local_addr().unwrap();
            let server = thread::spawn(move || {
                let (stream, _) = listener.accept().unwrap();
                handle_connection(stream, shared_runtime(), Deadline::default()).unwrap();
            });
            let mut client = TcpStream::connect(address).unwrap();
            client.write_all(&body).unwrap();
            client.shutdown(std::net::Shutdown::Write).unwrap();
            let mut response = String::new();
            BufReader::new(client).read_line(&mut response).unwrap();
            server.join().unwrap();
            response
        }

        assert!(
            exchange(b"{\"operation\":\"embed\",\"query\":\"q\"}\r\n".to_vec())
                .contains("runtime_unavailable")
        );
        let mut exact = b"{\"operation\":\"embed\",\"query\":\"q\"}".to_vec();
        exact.resize(MAX_REQUEST_BYTES, b' ');
        exact.push(b'\n');
        assert!(exchange(exact).contains("runtime_unavailable"));
        assert!(exchange(b"not json\n".to_vec()).contains("malformed_request"));
        assert!(exchange(Vec::new()).contains("malformed_request"));
        assert!(
            exchange(b"{\"operation\":\"embed\",\"query\":\"eof\"}".to_vec())
                .contains("runtime_unavailable")
        );

        let mut oversized = vec![b' '; MAX_REQUEST_BYTES + 1];
        oversized.push(b'\n');
        assert!(exchange(oversized).contains("request_too_large"));
    }

    #[cfg(unix)]
    #[test]
    fn unix_bind_replaces_stale_socket_and_sets_owner_only_permissions() {
        use std::os::unix::fs::PermissionsExt;
        use std::os::unix::net::UnixListener;

        let path = TestPath::new("sock");
        let stale = UnixListener::bind(&path.0).unwrap();
        drop(stale);

        let listener = bind_unix(&path.0).unwrap();
        assert_eq!(
            std::fs::metadata(&path.0).unwrap().permissions().mode() & 0o777,
            0o600
        );
        drop(listener);
    }

    #[cfg(unix)]
    #[test]
    fn unix_bind_preserves_live_socket() {
        use std::os::unix::net::{UnixListener, UnixStream};

        let path = TestPath::new("live.sock");
        let listener = UnixListener::bind(&path.0).unwrap();
        let client = thread::spawn({
            let path = path.0.clone();
            move || UnixStream::connect(path).unwrap()
        });
        let (_stream, _) = listener.accept().unwrap();
        let error = bind_unix(&path.0).expect_err("live socket must be preserved");
        assert_eq!(error.kind(), io::ErrorKind::AddrInUse);
        drop(client.join().unwrap());
        drop(listener);
    }

    #[cfg(unix)]
    #[test]
    fn unix_bind_does_not_remove_non_socket_paths() {
        use std::io::Write as _;

        let path = TestPath::new("txt");
        std::fs::File::create(&path.0)
            .unwrap()
            .write_all(b"keep")
            .unwrap();

        let error = bind_unix(&path.0).expect_err("regular file must be preserved");
        assert_eq!(error.kind(), io::ErrorKind::AlreadyExists);
        assert_eq!(std::fs::read(&path.0).unwrap(), b"keep");
    }
}
