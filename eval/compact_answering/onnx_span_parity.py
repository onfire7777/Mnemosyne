"""Generate and measure a tiny synthetic graph; no learned model or QA score.

Run with isolated onnx==1.18.0 and onnxruntime==1.28.0 dependencies. The
output directory is exclusive. Pass it to the Rust ignored integration test.
"""
from pathlib import Path
import hashlib
import json
import sys


def main():
    import numpy as np
    import onnx
    from onnx import TensorProto, helper
    import onnxruntime as ort

    if onnx.__version__ != '1.18.0' or ort.__version__ != '1.28.0':
        raise ValueError('parity runtime versions differ from the pinned protocol')
    root = Path(sys.argv[1])
    root.mkdir(parents=True, exist_ok=False)
    inputs = [helper.make_tensor_value_info(name, TensorProto.INT64, [1, 'tokens'])
              for name in ('input_ids', 'attention_mask')]
    outputs = [helper.make_tensor_value_info(name, TensorProto.FLOAT, [1, 'tokens'])
               for name in ('start_logits', 'end_logits')]
    graph = helper.make_graph([
        helper.make_node('Cast', ['input_ids'], ['start_logits'], to=TensorProto.FLOAT),
        helper.make_node('Cast', ['attention_mask'], ['mask'], to=TensorProto.FLOAT),
        helper.make_node('Mul', ['start_logits', 'mask'], ['end_logits']),
    ], 'synthetic-span-tensor-parity', inputs, outputs)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 17)], ir_version=10)
    onnx.checker.check_model(model)
    raw = model.SerializeToString()
    (root/'span.onnx').write_bytes(raw)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    session = ort.InferenceSession(raw, options, providers=['CPUExecutionProvider'])
    variants = {}
    def save_variant(name, changed):
        onnx.checker.check_model(changed)
        data = changed.SerializeToString()
        (root/(name+'.onnx')).write_bytes(data)
        variants[name] = hashlib.sha256(data).hexdigest()

    from copy import deepcopy
    extra = deepcopy(model)
    extra.graph.output.append(helper.make_tensor_value_info('mask', TensorProto.FLOAT, [1, 'tokens']))
    save_variant('extra-output', extra)
    nonfinite = deepcopy(model)
    nonfinite.graph.node[-1].CopyFrom(helper.make_node('Div', ['start_logits', 'mask'], ['end_logits']))
    save_variant('nonfinite', nonfinite)
    short = deepcopy(model)
    short.graph.node[-1].CopyFrom(helper.make_node('ReduceSum', ['start_logits'], ['end_logits'], keepdims=1))
    short.graph.output[-1].CopyFrom(helper.make_tensor_value_info('end_logits', TensorProto.FLOAT, [1, 1]))
    save_variant('short-output', short)
    typed = deepcopy(model)
    typed.graph.input.append(helper.make_tensor_value_info('token_type_ids', TensorProto.INT64, [1, 'tokens']))
    save_variant('token-types', typed)
    cases = []
    for length in (1, 64, 128, 384, 512):
        ids = np.arange(length, dtype=np.int64).reshape(1, -1)
        mask = np.ones((1, length), dtype=np.int64)
        if length > 1:
            mask[0, -1] = 0
        start, end = session.run(['start_logits', 'end_logits'], {'input_ids': ids, 'attention_mask': mask})
        cases.append({'input': {'input_ids': ids[0].tolist(), 'attention_mask': mask[0].tolist(), 'token_type_ids': None},
                      'output': {'start_logits': start[0].tolist(), 'end_logits': end[0].tolist()}})
    artifact = {'schema': 'compact-onnx-span-tensor-parity/v1', 'synthetic': True,
                'model_sha256': hashlib.sha256(raw).hexdigest(), 'onnx_version': onnx.__version__,
                'onnxruntime_version': ort.__version__, 'numpy_version': np.__version__,
                'cases': cases, 'variant_hashes': variants, 'learned_quality_verified': False, 'resource_admission_verified': False}
    (root/'fixture.json').write_text(json.dumps(artifact, sort_keys=True, indent=2)+'\n')
    print(json.dumps({'directory': str(root), 'model_bytes': len(raw), 'cases': len(cases),
                      'model_sha256': artifact['model_sha256']}))


if __name__ == '__main__':
    main()
