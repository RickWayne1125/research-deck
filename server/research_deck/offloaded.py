"""Files a cloud folder keeps only in the cloud, on macOS. iCloud Drive's Desktop and Documents with Optimize Mac
Storage on (or another File Provider folder) leave a placeholder on disk until a program reads the file. A program
started from Terminal or an app downloads the file then; a launchd agent does not by default, and its read fails with
"Resource deadlock avoided" (EDEADLK). So the server turns downloading on for itself when it starts (setiopolicy_np(3))."""
from __future__ import annotations

import ctypes
import logging
import os
import sys

log = logging.getLogger("research_deck")

# <sys/resource.h>
IOPOL_TYPE_VFS_MATERIALIZE_DATALESS_FILES = 3
IOPOL_SCOPE_PROCESS = 0
ON = 2                                                      # IOPOL_MATERIALIZE_DATALESS_FILES_ON
POLICIES = {0: "the system default", 1: "off", ON: "on"}


def _libc() -> ctypes.CDLL:
    lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    lib.getiopolicy_np.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.setiopolicy_np.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    return lib


def download_on_read() -> bool | None:
    """Have this process, and the agents and commands it starts, download an offloaded file when they read it.
    True once that is so, False if macOS refused (reading such a file then fails), None off macOS."""
    if sys.platform != "darwin":
        return None
    try:
        lib = _libc()
        before = lib.getiopolicy_np(IOPOL_TYPE_VFS_MATERIALIZE_DATALESS_FILES, IOPOL_SCOPE_PROCESS)
        if before != ON and lib.setiopolicy_np(IOPOL_TYPE_VFS_MATERIALIZE_DATALESS_FILES, IOPOL_SCOPE_PROCESS, ON) != 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))
    except (OSError, AttributeError) as e:
        log.warning("files that iCloud has offloaded will not be downloaded when read, so reading one fails: %s", e)
        return False
    if before != ON:
        log.info("files that iCloud has offloaded are downloaded when read (the policy was %s)", POLICIES.get(before, "unknown"))
    return True
