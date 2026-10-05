# Linux native ONNX CI evidence

GitHub Actions run [37240801730](https://github.com/onfire7777/Mnemosyne/actions/runs/37240801730),
job [111548962454](https://github.com/onfire7777/Mnemosyne/actions/runs/37240801730/job/111548962454),
succeeded at source `e1ad2d0cf5ac19298547740363795c2ad25da356`.
The retrieved job log is retained verbatim in `job.log`.

Ubuntu 24.04 ran the optional ONNX suite: 48 library tests, one decoded-reader
integration test, and two tensor integration tests passed. The fixture is a
314-byte arithmetic graph, not learned weights. Python reference generation,
Rust tests, formatting and Clippy completed successfully. This closes the
previously unexecuted Linux CI check for this source; it does not establish
learned quality, physical 8 GiB acceptance or a fully passed workflow. The
main unit/drift job was still running when this evidence was captured.
