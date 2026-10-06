"""Advisory file locks that work on POSIX (fcntl.flock) and Windows (msvcrt.locking).

    from thirty.filelock import lock, unlock, LockBusy
    with open(path, "a") as f:
        lock(f, exclusive=True, blocking=True)   # raises LockBusy when blocking=False and the lock is held
        ...
        unlock(f)

The hackathon code used fcntl directly; the desktop app also ships on Windows, where fcntl does not exist.
Windows locks a byte range, so every caller locks the same first byte of the lock file."""
import os

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt


class LockBusy(OSError):
    pass


def lock(f, exclusive=True, blocking=True):
    if fcntl is not None:
        flags = (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(f, flags)
        except BlockingIOError as e:
            raise LockBusy(str(e)) from e
        return
    # Windows: msvcrt has no shared lock; both kinds take the exclusive byte lock
    f.seek(0)
    mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK  # LK_LOCK retries ~10 s then raises
    while True:
        try:
            msvcrt.locking(f.fileno(), mode, 1)
            return
        except OSError as e:
            if not blocking:
                raise LockBusy(str(e)) from e


def unlock(f):
    if fcntl is not None:
        fcntl.flock(f, fcntl.LOCK_UN)
        return
    try:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


def is_posix():
    return fcntl is not None and os.name == "posix"
