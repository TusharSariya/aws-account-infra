import argparse
from dataclasses import asdict
import json
from pathlib import Path
from .imm2 import PowerController, PowerError


def main():
    parser = argparse.ArgumentParser(description="IMM2 status and wake only")
    parser.add_argument("action", choices=["status", "ensure-on"])
    parser.add_argument("target")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        controller = PowerController(args.config, args.target)
        result = (asdict(controller.get_power()) if args.action == "status"
                  else controller.ensure_on())
        print(json.dumps(result))
    except (PowerError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Power operation failed: {exc}\n")


if __name__ == "__main__":
    main()
