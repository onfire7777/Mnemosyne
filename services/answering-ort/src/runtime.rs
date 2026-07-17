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
            intra_op_threads: requested_intra_op_threads.clamp(1, 2),
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

impl Default for RuntimeConfig {
    fn default() -> Self {
        Self::new(None, 2)
    }
}

pub trait InferenceSession: Send + Sync {
    fn infer(&self, request: &Request) -> Result<Output, ApiError>;
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

        let result = session.infer(&request);
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
}

impl Default for Deadline {
    fn default() -> Self {
        Self::from_start(Instant::now())
    }
}

static SHARED_RUNTIME: OnceLock<Arc<Runtime>> = OnceLock::new();

pub fn shared_runtime() -> Arc<Runtime> {
    Arc::clone(
        SHARED_RUNTIME.get_or_init(|| Arc::new(Runtime::unavailable(RuntimeConfig::from_env()))),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn configuration_enforces_the_resource_contract() {
        let config = RuntimeConfig::new(Some(PathBuf::from("/models/local.onnx")), 64);
        assert_eq!(config.model_path, Some(PathBuf::from("/models/local.onnx")));
        assert!(!config.cpu_arena_enabled);
        assert!(config.memory_map_model);
        assert_eq!(config.intra_op_threads, 2);
        assert_eq!(config.inter_op_threads, 1);
        assert_eq!(MAX_IN_FLIGHT, 1);
        assert_eq!(REQUEST_DEADLINE, Duration::from_secs(30));
    }

    #[test]
    fn process_runtime_is_shared_and_unavailable_fails_closed() {
        let first = shared_runtime();
        let second = shared_runtime();
        assert!(Arc::ptr_eq(&first, &second));

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
}
