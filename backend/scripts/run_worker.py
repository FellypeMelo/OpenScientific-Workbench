"""RQ worker entrypoint for the local HPC job queue backend (`HPC_BACKEND=local`).

Why this script instead of the bare `rq worker osw-jobs` CLI command: RQ's
CLI resolves its Redis connection from `-u/--url` (envvar `RQ_REDIS_URL`) or a
`-c/--config` settings module -- neither of which lines up with this
project's own `REDIS_URL` env var / `src.infrastructure.config.settings`
(pydantic-settings, `.env`-file aware, shared by every other adapter in this
codebase). Running the bare CLI with no flags falls back to RQ's own
`Redis()` default (`localhost:6379`), which is WRONG inside
`docker-compose.yml`'s network -- the worker container needs to reach the
`redis` service by its Compose service name, exactly what
`settings.REDIS_URL` (`redis://redis:6379/0` in that file) already encodes.
This script builds the connection from that SAME setting, so the worker
process always agrees with the API process on which Redis it is talking to.

Usage (matches `docker-compose.yml`'s `worker` service and
`Dockerfile`'s `WORKDIR /app` + `PYTHONPATH=/app` layout):

    python scripts/run_worker.py

Consumes the `"osw-jobs"` queue -- see
`src/infrastructure/hpc/local_job_dispatcher.py` for what gets enqueued onto
it (`LocalJobDispatcher.dispatch`) and what actually runs each job
(`run_sandboxed_job`, which shells the work out through the same real
`BubblewrapSandboxDriver` sandbox RF-005 DAG-node execution uses).
"""
import logging

import redis
from rq import Worker

from src.infrastructure.config import settings
from src.infrastructure.hpc.local_job_dispatcher import QUEUE_NAME

logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


def main() -> None:
    connection = redis.from_url(settings.REDIS_URL)
    worker = Worker([QUEUE_NAME], connection=connection)
    logger.info(
        "Starting RQ worker on queue %r against REDIS_URL=%s", QUEUE_NAME, settings.REDIS_URL
    )
    worker.work()


if __name__ == "__main__":
    main()
