import sys

from configuronic.cli import cli
from configuronic.config import Config, _import_object_from_path


def main():
    if len(sys.argv) < 2 or not sys.argv[1].startswith('@'):
        print('Usage: python -m configuronic @path.to.module.Config [--param=value ...]', file=sys.stderr)
        sys.exit(1)

    import_path = sys.argv[1]
    sys.argv = [sys.argv[0]] + sys.argv[2:]

    obj = _import_object_from_path(import_path)

    if not isinstance(obj, Config):
        print(f'Error: {import_path} resolved to {type(obj).__name__}, expected a Config object', file=sys.stderr)
        sys.exit(1)

    cli(obj)


if __name__ == '__main__':
    main()
