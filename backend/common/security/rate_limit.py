import redis

from fastapi import HTTPException

from config.settings import settings


r = redis.from_url(
    settings.REDIS_URL
)


def limit(
    key: str,
    max_requests=30,
    window=60,
):

    count = r.incr(
        key
    )

    if count == 1:
        r.expire(
            key,
            window,
        )

    if count > max_requests:

        raise HTTPException(
            429,
            "Too many requests",
        )