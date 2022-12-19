# Copyright (C) 2022 The Qt Company Ltd.
# SPDX-License-Identifier: LicenseRef-Qt-Commercial OR BSD-3-Clause

from PySide6.QtCore import (Qt, QEvent, QObject, Signal, Slot)
from PySide6.QtWidgets import (QApplication, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget)

import asyncio
# import outcome
import signal
import sys
import traceback


class MainWindow(QMainWindow):

    def __init__(self, async_signal):
        super().__init__()

        self.async_signal = async_signal

        widget = QWidget()
        self.setCentralWidget(widget)

        layout = QVBoxLayout(widget)

        self.text = QLabel("The answer is 42.")
        layout.addWidget(self.text, alignment=Qt.AlignmentFlag.AlignCenter)

        async_trigger = QPushButton(text="What is the question?")
        async_trigger.clicked.connect(self.async_start)
        layout.addWidget(async_trigger, alignment=Qt.AlignmentFlag.AlignCenter)

    @Slot()
    def async_start(self):
        self.async_signal.emit()

    async def set_text(self):
        await asyncio.sleep(1)
        self.text.setText("What do you get if you multiply six by nine?")


class AsyncHelper(QObject):

    trigger_signal = Signal()

    class ReenterQtObject(QObject):
        """ This is a QObject to which an event will be posted, allowing
            Trio to resume when the event is handled. event.fn() is the
            next entry point of the Trio event loop. """
        def event(self, event):
            if event.type() == QEvent.User + 1:
                event.fn()
                return True
            return False

    class ReenterQtEvent(QEvent):
        """ This is the QEvent that will be handled by the ReenterQtObject.
            self.fn is the next entry point of the Trio event loop. """
        def __init__(self, fn):
            super().__init__(QEvent.Type(QEvent.User + 1))
            self.fn = fn

    def __init__(self, entry=None):
        super().__init__()
        self.reenter_qt = self.ReenterQtObject()
        self.entry = entry
        self.loop = asyncio.new_event_loop()

    def set_entry(self, entry):
        self.entry = entry

    @Slot()
    def launch_guest_run(self):
        """ To use asyncio and Qt together, one must run the asyncio
            event loop as a "guest" inside the Qt "host" event loop. """
        if not self.entry:
            raise Exception("No entry point for the asyncio event loop was set.")
        asyncio.set_event_loop(self.loop)
        self.loop.create_task(self.entry())
        self.loop.call_soon(self.next_guest_run_schedule)
        self.loop.run_forever()

    def continue_loop(self):
        """ This function is called by an event posted to the Qt event
            loop to restart the asyncio event loop. """
        self.loop.call_soon(self.next_guest_run_schedule)
        self.loop.run_forever()

    def next_guest_run_schedule(self):
        """ This function serves to pause and re-schedule the guest
            (asyncio) event loop inside the host (Qt) event loop. It is
            registered in asyncio as a callback to be called at the next
            iteration of the event loop. When this function runs, it
            first stops the asyncio event loop, then by posting an event
            on the Qt event loop, it both relinquishes to Qt's event
            loop and also schedules the asyncio event loop to run again.
            Upon handling this event, a function will be called that
            resumes the asyncio event loop. """
        self.loop.stop()
        QApplication.postEvent(self.reenter_qt, self.ReenterQtEvent(self.continue_loop))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    async_helper = AsyncHelper()
    main_window = MainWindow(async_helper.trigger_signal)
    async_helper.set_entry(main_window.set_text)

    # This establishes the entry point for the Trio guest run. It varies
    # depending on how and when its event loop is to be triggered, e.g.,
    # at a specific moment like a button press (as here) or rather from
    # the beginning.
    async_helper.trigger_signal.connect(async_helper.launch_guest_run)

    main_window.show()

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app.exec()
