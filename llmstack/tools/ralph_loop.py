import sys

from llmstack.config import load_config
from llmstack.core.supervisor import Supervisor
from llmstack.services.stack import ServiceStack


def main():
    config = load_config()
    services = ServiceStack(config)
    services.ensure_running()
    supervisor = Supervisor(config, config["dev_root"], services)
    supervisor.run()


if __name__ == "__main__":
    sys.exit(main())
