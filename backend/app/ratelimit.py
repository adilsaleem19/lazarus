"""Job-creation rate limiting: fixed one-hour windows in Redis.

Two budgets checked together: per-IP (stops one person hammering) and global
(caps total free-tier LLM spend no matter how many IPs show up). INCR+EXPIRE
is atomic enough here — the worst race over-counts by one, which only makes
the limiter marginally stricter.
"""

import time


class JobRateLimiter:
    def __init__(self, redis, *, per_ip: int, global_limit: int, window_s: int = 3600):
        self._redis = redis
        self._per_ip = per_ip
        self._global = global_limit
        self._window_s = window_s

    async def check(self, ip: str) -> str | None:
        """Charge one job attempt. Returns None if allowed, else a denial reason."""
        window = int(time.time()) // self._window_s

        ip_key = f"lazarus:rl:{window}:ip:{ip}"
        ip_count = await self._redis.incr(ip_key)
        if ip_count == 1:
            await self._redis.expire(ip_key, self._window_s)
        if ip_count > self._per_ip:
            return (
                f"rate limit: at most {self._per_ip} jobs per hour per IP — "
                "try again later"
            )

        global_key = f"lazarus:rl:{window}:global"
        global_count = await self._redis.incr(global_key)
        if global_count == 1:
            await self._redis.expire(global_key, self._window_s)
        if global_count > self._global:
            return (
                f"rate limit: Lazarus accepts at most {self._global} new jobs per hour "
                "in total — try again later"
            )
        return None
