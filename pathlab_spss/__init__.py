"""PathLab menu extension for IBM SPSS Statistics 27 and later."""

__version__ = "0.2.2"


def run_dialog(*args, **kwargs):
    # Keep the extension/menu importable before numerical dependencies are installed.
    from .adapter import run_dialog as execute
    return execute(*args, **kwargs)


def run(*args, **kwargs):
    from .adapter import run as execute
    return execute(*args, **kwargs)
