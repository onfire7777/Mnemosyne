use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, OnceLock};
use std::time::{Duration, Instant};

use crate::protocol::{ApiError, ErrorCode, Output, Request, Response};

pub const MAX_IN_FLIGHT: usize = 1;
pub const REQUEST_DEADLINE: Duration = Duration::from_secs(30);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeConfig {
    pub model_path: Option<PathBuf>,
    pub cpu_arena_enabled: bool,
    pub memory_map_model: bool,
    pub intra_op_threads: usize,
    pub inter_op_threads: usize,
}

impl RuntimeConfig {
    pub fn new(model_path: Option<PathBuf>, requested_intra_op_threads: usize) -> Self {
        Self {
            model_path,
            cpu_arena_enabled: false,
            memory_map_model: true,
            intra_op_threads: clamp_intra_op_threads(
                requested_intra_op_threads,
                num_cpus::get_physical(),
            ),
            inter_op_threads: 1,
        }
    }

    pub fn from_env() -> Self {
        let model_path = std::env::var_os("ANSWERING_ORT_MODEL_PATH").map(PathBuf::from);
        let requested_threads = std::env::var("ANSWERING_ORT_INTRA_OP_THREADS")
            .ok()
            .and_then(|value| value.parse().ok())
            .unwrap_or(2);
        Self::new(model_path, requested_threads)
    }
}

fn clamp_intra_op_threads(requested: usize, physical_cores: usize) -> usize {
    requested.clamp(1, physical_cores.clamp(1, 2))
}

impl Default for RuntimeConfig {
    fn default() -> Self {
        Self::new(None, 2)
    }
}

pub trait InferenceSession: Send + Sync {
    fn infer(&self, request: &Request, deadline: Deadline) -> Result<Output, ApiError>;
}

pub struct Runtime {
    config: RuntimeConfig,
    session: Option<Arc<dyn InferenceSession>>,
    in_flight: AtomicBool,
}

impl Runtime {
    pub fn unavailable(config: RuntimeConfig) -> Self {
        Self {
            config,
            session: None,
            in_flight: AtomicBool::new(false),
        }
    }

    pub fn with_session(config: RuntimeConfig, session: Arc<dyn InferenceSession>) -> Self {
        Self {
            config,
            session: Some(session),
            in_flight: AtomicBool::new(false),
        }
    }

    pub fn config(&self) -> &RuntimeConfig {
        &self.config
    }

    pub fn execute(&self, request: Request, deadline: Deadline) -> Response {
        if deadline.is_expired() {
            return Response::failure(ApiError::timed_out());
        }

        let _permit = match InFlightPermit::acquire(&self.in_flight) {
            Some(permit) => permit,
            None => {
                return Response::failure(ApiError::new(
                    ErrorCode::RuntimeBusy,
                    "one request is already in flight",
                ))
            }
        };

        let Some(session) = &self.session else {
            return Response::failure(ApiError::unavailable());
        };

        let result = session.infer(&request, deadline);
        if deadline.is_expired() {
            return Response::failure(ApiError::timed_out());
        }

        match result {
            Ok(output) => Response::success(output),
            Err(error) => Response::failure(error),
        }
    }
}

struct InFlightPermit<'a>(&'a AtomicBool);

impl<'a> InFlightPermit<'a> {
    fn acquire(flag: &'a AtomicBool) -> Option<Self> {
        flag.compare_exchange(false, true, Ordering::Acquire, Ordering::Relaxed)
            .ok()
            .map(|_| Self(flag))
    }
}

impl Drop for InFlightPermit<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}

#[derive(Debug, Clone, Copy)]
pub struct Deadline(Instant);

impl Deadline {
    pub fn from_start(started_at: Instant) -> Self {
        Self(started_at + REQUEST_DEADLINE)
    }

    pub fn after(duration: Duration) -> Self {
        Self(Instant::now() + duration.min(REQUEST_DEADLINE))
    }

    pub fn is_expired(self) -> bool {
        Instant::now() >= self.0
    }

    pub fn remaining(self) -> Option<Duration> {
        self.0.checked_duration_since(Instant::now())
    }
}

impl Default for Deadline {
    fn default() -> Self {
        Self::from_start(Instant::now())
    }
}

static SHARED_RUNTIME: OnceLock<Runtime> = OnceLock::new();

pub fn shared_runtime() -> &'static Runtime {
    SHARED_RUNTIME.get_or_init(|| Runtime::unavailable(RuntimeConfig::from_env()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::Output;
    use std::sync::Barrier;
    use std::thread;

    struct FixedSession(Result<Output, ApiError>);

    impl InferenceSession for FixedSession {
        fn infer(&self, _request: &Request, _deadline: Deadline) -> Result<Output, ApiError> {
            self.0.clone()
        }
    }

    struct BlockingSession {
        started: Arc<Barrier>,
        release: Arc<Barrier>,
        block_once: AtomicBool,
    }

    impl InferenceSession for BlockingSession {
        fn infer(&self, _request: &Request, deadline: Deadline) -> Result<Output, ApiError> {
            if self.block_once.swap(false, Ordering::Relaxed) {
                self.started.wait();
                self.release.wait();
            }
            if deadline.is_expired() {
                return Err(ApiError::timed_out());
            }
            Ok(Output::Embed {
                embedding: vec![1.0],
            })
        }
    }

    #[test]
    fn configuration_enforces_the_resource_contract() {
        let config = RuntimeConfig::new(Some(PathBuf::from("/models/local.onnx")), 64);
        assert_eq!(config.model_path, Some(PathBuf::from("/models/local.onnx")));
        assert!(!config.cpu_arena_enabled);
        assert!(config.memory_map_model);
        assert_eq!(
            config.intra_op_threads,
            num_cpus::get_physical().clamp(1, 2)
        );
        assert_eq!(clamp_intra_op_threads(64, 1), 1);
        assert_eq!(clamp_intra_op_threads(64, 8), 2);
        assert_eq!(config.inter_op_threads, 1);
        assert_eq!(MAX_IN_FLIGHT, 1);
        assert_eq!(REQUEST_DEADLINE, Duration::from_secs(30));
    }

    #[test]
    fn process_runtime_is_shared_and_unavailable_fails_closed() {
        let first = shared_runtime();
        let second = shared_runtime();
        assert!(std::ptr::eq(first, second));

        let response = first.execute(
            Request::Embed {
                query: "bounded".into(),
            },
            Deadline::default(),
        );
        assert_eq!(response.error.unwrap().code, ErrorCode::RuntimeUnavailable);
    }

    #[test]
    fn expired_deadline_fails_before_session_access() {
        let runtime = Runtime::unavailable(RuntimeConfig::default());
        let response = runtime.execute(
            Request::Embed { query: "q".into() },
            Deadline::from_start(Instant::now() - Duration::from_secs(31)),
        );
        assert_eq!(response.error.unwrap().code, ErrorCode::RequestTimedOut);
    }

    #[test]
    fn session_success_and_error_are_propagated() {
        let success = Runtime::with_session(
            RuntimeConfig::default(),
            Arc::new(FixedSession(Ok(Output::Embed {
                embedding: vec![1.0],
            }))),
        );
        assert!(
            success
                .execute(Request::Embed { query: "q".into() }, Deadline::default())
                .ok
        );

        let failure = Runtime::with_session(
            RuntimeConfig::default(),
            Arc::new(FixedSession(Err(ApiError::new(
                ErrorCode::InferenceFailed,
                "inference failed",
            )))),
        );
        assert_eq!(
            failure
                .execute(Request::Embed { query: "q".into() }, Deadline::default())
                .error
                .unwrap()
                .code,
            ErrorCode::InferenceFailed
        );
    }

    #[test]
    fn one_in_flight_is_enforced_and_permit_is_released() {
        let started = Arc::new(Barrier::new(2));
        let release = Arc::new(Barrier::new(2));
        let runtime = Arc::new(Runtime::with_session(
            RuntimeConfig::default(),
            Arc::new(BlockingSession {
                started: Arc::clone(&started),
                release: Arc::clone(&release),
                block_once: AtomicBool::new(true),
            }),
        ));
        let worker_runtime = Arc::clone(&runtime);
        let worker = thread::spawn(move || {
            worker_runtime.execute(
                Request::Embed {
                    query: "one".into(),
                },
                Deadline::default(),
            )
        });
        started.wait();

        let busy = runtime.execute(
            Request::Embed {
                query: "two".into(),
            },
            Deadline::default(),
        );
        assert_eq!(busy.error.unwrap().code, ErrorCode::RuntimeBusy);
        release.wait();
        assert!(worker.join().unwrap().ok);

        let later = runtime.execute(
            Request::Embed {
                query: "three".into(),
            },
            Deadline::default(),
        );
        assert!(later.ok);
    }

    #[test]
    fn late_session_result_fails_closed() {
        struct LateSession;
        impl InferenceSession for LateSession {
            fn infer(&self, _request: &Request, _deadline: Deadline) -> Result<Output, ApiError> {
                thread::sleep(Duration::from_millis(10));
                Ok(Output::Embed {
                    embedding: vec![1.0],
                })
            }
        }
        let runtime = Runtime::with_session(RuntimeConfig::default(), Arc::new(LateSession));
        let response = runtime.execute(
            Request::Embed { query: "q".into() },
            Deadline::after(Duration::from_millis(1)),
        );
        assert_eq!(response.error.unwrap().code, ErrorCode::RequestTimedOut);
    }
}
