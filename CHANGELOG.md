# Changelog

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
