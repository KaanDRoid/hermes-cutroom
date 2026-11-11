"""Detached, durable per-workspace job supervisor."""

import shutil
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
                studio._check_job_project(job)
                job.update(status="running", progress=0.05, started_at=time.time())
                studio._write_job(job)
            result = studio._perform_job(job)
            studio._complete_job(job, result)
        return 0
    except Exception as error:
        outputs = studio._job_path(job_id).parent / "outputs"
        if outputs.is_symlink():
            outputs.unlink()
        elif outputs.is_dir():
            # Unpublished outputs of a failed, stale or cancelled job are never eligible.
            shutil.rmtree(outputs)
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
