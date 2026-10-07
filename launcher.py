"""Entry point for the packaged executable: straight into the GUI."""


def main() -> int:
    # Velopack's install and update hooks re-run this executable and expect it
    # to exit, so boot() must run before the slow GUI import or any window.
    from mnemo_bridge.updates import boot

    boot()

    from mnemo_bridge.gui.app import run_gui

    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
