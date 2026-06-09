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


def _cli_single_command(config: Config):
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

    return _run_and_help


# A command tree is a (possibly nested) dict whose leaves are Configs. Positional
# args walk the tree by successive key lookups; the first option-looking token
# (``-``-prefixed) or a Config leaf ends the walk.
CommandTree = dict[str, 'Config | CommandTree']

# An empty-string key in a group node marks the *default command*: the one run when
# the group is reached without naming a child (no positional args, or a leading option).
DEFAULT_COMMAND = ''


def _walk_tree(tree: CommandTree, args: list[str]) -> tuple[Config | CommandTree, list[str], list[str]]:
    """Walk positional args down the command tree.

    Returns ``(node, path, rest)`` where ``node`` is the reached tree node (a
    ``Config`` leaf or an inner dict), ``path`` is the consumed keys, and
    ``rest`` is the remaining (unconsumed) args — the ``--kwargs`` and ``--help``.
    """
    node: Config | CommandTree = tree
    path: list[str] = []
    i = 0
    while isinstance(node, dict) and i < len(args) and not args[i].startswith('-'):
        key = args[i]
        if key not in node:
            available = list(node.keys())
            if path:
                raise ValueError(f"Command '{key}' not found under '{' '.join(path)}'. Available commands: {available}")
            raise ValueError(f"Command '{key}' not found. Available commands: {available}")
        node = node[key]
        path.append(key)
        i += 1
    return node, path, args[i:]


def _print_group_help(node: CommandTree, path: list[str]):
    print('Commands:')
    prefix = (' '.join(path) + ' ') if path else ''
    for command, child in node.items():
        if isinstance(child, dict):
            print(f'python {sys.argv[0]} {prefix}{command} <command> ...')
            continue
        target_command_doc = child.target.__doc__
        if target_command_doc:
            command_description = f' # {target_command_doc.split(chr(10))[0]}'
        else:
            command_description = ''
        required_args = get_required_args(child)
        required_args_str = ' '.join([f'--{arg}=<REQUIRED>' for arg in required_args])
        if command == DEFAULT_COMMAND:
            # The default command is invoked without naming it (no positional args, or a
            # leading option). Drop the empty name and flag it as the default.
            invocation = ' '.join(filter(None, [f'python {sys.argv[0]}', prefix.strip(), required_args_str]))
            doc = command_description.replace(' # ', ' ', 1) if command_description else ''
            print(f'{invocation} # default command{doc}')
        else:
            print(f'python {sys.argv[0]} {prefix}{command} {required_args_str}{command_description}')
    print()


def _cli_command_tree(tree: CommandTree):
    args = sys.argv[1:]
    node, path, rest = _walk_tree(tree, args)
    if isinstance(node, dict):
        default = node.get(DEFAULT_COMMAND)
        if default is not None:
            # A group with a default command. ``--help`` lists the group's children
            # (flagging the default); otherwise run the default, passing the remaining
            # tokens as overrides. A non-option positional that isn't a known command
            # already raised in ``_walk_tree``, so ``rest`` here is empty or starts with
            # an option token.
            if '--help' in rest:
                _print_group_help(node, path)
                return None
            runner = _cli_single_command(default)
            return fire.Fire(runner, command=rest)
        # A group node (root or intermediate): list its children — but only for a bare
        # group or an exact ``--help`` request. Any other option-looking token (e.g.
        # ``--typo``), even when ``--help`` is also present, is a mistake rather than a
        # request for help: reject it, matching the flat-dict "Command not found"
        # behavior instead of silently printing help and exiting 0.
        unknown = [token for token in rest if token != '--help']
        if unknown:
            available = list(node.keys())
            scope = f" under '{' '.join(path)}'" if path else ''
            raise ValueError(f"Command '{unknown[0]}' not found{scope}. Available commands: {available}")
        _print_group_help(node, path)
        return None
    # Config leaf: remaining args are its overrides. Handle ``--help`` ourselves so
    # fire doesn't intercept it, but still apply any overrides first so the help
    # reflects the overridden config (``command=`` keeps fire from re-reading the
    # already-consumed positional path off sys.argv).
    runner = _cli_single_command(node)
    if '--help' in rest:
        overrides = [a for a in rest if a != '--help']
        if not overrides:
            return runner(help=True)
        return fire.Fire(lambda **kwargs: runner(help=True, **kwargs), command=overrides)
    return fire.Fire(runner, command=rest)


def cli(config: Config | CommandTree):
    """
    Run a config object(s) as a CLI.

    Args:
        config: A single config, or a (possibly nested) dict of configs forming a
         command tree. Each non-dict leaf is a config; positional args walk the
         tree by key until a leaf is reached, then ``--kwargs`` override it.

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

        The more common real-world shape: the dict values are variants of one general
        config, derived with ``.override()`` instead of duplicate config functions.

        >>> single_arm = cfn.Config(build, robot_arm=franka, gripper=robotiq)
        >>> cfn.cli({
        ...     'droid': single_arm.override(robot_arm=franka_droid),
        ...     'sim': single_arm.override(robot_arm=franka_sim),
        ... })
        >>> # Shell call: python script.py droid --gripper=@my.grippers.Wsg
        >>> # Shell call: python script.py sim --robot_arm.collision_coeff=2.0

        >>> cfn.cli({'math': {'sum': sum, 'product': product}})
        >>> # Shell call: python script.py math sum --a 1 --b 2
        >>> # Shell call: python script.py math --help

        An empty-string ('') key marks a *default command*, run when no command is
        named — i.e. with no args or a leading option. A non-option word that isn't a
        known command still errors, so typos don't silently fall through.

        >>> cfn.cli({'': default_cfg, 'sim': sim_cfg})
        >>> # Shell call: python script.py                  -> default_cfg (no overrides)
        >>> # Shell call: python script.py --embodiment=droid -> default_cfg with override
        >>> # Shell call: python script.py sim --x=1          -> sim_cfg
        >>> # Shell call: python script.py --help             -> lists commands, flags the default
    """

    if isinstance(config, dict):
        return _cli_command_tree(config)
    else:
        fire.Fire(_cli_single_command(config))
