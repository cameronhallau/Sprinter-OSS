from __future__ import annotations

import asyncio
import logging
import signal
import time

from sprinter.config import Settings
from sprinter.engine import Container
from sprinter.logging import configure_logging

LOGGER = logging.getLogger("sprinter.worker")


async def run_worker(settings: Settings | None = None, container: Container | None = None) -> None:
    settings = settings or Settings()
    settings.database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    settings.validate_runtime("worker")
    configure_logging(settings.log_level)
    container = container or Container(settings)
    try:
        initial_pi = await container.pi.probe()
    except Exception as exc:
        container.db.heartbeat(False, pi_error=str(exc))
        LOGGER.critical("pi_startup_probe_failed", extra={"error": str(exc)})
        raise RuntimeError("Pi startup probe failed") from exc
    container.db.heartbeat(True, details=initial_pi)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    recovered = container.db.recover_abandoned_jobs()
    LOGGER.info("worker_started", extra={"recovered_jobs": recovered})
    next_probe = 0.0
    next_purge = 0.0
    pi_ready = True
    pi_error = ""
    while not stop.is_set():
        now = time.monotonic()
        if now >= next_probe:
            try:
                details = await container.pi.probe()
                pi_ready = True
                pi_error = ""
                container.db.heartbeat(True, details=details)
            except Exception as exc:
                pi_ready = False
                pi_error = str(exc)
                container.db.heartbeat(False, pi_error=pi_error)
                LOGGER.error("pi_probe_failed", extra={"error": pi_error})
            next_probe = now + settings.pi_probe_interval_seconds
        else:
            container.db.heartbeat(pi_ready, pi_error=pi_error)
        if pi_ready:
            result = await container.process_next_job()
            if result.get("processed"):
                LOGGER.info("job_processed", extra=result)
        deliveries = await container.flush_outbox()
        if deliveries["sent"] or deliveries["failed"]:
            LOGGER.info("outbox_flushed", extra=deliveries)
        if now >= next_purge:
            LOGGER.info("retention_purged", extra=container.db.purge())
            next_purge = now + 86_400
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
        except TimeoutError:
            pass
    LOGGER.info("worker_stopped")


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
