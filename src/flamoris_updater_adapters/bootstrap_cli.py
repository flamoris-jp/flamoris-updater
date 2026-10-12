import argparse
import os
import sys

import uvicorn

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import dumps

from .config import load
from .self_update import Supervisor, runtime_identity
from .setup import BootstrapConfig, LocalCoordinator, helper
from .web import create_app


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve", "helper", "supervise", "check", "probe"])
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    try:
        cfg = load(BootstrapConfig, args.config)
        if args.command == "check":
            print(dumps(runtime_identity()).decode())
        elif args.command == "supervise":
            Supervisor(cfg, args.config).worker()
        elif args.command == "helper":
            helper(cfg)
        else:
            if os.geteuid() != cfg.service_uid:
                raise UpdateError("forbidden", "Run the frontend as its configured service account")
            c = LocalCoordinator(cfg)
            if args.command == "probe":
                print(dumps(c.client.call({"action": "version", "body": {}})).decode())
            else:
                uvicorn.run(
                    create_app(c, cfg.public_origin, run_worker=False, base_path=cfg.base_path),
                    host=cfg.listen_host,
                    port=cfg.listen_port,
                    proxy_headers=False,
                    access_log=False,
                )
    except UpdateError as error:
        sys.stderr.write(dumps(error.public()).decode() + "\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
