import os
import selectors
import subprocess
import time

from flamoris_update_core.errors import UpdateError


def bounded_command(
    argv: list[str], timeout: int = 30, limit: int = 256 * 1024, check=True
) -> bytes:
    """Stream bounded diagnostics; terminating a client never proves the effect outcome."""
    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
        close_fds=True,
    )
    output = bytearray()
    sizes = {process.stdout: 0, process.stderr: 0}
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            for stream in sizes:
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise UpdateError("outcome_unknown", "Typed lifecycle command timed out")
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fileobj.fileno(), 64 * 1024)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    sizes[key.fileobj] += len(chunk)
                    if sizes[key.fileobj] > limit:
                        raise UpdateError(
                            "outcome_unknown", "Typed command exceeded diagnostic limit"
                        )
                    if key.fileobj is process.stdout:
                        output.extend(chunk)
            try:
                process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise UpdateError("outcome_unknown", "Typed lifecycle command timed out") from None
        if check and process.returncode != 0:
            raise UpdateError(
                "outcome_unknown", "Typed lifecycle command did not confirm completion"
            )
        return bytes(output)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
        process.stderr.close()
