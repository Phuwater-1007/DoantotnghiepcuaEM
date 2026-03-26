# ===== file: main_ui.py =====
"""Compatibility entrypoint.

For now the desktop app still uses the hardened CLI pipeline lifecycle so all
entrypoints behave consistently during thesis/demo runs.
"""

from vehicle_counting_system.main import main as run_cli_main


def main():
    return run_cli_main()


if __name__ == '__main__':
    raise SystemExit(main())
