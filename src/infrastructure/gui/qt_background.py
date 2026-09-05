from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

_active_bridges: set["_Bridge"] = set()


class _Bridge(QObject):
    """Delivers a worker's result to the GUI thread."""

    done = Signal(object)
    error = Signal(str)

    def __init__(
        self, on_done: Callable[[Any], None], on_error: Callable[[str], None]
    ) -> None:
        super().__init__()
        self._on_done = on_done
        self._on_error = on_error
        self.done.connect(self._deliver_done)
        self.error.connect(self._deliver_error)

    def _deliver_done(self, result: Any) -> None:
        try:
            self._on_done(result)
        finally:
            _active_bridges.discard(self)

    def _deliver_error(self, message: str) -> None:
        try:
            self._on_error(message)
        finally:
            _active_bridges.discard(self)


class _Worker(QRunnable):
    def __init__(self, fn: Callable[..., Any], bridge: _Bridge, args: tuple) -> None:
        super().__init__()
        self._fn = fn
        self._bridge = bridge
        self._args = args

    def run(self) -> None:
        try:
            self._bridge.done.emit(self._fn(*self._args))
        except Exception as exc:
            self._bridge.error.emit(str(exc))


def run_bg(
    fn: Callable[..., Any],
    on_done: Callable[[Any], None],
    on_error: Callable[[str], None],
    *args: Any,
) -> None:
    bridge = _Bridge(on_done, on_error)
    _active_bridges.add(bridge)
    QThreadPool.globalInstance().start(_Worker(fn, bridge, args))
