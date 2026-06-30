import logging
import threading
from queue import Empty, Queue

logger = logging.getLogger(__name__)

_worker = None


class WormWorker:
    def __init__(self):
        self._queue = Queue()
        self._thread = None
        self._default_app = None
        self._cancel_events = {}
        self._lock = threading.Lock()
        self._started = False

    def init_app(self, app):
        self._default_app = app
        if not self._started:
            self._thread = threading.Thread(target=self._run, name="worm-worker", daemon=True)
            self._thread.start()
            self._started = True
        self._schedule_resume(app)

    def _schedule_resume(self, app):
        if app.config.get("TESTING"):
            return

        def resume():
            try:
                with app.app_context():
                    from .service import get_library_service

                    get_library_service().recover_worm_jobs(
                        lambda upload_id, job_id: self.enqueue(upload_id, job_id, app)
                    )
            except Exception:
                app.logger.exception("Worm job recovery failed; web app continues without resuming jobs.")

        threading.Thread(target=resume, name="worm-resume", daemon=True).start()

    def register_job(self, job_id):
        with self._lock:
            event = self._cancel_events.get(job_id)
            if event is None:
                event = threading.Event()
                self._cancel_events[job_id] = event
            return event

    def request_cancel(self, job_id):
        with self._lock:
            event = self._cancel_events.get(job_id)
            if event is not None:
                event.set()
                return True
            return False

    def clear_job(self, job_id):
        with self._lock:
            self._cancel_events.pop(job_id, None)

    def is_cancelled(self, job_id):
        with self._lock:
            event = self._cancel_events.get(job_id)
            return bool(event and event.is_set())

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
            cancel_event = self.register_job(job_id)
            try:
                with app.app_context():
                    from .service import get_library_service

                    get_library_service().execute_worm_job(
                        upload_id,
                        job_id,
                        cancel_check=cancel_event.is_set,
                    )
            except Exception:
                try:
                    app.logger.exception(
                        "Unhandled worm worker failure upload_id=%s job_id=%s",
                        upload_id,
                        job_id,
                    )
                except Exception:
                    logger.exception(
                        "Unhandled worm worker failure upload_id=%s job_id=%s",
                        upload_id,
                        job_id,
                    )
            finally:
                self.clear_job(job_id)
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


def reset_worm_worker():
    global _worker
    _worker = None


def init_worm_worker_safe(app):
    try:
        if app.config.get("TESTING"):
            existing = _worker
            if existing is not None:
                existing.drain(timeout=5)
                reset_worm_worker()
        get_worm_worker().init_app(app)
    except Exception:
        app.logger.exception("Worm worker failed to initialize; web app continues without background processing.")
