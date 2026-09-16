from app import worker
from app import telemetry


def test_worker_iteration_continues_after_partition_failure(monkeypatch):
    consumed = []
    maintenance = []
    heartbeat = []

    def consume(partition, _consumer):
        consumed.append(partition)
        if partition == 0:
            raise RuntimeError("temporary stream failure")

    monkeypatch.setattr(worker, "consume_once", consume)
    monkeypatch.setattr(worker, "maintenance_once", lambda: maintenance.append(True))
    monkeypatch.setattr(worker.cache, "setex", lambda *args: heartbeat.append(args))
    monkeypatch.setattr(worker.time, "monotonic", lambda: 3)

    last, had_error = worker.run_iteration([0, 1], "test-worker", 0)

    assert consumed == [0, 1]
    assert maintenance == [True]
    assert heartbeat and heartbeat[0][0] == "worker:heartbeat:test-worker"
    assert last == 3
    assert had_error is True


def test_telemetry_consumer_initializes_group_once_and_uses_bounded_block(monkeypatch):
    class FakeStreamCache:
        def __init__(self):
            self.group_creates = 0
            self.blocks = []

        def xgroup_create(self, *_args, **_kwargs):
            self.group_creates += 1

        def xautoclaim(self, *_args, **_kwargs):
            return "0-0", []

        def xreadgroup(self, *_args, **kwargs):
            self.blocks.append(kwargs["block"])
            return []

    fake = FakeStreamCache()
    previous_groups = set(telemetry._initialized_groups)
    telemetry._initialized_groups.clear()
    monkeypatch.setattr(telemetry, "cache", fake)

    try:
        assert telemetry.consume_once(1, "test-worker") == 0
        assert telemetry.consume_once(1, "test-worker") == 0
    finally:
        telemetry._initialized_groups.clear()
        telemetry._initialized_groups.update(previous_groups)

    assert fake.group_creates == 1
    assert fake.blocks == [telemetry.READ_BLOCK_MS, telemetry.READ_BLOCK_MS]
