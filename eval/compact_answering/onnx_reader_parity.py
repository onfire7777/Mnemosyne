"""Add synthetic decoded-reader reference cases to a fresh tensor fixture.

No model download, training data, protected question or quality score. The
separate Python implementation uses the declared window-null-margin-v1 policy.
"""
from pathlib import Path
import hashlib
import json
import sys


def main():
    import numpy as np
    import onnxruntime as ort
    import tokenizers
    from tokenizers import Tokenizer, models, pre_tokenizers, processors

    if ort.__version__ != '1.28.0' or tokenizers.__version__ != '0.22.1':
        raise ValueError('reader reference dependencies differ from the pinned protocol')
    root = Path(sys.argv[1])
    names = ['[UNK]', '[CLS]', '[SEP]', 'word', 'unused4', 'unused5', 'unused6',
             'unused7', 'unused8', 'unused9', 'café', 'cafe\u0301', '東京', 'ask']
    tokenizer = Tokenizer(models.WordLevel(dict(zip(names, range(len(names)))), unk_token='[UNK]'))
    tokenizer.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
    tokenizer.post_processor = processors.TemplateProcessing(
        single='[CLS] $A [SEP]', pair='[CLS] $A [SEP] $B:1 [SEP]:1',
        special_tokens=[('[CLS]', 1), ('[SEP]', 2)])
    raw = tokenizer.to_str().encode()
    with (root/'tokenizer.json').open('xb') as output:
        output.write(raw)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    model = (root/'span.onnx').read_bytes()
    session = ort.InferenceSession(model, options, providers=['CPUExecutionProvider'])
    documents = [
        ['word café café'], ['word cafe\u0301'], ['word café 東京'],
        ['word '*900+'東京'], ['café', '東京'], ['unknown'], [], ['café', 'café'],
        ['word '*507+'café '+'word '*200], ['[CLS] unknown'],
    ]
    rows = []
    for index, texts in enumerate(documents):
        evidence = [{'id': f'cid-{i}', 'text': text} for i, text in enumerate(texts)]
        best = None
        window_counts = []
        for row_index, row in enumerate(evidence):
            tokenizer.no_truncation()
            full = tokenizer.encode('ask', row['text'])
            context_count = full.sequence_ids.count(1)
            overhead = len(full.ids)-context_count
            tokenizer.enable_truncation(512, stride=512-overhead-128, strategy='only_second')
            encoded = tokenizer.encode('ask', row['text'])
            windows = [encoded, *encoded.overflowing]
            window_counts.append(len(windows))
            for window in windows:
                ids = np.array([window.ids], dtype=np.int64)
                mask = np.array([window.attention_mask], dtype=np.int64)
                start, end = session.run(['start_logits', 'end_logits'], {'input_ids': ids, 'attention_mask': mask})
                null_index = next(i for i, (value, special) in enumerate(zip(window.ids, window.special_tokens_mask))
                                  if value == 1 and special == 1)
                null = np.float32(start[0, null_index]+end[0, null_index])
                # max_answer_tokens=1 is fixed for these test fixtures.
                for token, sequence in enumerate(window.sequence_ids):
                    if sequence != 1 or window.special_tokens_mask[token] or not window.attention_mask[token]:
                        continue
                    margin = np.float32(np.float32(start[0, token]+end[0, token])-null)
                    if margin <= 0:
                        continue
                    left, right = window.offsets[token]
                    byte_start = len(row['text'][:left].encode())
                    byte_end = len(row['text'][:right].encode())
                    key = (-float(margin), row_index, byte_start, byte_end)
                    if best is None or key < best:
                        best = key
        prediction = {'answer_type': 'null', 'supporting_ids': []}
        if best is not None:
            _, row_index, start, end = best
            cid = evidence[row_index]['id']
            prediction = {'answer_type': 'span', 'evidence_id': cid, 'start': start, 'end': end, 'supporting_ids': [cid]}
        rows.append({'case_id': f'synthetic-{index}', 'query': 'ask', 'evidence': evidence,
                     'output': {'operation': 'read', 'prediction': prediction}, 'window_counts': window_counts})
    artifact = {'schema': 'compact-onnx-decoded-parity/v1', 'synthetic': True,
                'policy': 'window-null-margin-v1', 'window_length': 512, 'window_step': 128,
                'null_token_id': 1, 'null_threshold': 0.0, 'max_answer_tokens': 1,
                'model_sha256': hashlib.sha256(model).hexdigest(),
                'tokenizer_sha256': hashlib.sha256(raw).hexdigest(),
                'onnxruntime_version': ort.__version__, 'tokenizers_version': tokenizers.__version__,
                'cases': rows, 'learned_quality_verified': False, 'resource_admission_verified': False}
    with (root/'reader-cases.json').open('x') as output:
        json.dump(artifact, output, ensure_ascii=False, sort_keys=True, indent=2)
        output.write('\n')
    print(json.dumps({'cases': len(rows), 'tokenizer_sha256': artifact['tokenizer_sha256']}))


if __name__ == '__main__':
    main()
