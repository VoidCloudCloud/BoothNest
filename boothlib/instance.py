# SPDX-License-Identifier: GPL-3.0-only
"""OS-released exclusive lock for one writer per application data directory."""
from pathlib import Path
import os


class InstanceLock:
    def __init__(self, home: Path):
        self.path = home / ".instance.lock"
        self.file = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = self.path.open("a+b")
        if f.tell() == 0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self.file = f
        return True

    def release(self):
        if self.file:
            self.file.close()
            self.file = None
