import os
import subprocess
import tempfile

from flamoris_update_core.errors import UpdateError


def bounded_command(
    argv: list[str], timeout: int = 30, limit: int = 256 * 1024, check=True
) -> bytes:
    """Profile-selected argv only; never shell or inherited application environment."""
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=errors,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
            close_fds=True,
        )
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Systemctl/Docker are clients: killing the client does not establish effect outcome.
            process.kill()
            process.wait()
            raise UpdateError("outcome_unknown", "Typed lifecycle command timed out") from None
        if os.fstat(output.fileno()).st_size > limit or os.fstat(errors.fileno()).st_size > limit:
            raise UpdateError("outcome_unknown", "Typed command exceeded diagnostic limit")
        if check and process.returncode != 0:
            raise UpdateError(
                "outcome_unknown", "Typed lifecycle command did not confirm completion"
            )
        output.seek(0)
        return output.read(limit)
