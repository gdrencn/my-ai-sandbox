"""One probe source shared by checkout and self-contained tester archives."""
from importlib.resources import files
from pathlib import Path


def source_bytes(name):
    if name not in ('guest_security_probe.py', 'host_security_probe.py'):
        raise ValueError('Unknown guest probe asset')
    packaged = files('tests').joinpath(name)
    if packaged.is_file():
        return packaged.read_bytes()
    return (Path(__file__).resolve().parents[1] / 'test' / name).read_bytes()
