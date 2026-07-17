fn main() {
    // Transport startup is added separately; initializing here keeps this binary
    // fail-closed until a real ONNX session is installed.
    let _ = answering_ort::shared_runtime();
}
