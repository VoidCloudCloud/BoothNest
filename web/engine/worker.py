# SPDX-License-Identifier: GPL-3.0-only
"""Private stdin/stdout transport for the maintained BoothNest engine."""
import contextlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boothlib.api import Api
from boothlib.config import Config
from boothlib.server import ALLOWED


def run(home):
    # Frozen Python does not apply PYTHONIOENCODING like the interpreter does.
    # The private RPC transport must always use UTF-8, including emoji in logs.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    api = Api(Config(home=Path(home)).load())
    api.get_state()
    output = sys.stdout
    for line in sys.stdin:
        request_id = None
        try:
            request = json.loads(line)
            request_id = request.get('id')
            method, args = request.get('method'), request.get('args', [])
            if method not in ALLOWED or not isinstance(args, list):
                raise ValueError('Unknown engine operation')
            with contextlib.redirect_stdout(sys.stderr):
                value = getattr(api, method)(*args)
            response = {'id': request_id, 'value': value}
        except Exception as error:
            response = {'id': request_id, 'error': str(error)}
        output.write(json.dumps(response, ensure_ascii=False) + '\n')
        output.flush()
    if api.busy:
        api.cancel()
        import time
        for _ in range(100):
            if not api.busy:
                break
            time.sleep(.1)


if __name__ == '__main__':
    run(sys.argv[1])
