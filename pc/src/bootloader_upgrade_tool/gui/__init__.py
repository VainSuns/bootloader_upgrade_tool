__all__ = ["BootloaderMainWindow", "MainWindow", "main", "run"]


def __getattr__(name: str):
    if name in {"main", "run"}:
        from .app import main

        return main
    if name in {"BootloaderMainWindow", "MainWindow"}:
        from .main_window import BootloaderMainWindow

        return BootloaderMainWindow
    raise AttributeError(name)