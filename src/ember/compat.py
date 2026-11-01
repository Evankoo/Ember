"""The few file operations that differ on Windows; everything else stays ordinary Python."""
from __future__ import annotations

import errno
import os
from pathlib import Path
import re
import time

WINDOWS = os.name == "nt"
# Files that Windows would run rather than open; a workspace document must never start a program.
RUNNABLE_SUFFIXES = frozenset({".bat", ".cmd", ".com", ".cpl", ".exe", ".hta", ".js", ".jse", ".lnk", ".msc",
                               ".msi", ".pif", ".ps1", ".reg", ".scr", ".url", ".vbe", ".vbs", ".wsf", ".wsh"})
_RESERVED_NAME = re.compile(r"(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(\..*)?", re.IGNORECASE)
_REPLACE_RETRY_SECONDS = 2.0
_MOUNT_POINT_TAG = 0xA0000003  # IO_REPARSE_TAG_MOUNT_POINT; the stat module defines it only on Windows.


def lock_file(fd: int, *, blocking: bool = True) -> None:
    """Hold an exclusive lock until the descriptor closes; BlockingIOError when busy and not blocking."""
    if not WINDOWS:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return
    import msvcrt
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EDEADLK):
                raise
            if not blocking:
                raise BlockingIOError(errno.EWOULDBLOCK, "文件已被锁定") from error
            time.sleep(0.05)


def publish_new(temporary, target) -> None:
    """Move a finished file to a new name, raising FileExistsError instead of replacing anything."""
    if WINDOWS:
        os.rename(temporary, target)  # Unlike POSIX, Windows rename refuses an existing target.
        return
    os.link(temporary, target, follow_symlinks=False)
    os.unlink(temporary)


def replace_file(source, target) -> None:
    """Atomic replace that waits briefly for the antivirus or editor holding the file on Windows."""
    deadline = time.monotonic() + _REPLACE_RETRY_SECONDS
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if not WINDOWS or time.monotonic() >= deadline:
                raise
            time.sleep(0.1)


def is_junction(path: Path) -> bool:
    """Directory junctions redirect like symlinks but is_symlink() misses them before Python 3.12."""
    if not WINDOWS:
        return False
    try:
        return getattr(os.lstat(path), "st_reparse_tag", 0) == _MOUNT_POINT_TAG
    except OSError:
        return False


def windows_name_allowed(part: str) -> bool:
    """False for a name Windows would reinterpret: a drive, data stream, device or trimmed name."""
    return not (any(char in '<>:"|?*' or ord(char) < 32 for char in part)
                or part[-1:] in (".", " ") or _RESERVED_NAME.fullmatch(part))
