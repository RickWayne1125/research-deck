"""Files iCloud has offloaded (research_deck/offloaded.py): the server has macOS download one when it reads it."""
import ctypes
import errno
import logging
import sys

import pytest

from research_deck import offloaded

KIND, PROCESS = offloaded.IOPOL_TYPE_VFS_MATERIALIZE_DATALESS_FILES, offloaded.IOPOL_SCOPE_PROCESS


def test_off_macos_nothing_is_called(monkeypatch):
    monkeypatch.setattr(offloaded.sys, "platform", "linux")
    monkeypatch.setattr(offloaded, "_libc", lambda: pytest.fail("no system call off macOS"))
    assert offloaded.download_on_read() is None


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_a_process_that_would_not_download_offloaded_files_does_after_the_call():
    lib = offloaded._libc()
    before = lib.getiopolicy_np(KIND, PROCESS)
    try:
        assert lib.setiopolicy_np(KIND, PROCESS, 1) == 0                # off: how launchd starts an agent by default
        assert offloaded.download_on_read() is True
        assert lib.getiopolicy_np(KIND, PROCESS) == offloaded.ON
        assert offloaded.download_on_read() is True                      # already on: nothing to change
    finally:
        lib.setiopolicy_np(KIND, PROCESS, max(before, 0))


def test_when_macos_refuses_the_log_says_so(monkeypatch, caplog):
    class Refusing:
        def getiopolicy_np(self, kind, scope):
            return 1

        def setiopolicy_np(self, kind, scope, policy):
            ctypes.set_errno(errno.EPERM)
            return -1

    monkeypatch.setattr(offloaded.sys, "platform", "darwin")
    monkeypatch.setattr(offloaded, "_libc", Refusing)
    with caplog.at_level(logging.WARNING, logger="research_deck"):
        assert offloaded.download_on_read() is False
    assert "will not be downloaded" in caplog.text and "Operation not permitted" in caplog.text
