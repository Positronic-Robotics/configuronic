import inspect
import sys

import fire

from configuronic.config import Config


def _get_required_args_recursive(config: Config, prefix: str = '') -> list[str]:
    sig = inspect.signature(config.target)
    required_args = []

    for i, (name, param) in enumerate(sig.parameters.items()):
        if param.default != inspect.Parameter.empty:
            continue
        if param.name in config.kwargs:
            if isinstance(config.kwargs[param.name], Config):
                required_args.extend(_get_required_args_recursive(config.kwargs[param.name], f'{prefix}{name}.'))
            if isinstance(config.kwargs[param.name], list | tuple):
                for i, item in enumerate(config.kwargs[param.name]):
                    if isinstance(item, Config):
                        required_args.extend(_get_required_args_recursive(item, f'{prefix}{name}.{i}.'))
            if isinstance(config.kwargs[param.name], dict):
                for k, v in config.kwargs[param.name].items():
                    if isinstance(v, Config):
                        required_args.extend(_get_required_args_recursive(v, f'{prefix}{name}.{k}.'))
            continue
        if i < len(config.args):
            continue
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            # var positional args are not required
            continue
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            # var keyword args are not required
            continue

        required_args.append(f'{prefix}{name}')
    return required_args


def get_required_args(config: Config) -> list[str]:
    """
    Get the list of required arguments to instantiate the target callable.

    Returns:
        List of required argument names (excluding those with default values and those that are already set).
    """
    return _get_required_args_recursive(config, '')


def _cli_single_command(config: Config, is_command_first: bool = False):
    assert 'help' not in config.kwargs, "Config contains 'help' argument. This is reserved for the help flag."

    def _run_and_help(help: bool = False, **kwargs):
        overriden_config = config.override(**kwargs)
        if help:
            if hasattr(overriden_config.target, '__doc__') and overriden_config.target.__doc__:
                print(overriden_config.target.__doc__)
                print('=' * 140)

            print('Config:')
            for arg in get_required_args(overriden_config):
                print(f'{arg}: <REQUIRED>')
            print()
            print(str(overriden_config))
        else:
            return overriden_config.instantiate()

    if is_command_first:
        # HACK: Add fake first argument to a function signature so the `Fire` threat it as a positional argument
        def _run_and_help_wrapper(_command: str=None, help: bool = False, **kwargs):
            return _run_and_help(help, **kwargs)

        return _run_and_help_wrapper
    else:
        return _run_and_help


def _cli_multiple_commands(commands_config: dict[str, Config]):
    def _run_and_help(_command: str = None, help: bool = False, **kwargs):
        args = sys.argv[1:]
        # Handle help flag manually to choose a proper function for fire.Fire
        if len(args) == 0 or args[0] == '--help':
            print('Commands:')
            for command in commands_config:
                target_command_doc = commands_config[command].target.__doc__
                if target_command_doc:
                    first_line_of_doc = target_command_doc.split('\n')[0]
                    command_description = f' # {first_line_of_doc}'
                else:
                    command_description = ''
                required_args = get_required_args(commands_config[command])
                required_args_str = ' '.join([f'--{arg}=<REQUIRED>' for arg in required_args])
                print(f'python {sys.argv[0]} {command} {required_args_str}{command_description}')
            print()
        elif args[0] in commands_config:
            return _cli_single_command(commands_config[args[0]], is_command_first=True)(_command, help, **kwargs)
        else:
            raise ValueError(f"Command '{args[0]}' not found. Available commands: {list(commands_config.keys())}")

    fire.Fire(_run_and_help)


def cli(config: Config | dict[str, Config]):
    """
    Run a config object(s) as a CLI.

    Args:
        config: The config or dict of configs to run. If dict is provided, each key is a command name
         and each value is a config object.

    Example:
        >>> @cfn.config()
        >>> def sum(a, b):
        >>>     return a + b
        >>> cfn.cli(sum)
        >>> # Shell call: python script.py --a 1 --b 2
        >>> # Shell call: python script.py --help

        >>> @cfn.config()
        >>> def sum(a, b):
        >>>     return a + b
        >>> @cfn.config()
        >>> def product(a, b):
        >>>     return a * b
        >>> cfn.cli({'sum': sum, 'product': product})
        >>> # Shell call: python script.py sum --a 1 --b 2
        >>> # Shell call: python script.py product --a 1 --b 2
        >>> # Shell call: python script.py --help
        >>> # Shell call: python script.py sum --help
    """

    if isinstance(config, dict):
        return _cli_multiple_commands(config)
    else:
        fire.Fire(_cli_single_command(config))
