# Changelog

## [0.7.0] - 2026-07-26

### Added
- A target parameter annotated `cfn.Config` now receives the stored config itself instead of its instantiation (#38). This covers targets that must build a config later, more than once, or with overrides they only learn at runtime — a server applying per-connection overrides, for instance — which previously forced a hand-rolled dict of configs keyed by string. The declaration lives in the target's signature, so callers keep passing ordinary values: `.override()` (including dotted keys reaching into the config), `--help` and `get_required_args` all keep working on it. `Config | None`, `Optional[Config]`, `Annotated[Config, ...]` and string annotations (`from __future__ import annotations`) are recognised too; a non-config value on such a parameter is passed through untouched, and configs nested in containers (`list[Config]`) still resolve as before.

## [0.6.0] - 2026-07-25

### Added
- `Config.override_data()`, for applying overrides whose values come from outside the process — a request, a URL, a user-supplied file (#36). Same dotted overrides as `override()`, but values are interpreted strictly as data: a string that `override()` would resolve as an import raises `ImportNotAllowedError` instead, at any nesting depth. This covers the relative (`.`) form as seriously as the absolute (`@`) one — leading dots walk *up* the module tree, and enough of them leave the package entirely. Values that are not import references pass through untouched.
- `ImportNotAllowedError` (a `ConfigError`), carrying the offending `key` (the full dotted path, e.g. `cameras[0]`) and `value`, so a server can name the refused parameter back to the caller.

### Fixed
- Override failures now report the full dotted key. Previously `cfg.override(**{'arg.a.b': 4})` reported `Failed to override 'a'` — an intermediate segment — instead of `Failed to override 'arg.a.b'`.

## [0.5.2] - 2026-07-24

### Added
- PEP 561 `py.typed` marker, declared as package-data so it ships in the sdist and wheel (#34). Downstream type-checkers now read configuronic's inline annotations instead of treating the package as untyped — e.g. `.override(...)` on a `@cfn.config`-decorated symbol resolves correctly rather than being flagged as an unknown member.

## [0.5.1] - 2026-07-08

### Fixed
- Overriding with a `Config` (or a container of `Config`s) as a value no longer lets a dotted key in the *same* call mutate the shared instance (#31). Previously `cfg.override(codec=shared_codec, **{'codec.flip': True})` (and the equivalent `Config.__init__` / decorator form, including positional values as in `Config(Env, shared_codec, **{'0.flip': True})`) wrote `flip=True` onto `shared_codec` itself, silently changing every other config referencing it. `Config` and container values are now copied on store — for both keyword and positional arguments — so dotted writes always land on a private copy.

## [0.5.0] - 2026-06-09

### Added
- Nested command trees in `cfn.cli`. The dict form now accepts arbitrarily-nested dicts of `Config`s: positional args walk the tree by key until a `Config` leaf, then `--kwargs` override and instantiate it (e.g. `script.py group subcommand --param=value`). `--help` lists child commands at a group node and required args at a leaf. The previous flat `{'cmd': cfg}` form is the depth-1 special case and is unchanged.
- Default command in `cfn.cli(dict)` via an empty-string (`''`) key (#28). The `''` config is run when a command-tree group is reached without naming a child — i.e. with no args or a leading option (`python script.py` or `python script.py --param=value`). A non-option word that isn't a known command still errors, so typos don't silently fall through. `--help` lists the group's children and flags the default. Works at the root and at intermediate group nodes.

### Fixed
- `override()` / `copy()` now produce a fully independent config. Previously only top-level `Config` kwargs were copied, so a dotted override reaching through a shared `dict`/`list`/`tuple` (e.g. `base.override(**{'cameras.left.fps': 60})`) mutated the base and sibling variants. Nested `Config`s inside containers are now copied too.

### Documentation
- Documented the core "one general config + named `.override()` variants" idiom and contrasted it with writing near-duplicate config functions (#29). Added README sections "Variants via `.override()`" and "Instantiation semantics", and expanded the `Config.override`, `Config.instantiate`, and `cli` docstrings.
- Clarified instantiation semantics: a config is a closure and each `Config` reference is instantiated independently (no caching); to share one object across components, bind them together by passing it as a single argument.
- Updated the multi-config Best Practices example to use `cfn.cli(dict)` (with a default command) instead of manual `sys.argv` dispatch.

## [0.4.0] - 2026-02-16

### Added
- Support for `python -m configuronic @path.to.module.Config [--param=value ...]`. Any `Config` object on the Python path can now be run directly without a wrapper script.

## [0.3.1] - 2026-02-06

### Fixed
- Fix relative import resolution when module is run via `python -m`. The `_creator_module.__name__` is `'__main__'` in that case, breaking relative path computation. Now uses `__spec__.name` which preserves the real module path.

## [0.3.0] - 2025-10-25

### Added
- Support for passing entire lists and dictionaries containing config references from CLI and Python code. You can now use `--items='["@module.Obj1", ".Obj2"]'` or `--config='{"key": "@module.Value"}'` to override collections with config references.
- Both absolute (`@`) and relative (`.`) references are resolved recursively at all nesting levels within lists and dicts, providing consistent behavior throughout nested structures.
- All relative paths (`.`) in list/dict overrides resolve against the config (similar to standard resolution). Indexed overrides (e.g., `--items.0='.value'`) continue to resolve relative to the element's default.

### Changed
- **Breaking:** Dot-prefixed strings in list/dict overrides now trigger relative import resolution. To pass literal strings like `'./data'` or `'.env'`, use indexed override syntax: `--paths='["",""]' --paths.0='./data' --paths.1='.env'`.

## [0.2.3] - 2025-09-25

### Fixed
- Improved Config override error reporting by surfacing a contextual `ConfigError` that preserves the original failure details.


## [0.2.2] - 2025-09-05

### Fixed
- Narrow relative import resolution to reduce false positives for CLI string args. Leading-dot strings are now treated as literals unless the default provides a valid base (nested `Config`, importable object, Enum value, or `'@'` string). This fixes errors like passing `--input_dir=../data` being misinterpreted as a relative import. Relative imports for enums and multi-dot module paths continue to work where appropriate.


## [0.2.1] - 2025-08-22

### Fixed
- Fix --help failed for cfn.cli with multiple commands with no docstring (#17)


## [0.2.0] - 2025-08-19

### Added
- Add ability to specify multiple command in `cfn.cli`. Example:
```python
@cfn.config()
def sum(a, b):
    return a + b

@cfn.config()
def prod(a, b):
    return a * b

cfn.cli({'sum': sum, 'prod': prod})
```


## [0.1.1] - 2025-08-18

### Fixed
- Resolve values for nested dict and list overrides, not only `Config` fields. Now `@` absolute imports and `.` relative imports work when overriding entries inside plain dicts and lists (e.g., `--cameras.left=.opencv` or `--steps.0=@pkg.module.Factory`). Implementation updates `_set_value` to call `_resolve_value` for dict/list branches using the current default as context when available.

## [0.1.0] - 2024-07-29

### Added
- Initial release of Configuronic: configuration as code, CLI integration, nested overrides, absolute/relative import resolution, and serialization.
