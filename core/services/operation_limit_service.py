"""Bounded admission control for foreground game commands.

The service intentionally owns only short-lived in-memory state. Background
automation continues to use its existing business cooldowns and does not pass
through this foreground command limiter.
"""

import asyncio
import json
import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Dict, Optional, Tuple


logger = logging.getLogger(__name__)


@dataclass
class _TokenBucket:
    tokens: float
    updated_at: float
    last_seen: float


@dataclass
class OperationLease:
    """An idempotently releasable reservation for one foreground command."""

    service: "OperationLimitService"
    user_ids: Tuple[str, ...]
    released: bool = False

    def release(self) -> None:
        self.service._release_lease(self)


@dataclass(frozen=True)
class AdmissionResult:
    accepted: bool
    lease: Optional[OperationLease] = None
    reason: Optional[str] = None
    retry_after: float = 0.0
    should_notify: bool = False
    notice: Optional[str] = None


class OperationLimitService:
    """Apply a per-sender token bucket and bounded in-flight reservations."""

    STATE_TTL_SECONDS = 15 * 60
    CLEANUP_INTERVAL_SECONDS = 60

    def __init__(self, config: Optional[dict] = None, clock: Optional[Callable[[], float]] = None):
        config = config if isinstance(config, dict) else {}
        self.enabled = bool(config.get("enabled", True))
        self.user_interval_seconds = self._number(config.get("user_interval_seconds", 2), 2.0, minimum=0.0)
        self.user_burst = self._integer(config.get("user_burst", 2), 2, minimum=1)
        self.user_max_inflight = self._integer(config.get("user_max_inflight", 1), 1, minimum=0)
        self.global_max_inflight = self._integer(config.get("global_max_inflight", 4), 4, minimum=0)
        self.reject_notice_interval_seconds = self._number(
            config.get("reject_notice_interval_seconds", 5), 5.0, minimum=0.0
        )
        self.max_draws_per_request = self._integer(
            config.get("max_draws_per_request", 100), 100, minimum=1
        )
        self.user_overrides = self._parse_overrides(config.get("user_overrides", {}))
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._buckets: Dict[str, _TokenBucket] = {}
        self._inflight: Dict[str, int] = {}
        self._last_notice: Dict[str, float] = {}
        self._last_cleanup = self._clock()
        self._global_inflight = 0
        self.metrics = {
            "accepted": 0,
            "rejected_global": 0,
            "rejected_user_inflight": 0,
            "rejected_rate": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "command_elapsed_seconds": 0.0,
        }

    @staticmethod
    def _number(value: Any, default: float, minimum: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(number):
            return default
        return max(minimum, number)

    @staticmethod
    def _integer(value: Any, default: int, minimum: int = 0) -> int:
        try:
            return max(minimum, int(value))
        except (TypeError, ValueError, OverflowError):
            return default

    @classmethod
    def _parse_overrides(cls, value: Any) -> Dict[str, Dict[str, Any]]:
        # AstrBot's schema editor does not provide a dynamic-key editor, so the
        # schema exposes this field as JSON text while runtime also accepts a
        # native mapping from programmatic configurations.
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                logger.warning("operation_limit.user_overrides is not valid JSON; ignoring overrides")
                return {}
        if not isinstance(value, dict):
            return {}

        overrides: Dict[str, Dict[str, Any]] = {}
        for user_id, raw in value.items():
            if not isinstance(raw, dict):
                continue
            normalized: Dict[str, Any] = {}
            aliases = {
                "interval_seconds": "interval_seconds",
                "user_interval_seconds": "interval_seconds",
                "burst": "burst",
                "user_burst": "burst",
                "max_inflight": "max_inflight",
                "user_max_inflight": "max_inflight",
            }
            for key, canonical in aliases.items():
                if key in raw and canonical not in normalized:
                    normalized[canonical] = raw[key]
            overrides[str(user_id)] = normalized
        return overrides

    def _user_limits(self, user_id: str) -> Tuple[float, int, int]:
        override = self.user_overrides.get(str(user_id), {})
        interval = self._number(
            override.get("interval_seconds", self.user_interval_seconds),
            self.user_interval_seconds,
            minimum=0.0,
        )
        burst = self._integer(override.get("burst", self.user_burst), self.user_burst, minimum=1)
        max_inflight = self._integer(
            override.get("max_inflight", self.user_max_inflight), self.user_max_inflight, minimum=0
        )
        return interval, burst, max_inflight

    def try_acquire(self, sender_id: Any, effective_user_id: Any = None) -> AdmissionResult:
        """Atomically check and reserve capacity without waiting in a queue.

        Tokens are charged to the real sender only. A distinct effective user
        used by an impersonated command also receives an in-flight reservation.
        """
        sender = str(sender_id or "unknown")
        effective = str(effective_user_id or sender)
        user_ids = tuple(dict.fromkeys((sender, effective)))
        now = self._clock()

        with self._lock:
            self._cleanup_if_due(now)

            if self.global_max_inflight > 0 and self._global_inflight >= self.global_max_inflight:
                return self._reject(sender, "global", now)

            if self.enabled:
                for user_id in user_ids:
                    _, _, max_inflight = self._user_limits(user_id)
                    if max_inflight > 0 and self._inflight.get(user_id, 0) >= max_inflight:
                        return self._reject(sender, "user_inflight", now)

                interval, burst, _ = self._user_limits(sender)
                bucket = None
                if interval > 0:
                    bucket = self._refill_bucket(sender, interval, burst, now)
                    if bucket.tokens < 1.0:
                        retry_after = max(0.0, interval * (1.0 - bucket.tokens))
                        return self._reject(sender, "rate", now, retry_after)

            if self.enabled and interval > 0:
                # `interval` is assigned in the enabled branch above.
                bucket.tokens -= 1.0
                bucket.last_seen = now

            self._global_inflight += 1
            for user_id in user_ids:
                self._inflight[user_id] = self._inflight.get(user_id, 0) + 1
            self.metrics["accepted"] += 1
            return AdmissionResult(True, lease=OperationLease(self, user_ids))

    def _refill_bucket(self, user_id: str, interval: float, burst: int, now: float) -> _TokenBucket:
        bucket = self._buckets.get(user_id)
        if bucket is None:
            bucket = _TokenBucket(float(burst), now, now)
            self._buckets[user_id] = bucket
            return bucket
        elapsed = max(0.0, now - bucket.updated_at)
        bucket.tokens = min(float(burst), bucket.tokens + elapsed / interval)
        bucket.updated_at = now
        bucket.last_seen = now
        return bucket

    def _reject(
        self,
        sender: str,
        reason: str,
        now: float,
        retry_after: float = 0.0,
    ) -> AdmissionResult:
        metric_key = {
            "global": "rejected_global",
            "user_inflight": "rejected_user_inflight",
            "rate": "rejected_rate",
        }[reason]
        self.metrics[metric_key] += 1
        last_notice = self._last_notice.get(sender)
        should_notify = (
            self.reject_notice_interval_seconds <= 0
            or last_notice is None
            or now - last_notice >= self.reject_notice_interval_seconds
        )
        if should_notify:
            self._last_notice[sender] = now

        if reason == "rate":
            wait_seconds = max(1, int(math.ceil(retry_after)))
            notice = "⏳ 操作太快，请{}秒后重试。".format(wait_seconds)
        elif reason == "user_inflight":
            notice = "⏳ 当前操作尚未完成，请稍后重试。"
        else:
            notice = "⏳ 当前操作较多，请稍后重试。"
        return AdmissionResult(
            False,
            reason=reason,
            retry_after=retry_after,
            should_notify=should_notify,
            notice=notice if should_notify else None,
        )

    def _release_lease(self, lease: OperationLease) -> None:
        with self._lock:
            if lease.released:
                return
            lease.released = True
            self._global_inflight = max(0, self._global_inflight - 1)
            for user_id in lease.user_ids:
                count = self._inflight.get(user_id, 0)
                if count <= 1:
                    self._inflight.pop(user_id, None)
                else:
                    self._inflight[user_id] = count - 1

    def _cleanup_if_due(self, now: float) -> None:
        if now - self._last_cleanup < self.CLEANUP_INTERVAL_SECONDS:
            return
        expired_before = now - self.STATE_TTL_SECONDS
        for user_id, bucket in list(self._buckets.items()):
            if user_id not in self._inflight and bucket.last_seen < expired_before:
                self._buckets.pop(user_id, None)
        for user_id, timestamp in list(self._last_notice.items()):
            if timestamp < expired_before:
                self._last_notice.pop(user_id, None)
        self._last_cleanup = now

    async def stream_reserved(
        self,
        lease: OperationLease,
        iterator: AsyncIterator[Any],
        after: Optional[Callable[[], AsyncIterator[Any]]] = None,
        command_name: str = "unknown",
    ) -> AsyncIterator[Any]:
        """Yield a command and its optional follow-up while holding capacity.

        The source iterators are explicitly closed on completion, cancellation,
        or consumer close. The lease is always released, including exceptions
        raised while the caller consumes the yielded results.
        """
        started = self._clock()
        command_stream = iterator.__aiter__()
        active_iterators = [command_stream]
        outcome = "completed"
        try:
            while True:
                try:
                    item = await command_stream.__anext__()
                except StopAsyncIteration:
                    break
                yield item
            if after is not None:
                after_stream = after().__aiter__()
                active_iterators.append(after_stream)
                while True:
                    try:
                        item = await after_stream.__anext__()
                    except StopAsyncIteration:
                        break
                    yield item
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except GeneratorExit:
            outcome = "cancelled"
            raise
        except BaseException:
            outcome = "failed"
            raise
        finally:
            try:
                for source in reversed(active_iterators):
                    await self._close_iterator(source)
            finally:
                lease.release()
                elapsed = max(0.0, self._clock() - started)
                with self._lock:
                    self.metrics["completed" if outcome == "completed" else outcome] += 1
                    self.metrics["command_elapsed_seconds"] += elapsed
                logger.debug(
                    "Foreground command %s finished with %s in %.3fs",
                    command_name,
                    outcome,
                    elapsed,
                )

    @staticmethod
    async def _close_iterator(iterator: AsyncIterator[Any]) -> None:
        close = getattr(iterator, "aclose", None)
        if close is None:
            return
        try:
            await close()
        except BaseException as exc:
            # Always proceed to release the lease. An active cancellation or
            # handler error still propagates from the outer generator.
            logger.debug("Unable to close command result generator cleanly: %r", exc)

    async def close_iterator(self, iterator: AsyncIterator[Any]) -> None:
        """Close a nested command stream when its outer consumer stops early."""
        await self._close_iterator(iterator)

    def snapshot(self) -> Dict[str, Any]:
        """Return a small diagnostics snapshot for tests and operator checks."""
        with self._lock:
            return {
                **self.metrics,
                "global_inflight": self._global_inflight,
                "tracked_buckets": len(self._buckets),
                "tracked_notices": len(self._last_notice),
            }
