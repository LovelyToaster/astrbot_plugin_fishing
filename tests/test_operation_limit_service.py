import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import unittest

from core.services.operation_limit_service import OperationLimitService


class FakeClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class OperationLimitServiceTests(unittest.TestCase):
    def test_token_bucket_is_per_real_sender_and_refills_monotonically(self):
        clock = FakeClock()
        service = OperationLimitService({"user_max_inflight": 0}, clock=clock)

        first = service.try_acquire("alice", "alice")
        second = service.try_acquire("alice", "alice")
        third = service.try_acquire("alice", "alice")
        other = service.try_acquire("bob", "bob")

        self.assertTrue(first.accepted)
        self.assertTrue(second.accepted)
        self.assertFalse(third.accepted)
        self.assertEqual(third.reason, "rate")
        self.assertTrue(other.accepted)
        self.assertEqual(third.retry_after, 2.0)

        first.lease.release()
        second.lease.release()
        other.lease.release()
        clock.advance(2.0)
        refilled = service.try_acquire("alice", "alice")
        self.assertTrue(refilled.accepted)
        refilled.lease.release()

    def test_global_rejection_does_not_consume_sender_token(self):
        clock = FakeClock()
        service = OperationLimitService({"global_max_inflight": 1}, clock=clock)
        busy = service.try_acquire("alice", "alice")

        denied = service.try_acquire("bob", "bob")
        self.assertFalse(denied.accepted)
        self.assertEqual(denied.reason, "global")
        self.assertTrue(denied.should_notify)
        self.assertTrue(service._buckets.get("bob") is None)

        busy.lease.release()
        accepted = service.try_acquire("bob", "bob")
        self.assertTrue(accepted.accepted)
        accepted.lease.release()

    def test_admission_is_atomic_under_concurrent_requests(self):
        service = OperationLimitService(
            {
                "enabled": False,
                "global_max_inflight": 4,
            }
        )
        barrier = Barrier(16)

        def acquire():
            barrier.wait()
            return service.try_acquire("same-sender", "same-sender")

        with ThreadPoolExecutor(max_workers=16) as executor:
            results = list(executor.map(lambda _: acquire(), range(16)))

        accepted = [result for result in results if result.accepted]
        self.assertEqual(len(accepted), 4)
        self.assertEqual(service.snapshot()["global_inflight"], 4)
        for result in accepted:
            result.lease.release()
        self.assertEqual(service.snapshot()["global_inflight"], 0)

    def test_proxy_reserves_target_slot_but_charges_only_sender_bucket(self):
        service = OperationLimitService()
        target_busy = service.try_acquire("target", "target")
        target_tokens_after_direct_request = service._buckets["target"].tokens
        proxy_denied = service.try_acquire("admin", "target")

        self.assertFalse(proxy_denied.accepted)
        self.assertEqual(proxy_denied.reason, "user_inflight")
        self.assertIsNone(service._buckets.get("admin"))

        target_busy.lease.release()
        proxy = service.try_acquire("admin", "target")
        self.assertTrue(proxy.accepted)
        self.assertIn("admin", service._buckets)
        self.assertEqual(service._buckets["target"].tokens, target_tokens_after_direct_request)
        proxy.lease.release()

    def test_user_overrides_and_disabled_user_limits_keep_global_cap(self):
        service = OperationLimitService(
            {
                "enabled": False,
                "global_max_inflight": 2,
                "user_overrides": '{"alice":{"interval_seconds":1,"burst":1,"max_inflight":1}}',
            }
        )
        reservations = [service.try_acquire("alice", "alice") for _ in range(2)]
        self.assertTrue(all(result.accepted for result in reservations))

        third = service.try_acquire("alice", "alice")
        self.assertFalse(third.accepted)
        self.assertEqual(third.reason, "global")
        reservations[0].lease.release()
        reservations[1].lease.release()

        enabled = OperationLimitService(
            {
                "user_interval_seconds": 0,
                "user_max_inflight": 0,
                "user_overrides": {
                    "slow": {"interval_seconds": 2, "burst": 1, "max_inflight": 1},
                    "override-rate": {"interval_seconds": 2, "burst": 1, "max_inflight": 0},
                },
            }
        )
        first = enabled.try_acquire("slow", "slow")
        denied = enabled.try_acquire("slow", "slow")
        self.assertTrue(first.accepted)
        self.assertFalse(denied.accepted)
        self.assertEqual(denied.reason, "user_inflight")
        first.lease.release()

        override_first = enabled.try_acquire("override-rate", "override-rate")
        override_denied = enabled.try_acquire("override-rate", "override-rate")
        self.assertTrue(override_first.accepted)
        self.assertFalse(override_denied.accepted)
        self.assertEqual(override_denied.reason, "rate")
        override_first.lease.release()

    def test_rejection_notice_is_throttled_and_idle_state_is_cleaned(self):
        clock = FakeClock()
        service = OperationLimitService({"user_max_inflight": 0}, clock=clock)
        first = service.try_acquire("alice", "alice")
        second = service.try_acquire("alice", "alice")
        third = service.try_acquire("alice", "alice")
        self.assertTrue(first.accepted)
        self.assertTrue(second.accepted)
        self.assertTrue(third.should_notify)
        first.lease.release()
        second.lease.release()

        clock.advance(2.0)
        one_more = service.try_acquire("alice", "alice")
        one_more.lease.release()
        rate_limited = service.try_acquire("alice", "alice")
        self.assertFalse(rate_limited.should_notify)

        clock.advance(service.STATE_TTL_SECONDS + service.CLEANUP_INTERVAL_SECONDS)
        service.try_acquire("bob", "bob").lease.release()
        self.assertNotIn("alice", service._buckets)
        self.assertNotIn("alice", service._last_notice)


class OperationStreamReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_consumer_close_closes_source_and_releases_capacity(self):
        service = OperationLimitService()
        admission = service.try_acquire("alice", "alice")
        source_closed = asyncio.Event()

        async def source():
            try:
                yield "first"
                await asyncio.Event().wait()
            finally:
                source_closed.set()

        stream = service.stream_reserved(admission.lease, source(), command_name="sample")
        self.assertEqual(await asyncio.wait_for(stream.__anext__(), timeout=1), "first")
        self.assertEqual(service.snapshot()["global_inflight"], 1)
        await stream.aclose()

        self.assertTrue(source_closed.is_set())
        self.assertEqual(service.snapshot()["global_inflight"], 0)
        self.assertTrue(admission.lease.released)

    async def test_handler_exception_releases_capacity(self):
        service = OperationLimitService()
        admission = service.try_acquire("alice", "alice")

        async def source():
            yield "first"
            raise RuntimeError("handler failed")

        stream = service.stream_reserved(admission.lease, source())
        self.assertEqual(await stream.__anext__(), "first")
        with self.assertRaisesRegex(RuntimeError, "handler failed"):
            await stream.__anext__()
        self.assertEqual(service.snapshot()["global_inflight"], 0)

    async def test_task_cancellation_releases_capacity(self):
        service = OperationLimitService()
        admission = service.try_acquire("alice", "alice")

        async def source():
            yield "first"
            await asyncio.Event().wait()

        async def consume():
            stream = service.stream_reserved(admission.lease, source())
            try:
                async for _ in stream:
                    await asyncio.Event().wait()
            finally:
                await service.close_iterator(stream)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(service.snapshot()["global_inflight"], 0)


if __name__ == "__main__":
    unittest.main()
