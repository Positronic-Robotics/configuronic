# Changelog

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
