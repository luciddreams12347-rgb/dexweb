import threading
from queue import Empty, Queue

_worker = None


class WormWorker:
    def __init__(self):
        self._queue = Queue()
        self._thread = None
        self._default_app = None

    def init_app(self, app):
        self._default_app = app
        if self._thread and self._thread.is_alive():
            with app.app_context():
                from .service import get_library_service

                get_library_service().resume_pending_worm_jobs(
                    lambda upload_id, job_id: self.enqueue(upload_id, job_id, app)
                )
            return
        self._thread = threading.Thread(target=self._run, name="worm-worker", daemon=True)
        self._thread.start()
        with app.app_context():
            from .service import get_library_service

            get_library_service().resume_pending_worm_jobs(
                lambda upload_id, job_id: self.enqueue(upload_id, job_id, app)
            )

    def enqueue(self, upload_id, job_id, app=None):
        self._queue.put((app or self._default_app, upload_id, job_id))

    def _run(self):
        while True:
            try:
                app, upload_id, job_id = self._queue.get(timeout=1)
            except Empty:
                continue
            if app is None:
                self._queue.task_done()
                continue
            with app.app_context():
                try:
                    from .service import get_library_service

                    get_library_service().execute_worm_job(upload_id, job_id)
                except Exception:
                    app.logger.exception(
                        "Unhandled worm worker failure upload_id=%s job_id=%s",
                        upload_id,
                        job_id,
                    )
            self._queue.task_done()

    def drain(self, timeout=10):
        if timeout is None:
            self._queue.join()
            return
        finished = threading.Event()

        def waiter():
            self._queue.join()
            finished.set()

        threading.Thread(target=waiter, daemon=True).start()
        finished.wait(timeout=timeout)


def get_worm_worker():
    global _worker
    if _worker is None:
        _worker = WormWorker()
    return _worker
