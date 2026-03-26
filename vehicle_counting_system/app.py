"""
Application entrypoint alias.

The GUI scaffold is not i
mplemented yet, so this module delegates to the
production CLI/OpenCV pipeline entrypoint to keep startup behavior consistent.
"""

from vehicle_counting_system.main import main as run_cli_main

def main() -> None:
    raise SystemExit(run_cli_main())


if __name__ == "__main__":
    main()

