"""Detached, durable per-workspace job supervisor."""

import sys
import time

from .studio import Studio


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    studio = Studio(argv[0])
    job_id = argv[1]

    def cancelled():
        return studio.job(job_id).get("cancel_requested", False)

    try:
        with studio._lock("queue", timeout=3600, cancelled=cancelled):
            if cancelled():
                raise InterruptedError("Job cancelled")
            with studio._lock():
                job = studio.job(job_id)
                job.update(status="running", progress=0.05, started_at=time.time())
                studio._write_job(job)
            result = studio._perform_job(job)
            if cancelled():
                raise InterruptedError("Job cancelled")
            with studio._lock():
                current = studio.get(job["project_id"])
                if current["revision"] != job["revision"]:
                    raise ValueError(
                        "Project changed while this job was running; retry on the current revision"
                    )
                studio._check_source(current)
                job = studio.job(job_id)
                job.update(
                    status="completed",
                    progress=1.0,
                    result=result,
                    completed_at=time.time(),
                )
                studio._write_job(job)
        return 0
    except Exception as error:
        with studio._lock():
            job = studio.job(job_id)
            job.update(
                status="cancelled" if isinstance(error, InterruptedError) else "failed",
                error=str(error),
                completed_at=time.time(),
            )
            studio._write_job(job)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
