"""Lifecycle for the opt-in Trobrat local telemetry and control gateway."""

from __future__ import annotations

import threading

from . import bernin_control


class TrobratService:
    """Run the validated symbolic S7 gateway inside RoastArtisan.

    Constructing or starting this service does not issue PLC writes. Commands
    still require an explicit local Modbus request and pass the gateway guards.
    """

    def __init__(self, host: str) -> None:
        self.host = host
        self.gateway = bernin_control.ControlGateway(bernin_control.ControlReader(host))
        self.stop_event = threading.Event()
        self.server: bernin_control.Server | None = None
        self.poll_thread: threading.Thread | None = None
        self.server_thread: threading.Thread | None = None

    def start(self) -> None:
        # Bind first: a previously started standalone client must not silently
        # compete with this instance on the local Modbus port.
        self.server = bernin_control.Server(self.gateway)
        try:
            self.poll_thread = threading.Thread(
                target=bernin_control.poll,
                args=(self.gateway, self.stop_event),
                name='trobrat-poll',
                daemon=True,
            )
            self.server_thread = threading.Thread(
                target=self.server.serve_forever,
                name='trobrat-modbus',
                daemon=True,
            )
            self.poll_thread.start()
            self.server_thread.start()
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        self.gateway.stop_commands()
        self.stop_event.set()
        if self.server is not None:
            if self.server_thread is not None and self.server_thread.is_alive():
                self.server.shutdown()
            self.server.server_close()
            if self.server_thread is not None and self.server_thread.is_alive():
                self.server_thread.join(timeout=3)
        if self.poll_thread is not None:
            self.poll_thread.join(timeout=3)
        self.gateway.close()
