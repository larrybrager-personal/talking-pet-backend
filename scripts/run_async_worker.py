import argparse
import asyncio
import logging
import uuid

import main


async def _run_loop(limit: int, poll_interval: float, worker_id: str) -> None:
    while True:
        claimed = await main.run_async_worker_once(worker_id=worker_id, limit=limit)
        if not claimed:
            await asyncio.sleep(poll_interval)


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="Run Talking Pet async queue worker")
    parser.add_argument("--once", action="store_true", help="Process at most one batch then exit")
    parser.add_argument("--limit", type=int, default=1, help="Max jobs to claim per batch")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=main.ASYNC_JOB_POLL_INTERVAL_SEC,
        help="Seconds to sleep between empty polls",
    )
    parser.add_argument(
        "--worker-id",
        default=f"worker-{uuid.uuid4()}",
        help="Stable worker identity for job locks/logging",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    if args.once:
        asyncio.run(main.run_async_worker_once(worker_id=args.worker_id, limit=args.limit))
        return

    asyncio.run(_run_loop(args.limit, args.poll_interval, args.worker_id))


if __name__ == "__main__":
    main_cli()
