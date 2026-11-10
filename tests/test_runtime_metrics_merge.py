"""Operational telemetry cannot make successful memory operations fail."""
from concurrent.futures import ThreadPoolExecutor

from mnemosyne.runtime_state import RuntimeState


def test_concurrent_metric_deltas_and_samples_merge_without_double_counting(tmp_path):
    path = tmp_path / 'runtime.json'
    initial = RuntimeState(path)
    initial.save()
    first, second = RuntimeState(path), RuntimeState(path)
    one, two = first.load_metrics(), second.load_metrics()
    one.record_retrieval({'lexical': 2}, 10, False)
    two.record_retrieval({'lexical': 3}, 20, True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda pair: pair[0].save_metrics(pair[1]), [(first, one), (second, two)]))
    saved = RuntimeState(path).load_metrics().snapshot()
    assert saved.counters['retrieval.requests'] == 2
    assert saved.counters['retrieval.channel.lexical.hits'] == 5
    assert saved.counters['retrieval.abstentions'] == 1
    assert sorted(saved.samples['retrieval.latency_ms']) == [10, 20]
    assert saved.gauges['retrieval.latency_ms.p95'] == 20
    first.save_metrics(one)
    second.save_metrics(two)
    assert RuntimeState(path).load_metrics().snapshot() == saved
    one.record_retrieval({}, 30, False)
    first.save_metrics(one)
    saved = RuntimeState(path).load_metrics().snapshot()
    assert saved.counters['retrieval.requests'] == 3
    assert sorted(saved.samples['retrieval.latency_ms']) == [10, 20, 30]


def test_equal_window_observations_and_last_committing_gauge_survive(tmp_path):
    path = tmp_path / 'runtime.json'
    initial = RuntimeState(path)
    metrics = initial.load_metrics()
    for _ in range(200):
        metrics.observe('latency', 1)
    metrics.gauge('queue_size', 5)
    initial.save_metrics(metrics)
    first, second = RuntimeState(path), RuntimeState(path)
    one, two = first.load_metrics(), second.load_metrics()
    one.observe('latency', 2)
    one.gauge('queue_size', 3)
    two.observe('latency', 1)  # Same values/length as baseline: still a new observation.
    two.gauge('queue_size', 5)  # Explicit reset to baseline is still a write.
    first.save_metrics(one)
    second.save_metrics(two)
    saved = RuntimeState(path).load_metrics().snapshot()
    assert len(saved.samples['latency']) == 200
    assert saved.samples['latency'][-2:] == [2, 1]
    assert saved.gauges['queue_size'] == 5


def test_metrics_respect_profile_erasure_and_retry_failed_advisory_write(tmp_path, monkeypatch):
    path = tmp_path / 'runtime.json'
    state = RuntimeState(path)
    state.data['user_model']['entries'] = [{'id': 'private', 'statement': 'erase me'}]
    state.save()
    stale, eraser = RuntimeState(path), RuntimeState(path)
    metrics = stale.load_metrics()
    metrics.increment('requests')
    metrics.observe('latency', 4)
    eraser.data['user_model']['entries'] = []
    eraser.save()
    real_publish = stale._publish

    def unavailable(_data):
        raise OSError('disk temporarily unavailable')

    monkeypatch.setattr(stale, '_publish', unavailable)
    stale.save_metrics(metrics)  # Advisory failure must not escape the memory operation.
    assert RuntimeState(path).data['user_model']['entries'] == []
    monkeypatch.setattr(stale, '_publish', real_publish)
    stale.save_metrics(metrics)
    saved = RuntimeState(path)
    assert saved.data['user_model']['entries'] == []
    assert saved.load_metrics().snapshot().counters['requests'] == 1
    assert saved.load_metrics().snapshot().samples['latency'] == [4]


def test_shared_registry_parallel_saves_do_not_duplicate_observations(tmp_path):
    state = RuntimeState(tmp_path / 'runtime.json')
    metrics = state.load_metrics()

    def observe_and_save(_):
        metrics.increment('requests')
        metrics.observe('latency', 1)
        state.save_metrics(metrics)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(observe_and_save, range(12)))
    state.save_metrics(metrics)
    saved = RuntimeState(state.path).load_metrics().snapshot()
    assert saved.counters['requests'] == 12
    assert saved.samples['latency'] == [1] * 12
