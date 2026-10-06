"""Bounded byte collection for the owned, non-spawning SDK helper."""
import subprocess
import threading
import time

LIMIT = 1024 * 1024


def bounded_run(command, *, cwd, env, timeout, **unused):
    chunks = [bytearray(), bytearray()]
    lock = threading.Lock()
    overflow = threading.Event()
    errors = []
    proc = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def collect(stream, index):
        try:
            while True:
                data = stream.read(4096)
                if not data:
                    break
                with lock:
                    remaining = LIMIT - sum(map(len, chunks))
                    chunks[index].extend(data[:remaining])
                    if len(data) > remaining:
                        overflow.set()
                        break
        except Exception as exc:
            errors.append(repr(exc))
            overflow.set()
        finally:
            stream.close()

    threads = [threading.Thread(target=collect, args=(stream, i), daemon=True)
               for i, stream in enumerate((proc.stdout, proc.stderr))]
    timed_out = False
    try:
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + timeout
        while proc.poll() is None or any(t.is_alive() for t in threads):
            if overflow.is_set() or time.monotonic() >= deadline:
                timed_out = not overflow.is_set()
                if proc.poll() is None:
                    proc.kill()
                break
            time.sleep(.005)
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=2)
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=2)
    if any(t.is_alive() for t in threads):
        raise RuntimeError('owned helper byte collectors did not finish')
    stdout, stderr = map(bytes, chunks)
    if timed_out:
        raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
    result = subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
    result.output_limit_exceeded = overflow.is_set()
    result.collection_errors = errors
    return result
