from launch_tradelab import ensure_dependencies

if __name__ == "__main__":
    if ensure_dependencies():
        from tradelab.ui.app import run_app
        run_app()
