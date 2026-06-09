# Configuronic

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://badge.fury.io/py/configuronic.svg)](https://badge.fury.io/py/configuronic)
[![Tests](https://github.com/Positronic-Robotics/configuronic/workflows/Tests/badge.svg)](https://github.com/Positronic-Robotics/configuronic/actions)

**Configuronic** is a simple yet powerful "Configuration as Code" library designed for modern Python applications, particularly in robotics, machine learning, and complex system configurations. Born from the need for a cleaner alternative to existing configuration frameworks, configuronic embraces Python's native syntax while providing powerful CLI integration and hierarchical configuration management.

## ✨ Why Configuronic?

* 🎯 **DRY Principle**: Write configurations in Python, not YAML/JSON/XML
* 🚀 **CLI-First**: Automatic command-line interfaces with complex nested parameter support
* 🔧 **Simple & Minimal**: Clean API that gets out of your way
* 🌳 **Hierarchical**: Deep nesting and inheritance support
* 🔄 **Dynamic**: Runtime configuration resolution with relative imports

## 🚀 Quick Start

```python
import configuronic as cfn

@cfn.config(learning_rate=0.001, epochs=100)
def train_model(learning_rate: float, epochs: int, model_name: str = "bert-base"):
    print(f"Training {model_name} for {epochs} epochs with lr={learning_rate}")
    # Your training logic here

if __name__ == "__main__":
    cfn.cli(train_model)
```

Run from command line:
```bash
# Use defaults
python train.py

# Override parameters
python train.py --learning_rate=0.0001 --epochs=50 --model_name="gpt-2"

# See current configuration
python train.py --help
```

## 📖 Table of Contents

- [Installation](#-installation)
- [Core Concepts](#-core-concepts)
- [Real-World Examples](#-real-world-examples)
- [Advanced Features](#-advanced-features)
- [CLI Usage](#-cli-usage)
- [API Reference](#-api-reference)
- [Best Practices](#-best-practices)
- [Contributing](#-contributing)

## 📦 Installation

Using pip
```bash
pip install configuronic
```

### Development Installation
```bash
git clone https://github.com/Positronic-Robotics/configuronic.git
cd configuronic
uv venv -p 3.10
source .venv/bin/activate
uv pip install -e .[dev]
```

## 🧠 Core Concepts

### Configuration as Code

In configuronic, configurations are **closures** - callables that store both the function and its arguments. It is somewhat similar to [`functools.partial`](https://docs.python.org/3/library/functools.html#functools.partial) This functional approach enables powerful composition and inheritance patterns.

```python
import configuronic as cfn

# Create a configuration
@cfn.config(batch_size=32, lr=0.001)
def create_optimizer(batch_size: int, lr: float):
    return torch.optim.Adam(lr=lr)

# Override and create variants
fast_optimizer = create_optimizer.override(lr=0.01)
large_batch_optimizer = create_optimizer.override(batch_size=128)

# Instantiate when needed
optimizer = fast_optimizer.instantiate()
```

### Two Main Operations

**1. `override(**kwargs)`** - Create configuration variants
```python
base_config = cfn.Config(MyModel, layers=3, units=64)
deep_config = base_config.override(layers=6)
wide_config = base_config.override(units=128)
```

**2. `instantiate()`** - Execute function with configured arguments and get its result
```python
model = deep_config.instantiate()  # Returns MyModel(layers=6, units=64)
```

**Callable Syntax** - Config objects are callable, providing a shorthand for override + instantiate
```python
# These are equivalent:
result1 = config.override(param=value).instantiate()
result2 = config(param=value)()
```

### Nested Configuration Override

Support for deep parameter modification using dot notation:

```python
# Configure a complex training pipeline
training_cfg = cfn.Config(
    train_pipeline,
    model=cfn.Config(TransformerModel, layers=6, hidden_size=512),
    optimizer=cfn.Config(torch.optim.Adam, lr=0.001),
    data=cfn.Config(DataLoader, batch_size=32)
)

# Override nested parameters
fast_training = training_cfg.override(**{
    "optimizer.lr": 0.01,
    "data.batch_size": 64,
    "model.layers": 12
})
```

### Variants via `.override()` (the core idiom)

For real projects, the pattern you'll reach for most is **one general config plus
named variants derived with `.override()`** — *not* a dict of unrelated config
functions. Define the shared base once, then specialize it:

```python
# ONE general config — the factory and its shared defaults.
single_arm = cfn.Config(build_embodiment, robot_arm=franka, gripper=robotiq, cameras={})

# Named variants are just overrides of that base. Use dotted keys to reach
# into sub-configs and list/dict slots.
droid = single_arm.override(
    robot_arm=franka_droid,
    cameras={'wrist': wrist_cam, 'scene': scene_cam},
)
sim = single_arm.override(
    robot_arm=franka_sim,
    **{'robot_arm.collision_coeff': 2.0},   # nested, dotted override
)

# Expose the variants as CLI commands by passing a dict of overrides to cli().
if __name__ == "__main__":
    cfn.cli({'droid': droid, 'sim': sim})
```

```bash
python embodiment.py droid --gripper="@my.grippers.Wsg"
python embodiment.py sim --robot_arm.collision_coeff=4.0
```

**Less recommended:** writing several near-duplicate `@cfn.config` functions that
each rebuild the same object and differ only in a few arguments.

```python
# Works, but duplicates the construction logic, which can drift out of sync and is
# harder to override from the CLI.
@cfn.config(robot_arm=..., gripper=..., cameras={...})
def droid(robot_arm, gripper, cameras):
    return build_embodiment(robot_arm, gripper, cameras, simulated=False)

@cfn.config(mujoco_model_path=...)
def sim(mujoco_model_path, ...):
    ...  # rebuild devices by hand
    return build_embodiment(robot_arm, gripper, cameras, simulated=True)
```

When two configs share a factory and differ only in their arguments, prefer
`base.override(...)` over a second `@cfn.config` function. Concrete (non-`Config`)
override values pass straight through, and dotted keys let you tweak nested
sub-configs without redefining the base.

### Instantiation semantics (shared instances)

Each referenced `Config` is instantiated **independently** — there is **no instance
memoization or identity sharing**. If the same sub-config is referenced from several
slots, it is built **once per slot**, producing that many distinct objects:

```python
mujoco = cfn.Config(MujocoSim, model_path="scene.xml")

# ❌ Three references -> THREE separate MujocoSim instances, not one shared sim.
embodiment = cfn.Config(
    Embodiment,
    robot_arm=cfn.Config(SimArm, sim=mujoco),
    gripper=cfn.Config(SimGripper, sim=mujoco),
    cameras={'wrist': cfn.Config(SimCamera, sim=mujoco)},
)
```

To share a single instance across slots, build it inside one config that returns the
group as a **bundle** (a dataclass, namedtuple, or dict), and reference that bundle:

```python
# ✅ Build the shared sim and all devices together; one MujocoSim is created.
@cfn.config(model_path="scene.xml")
def sim_devices(model_path: str):
    sim = MujocoSim(model_path)
    return {
        'robot_arm': SimArm(sim),
        'gripper': SimGripper(sim),
        'cameras': {'wrist': SimCamera(sim)},
    }
```

## 🌍 Real-World Examples

### Robotics Hardware Configuration

```python
import configuronic as cfn

@cfn.config(ip="172.168.0.2")
def robot_arm(ip: str, relative_dynamics_factor: float = 0.2):
    from my_robots import FrankaArm
    return FrankaArm(ip=ip, dynamics_factor=relative_dynamics_factor)

@cfn.config(device_path="/dev/video0", fps=30)
def camera(device_path: str, width: int = 1920, height: int = 1080, fps: int = 30):
    from my_cameras import Camera
    return Camera(device_path, width, height, fps)

# Create specific hardware configurations
left_camera = camera.override(device_path="/dev/video1")
right_camera = camera.override(device_path="/dev/video2")

# Main system configuration
@cfn.config(arm=robot_arm,
            cameras={'left': left_cam, 'right': right_cam})
def main(arm, cameras, gripper=None):
    from robot_library import RobotSystem
    system = RobotSystem(arm=arm, cameras=cameras, gripper=gripper)
    system.run()

if __name__ == "__main__":
    cfn.cli(main)
```

### Machine Learning Pipeline

```python
@cfn.config(model_name="bert-base", max_length=512)
def create_tokenizer(model_name: str, max_length: int):
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    tokenizer.model_max_length = max_length
    return tokenizer

@cfn.config(hidden_size=768, num_layers=12)
def create_model(hidden_size: int, num_layers: int, tokenizer):
    vocab_size = len(tokenizer)
    return TransformerModel(vocab_size, hidden_size, num_layers)

# Configure the complete pipeline
@cfn.config()
def training_pipeline(
    tokenizer=create_tokenizer,
    model=create_model,
    learning_rate: float = 1e-4,
    batch_size: int = 16
):
    # Pipeline implementation
    return TrainingPipeline(tokenizer, model, learning_rate, batch_size)

if __name__ == "__main__":
    cfn.cli(training_pipeline)
```

Run with different configurations:
```bash
# Use defaults
python train.py

# Quick experiments
python train.py --learning_rate=1e-3 --batch_size=32

# Override nested model parameters
python train.py --model.num_layers=6 --tokenizer.max_length=256

# Switch to different model entirely
python train.py --tokenizer.model_name="gpt2" --model.hidden_size=1024
```

## 🔧 Advanced Features

### Import Resolution with `@` and `.`

Configuronic provides powerful import resolution syntax that allows you to dynamically reference Python objects, especially useful for CLI usage.

#### Absolute Imports (`@`)
Direct import paths to any Python object. If you need to use a literal `@` at the beginning of a string (not for imports), use `@@`:
```bash
# From command line - these import exact module paths
python train.py --model="@transformers.BertModel"     # Import BertModel
python train.py --message="@@starts_with_at"          # Literal string "@starts_with_at"
python train.py --text="foo@bar"                      # No escaping needed in the middle
```

Absolute imports could also be used in both Python decorators and classes. However, we don't suggest using them:

```python
@cfn.config(model="@torchvision.models.resnet34")
def get_model_parameters(model: torch.nn.Module):
    return list(model.named_parameters())
```

```python
def get_model_parameters(model: torch.nn.Module):
    return list(model.named_parameters())

resnet_model_parameters = cfn.Config(
    get_model_parameters,
    model="@torchvision.models.resnet34"
)
```

#### Relative Imports (`.`)
Navigate relative to the current module, similar to Python's relative import syntax:

```python
# If default is myproject.models.BertEncoder
python train.py --encoder=".RobertaEncoder"        # -> myproject.models.RobertaEncoder (same module)
python train.py --encoder="..utils.CustomEncoder"  # -> myproject.utils.CustomEncoder (parent module)
python train.py --encoder="...shared.BaseEncoder"  # -> myproject.shared.BaseEncoder (grandparent module)
```

**How it works:** Each `.` acts like `../` in file system navigation:
- `.` = stay in current module (like `./`)
- `..` = go up one module level (like `../`)
- `...` = go up two module levels (like `../../`), etc.

The path after the dots specifies the target within that module hierarchy.

**Note**: Relative import resolution triggers when the default provides a valid base — specifically when it is another `Config`, an importable object (class/function), an Enum value, or a string starting with '@'. In other cases (e.g., default is `None` or a plain string), leading-dot strings are treated as literals. This allows passing common filesystem-like values such as '../data', './file', or '.env' via CLI without special handling.

#### Configuration Copy Across Modules

The `copy()` method updates module context so relative imports (`.`) resolve from the new module location:

```python
# configs/base.py
original_config = cfn.Config(SomeClass, value=1)

# experiments/vision.py
from configs.base import original_config

# Copy updates the config's module context to experiments.vision
copied_config = original_config.copy()

@cfn.config()
def local_function():
    return "local result"

# When copied_config is used as default, '.' resolves in experiments.vision
env_cfg = cfn.Config(Environment, setup=copied_config)
specialized_cfg = env_cfg.override(setup=".local_function")  # Finds local_function
```

Without `copy()`, `.local_function` would try to resolve in `configs.base` and fail.

### Lists and Dictionaries

Configuronic seamlessly handles nested data structures and supports config references within them:

```python
simulation_cfg = cfn.Config(
    run_simulation,
    loaders=[
        cfn.Config(AddCameras, camera_config=camera_cfg),
        cfn.Config(AddObjects, objects=["cube", "sphere"]),
        cfn.Config(SetLighting, intensity=0.8)
    ],
    cameras={
        'main': cfn.Config(Camera, position=[0, 0, 1]),
        'side': cfn.Config(Camera, position=[1, 0, 0])
    }
)

# Override specific items using indexed notation
modified_sim = simulation_cfg.override(**{
    "loaders.0.camera_config.fps": 60,  # First loader's camera FPS
    "cameras.main.position": [0, 0, 2]   # Main camera position
})

# Override entire lists/dicts with config references
from_cli = simulation_cfg.override(
    loaders=[
        '@my_loaders.CameraLoader',
        '@my_loaders.ObjectLoader',
        '.CustomLightingLoader'  # Relative to simulation_cfg's module
    ]
)
```

#### Lists and Dicts with Config References

You can pass entire lists or dictionaries containing config references (using `@` or `.` syntax):

```python
# From CLI (we rely on fire's parsing behavior)
python script.py --models='["@transformers.BertModel", "@transformers.GPT2Model"]'
python script.py --cameras='{"left": "@opencv.Camera", "right": ".CustomCamera"}'

# From Python code
config = cfg.override(
    models=['@transformers.BertModel', '@transformers.GPT2Model'],
    datasets=['.ImageNetDataset', '.CocoDataset']
)
```

**Key points:**

1. **Replacement semantics:** Overriding an entire list or dict completely replaces all previous values, including any defaults that were defined. This is assignment, not merging.

2. **Relative resolution:** All relative paths (`.`) in a list/dict override resolve against the **config** (similar to standard resolution). Both absolute (`@`) and relative (`.`) references work recursively at all nesting levels.

```python
# In file: myproject/training.py
@cfn.config(datasets=[SomeDefaultDataset, AnotherDefault, ThirdDefault])
def train(datasets):
    pass

# CLI: python training.py --datasets='[".LocalDataset", ".RemoteDataset"]'
# Result:
#   - Original 3 defaults are completely replaced by 2 new values
#   - Both resolve relative to the config: myproject.training.LocalDataset, myproject.training.RemoteDataset

# Nested collections also resolve references:
python training.py --data='[[".Dataset1", "@other.Dataset2"], {"key": ".value"}]'
# All references (@ and .) are resolved recursively at any depth
```

To pass literal strings starting with `.` (like `'./data'` or `'.env'`), use indexed override instead:

```bash
# Initialize with empty strings, then override individually
python script.py --paths='["",""]' --paths.0='./data' --paths.1='.env'
```

### Configuration Inheritance

```python
# Base configuration
base_camera = cfn.Config(Camera, width=1920, height=1080, fps=30)

# Derived configurations
hd_camera = base_camera.override(width=1280, height=720)
high_fps_camera = base_camera.override(fps=60)
webcam = base_camera.override(width=640, height=480, fps=15)

# All inherit base settings unless overridden
```

## 🖥️ CLI Usage

Configuronic leverages [Python Fire](https://github.com/google/python-fire) for automatic CLI generation:

### Basic CLI
```python
@cfn.config(param1="default", param2=42)
def my_function(param1: str, param2: int):
    return f"{param1}: {param2}"

if __name__ == "__main__":
    cfn.cli(my_function)
```

### Command Line Examples
```bash
# Show help and current config
python script.py --help

# Override parameters
python script.py --param1="hello" --param2=100

# Nested parameter override
python script.py --model.layers=6 --optimizer.lr=0.001

# Using absolute imports
python script.py --model="@my_models.CustomTransformer"

# To pass a string that starts with @, repeat it twice
python script.py --message="@@this_is_literal_at_sign"

# Using relative imports
python script.py --tokenizer=".CustomTokenizer"

# Complex nested overrides
python script.py --cameras.left.fps=60 --cameras.right.device="/dev/video2"
```


### Multi-Command CLI
You can also provide multiple commands in a single script by passing a dictionary of configurations:

```python
@cfn.config()
def sum_numbers(x: float, y: float) -> float:
    """Sum of two numbers"""
    return x + y

@cfn.config()
def multiply_numbers(x: float, y: float) -> float:
    """Product of two numbers"""
    return x * y

if __name__ == "__main__":
    cfn.cli({'sum': sum_numbers, 'multiply': multiply_numbers})
```

This enables running different commands from the same script:

```bash
# Run sum command
python script.py sum --x=5 --y=10
# Output: 15.0

# Run multiply command
python script.py multiply --x=5 --y=10
# Output: 50.0

# Get help for all commands
python script.py --help
# Shows available commands with their descriptions

# Get help for specific command
python script.py sum --help
# Shows detailed help for the sum command
```

#### Default command (no subcommand name)

An empty-string (`''`) key marks a **default command** — the one run when no command
is named. This lets a tool expose named presets *and* a primary, flags-only path:

```python
cfn.cli({'': default_cfg, 'sim': sim_cfg})
```

```bash
python script.py                       # -> default_cfg (no overrides)
python script.py --embodiment=droid    # -> default_cfg with the override applied
python script.py sim --x=1             # -> sim_cfg (named command, unchanged)
python script.py --help                # -> lists commands and flags the default
```

A non-option word that isn't a known command still errors (so typos don't silently
fall through to the default) — only no arguments or a leading `--option` dispatch to
the default.

### Parameter Override Order ⚠️

**Important:** Parameter overrides are executed in order of declaration. When overriding nested configurations, set the parent object first, then its properties:

```bash
# ✅ Correct: set camera first, then its resolution
python script.py --camera="@opencv.Camera" --camera.resolution="full_hd"

# ❌ Incorrect: this will reset camera after setting resolution
python script.py --camera.resolution="full_hd" --camera="@opencv.Camera"
```

In the incorrect example, the default camera's resolution gets updated first, but then the entire camera object is replaced, losing the resolution override.

## 📚 API Reference

### Core Classes

#### `Config(target, *args, **kwargs)`
Main configuration class that stores a callable and its arguments.

**Methods:**
- `override(**kwargs) -> Config`: Create new config with updated parameters
- `instantiate() -> Any`: Execute the configuration and return result
- `copy() -> Config`: Deep copy the configuration
- `__call__(**kwargs) -> Any`: `override` config with `**kwargs` and `instantiate` it. **Note:** only keyword specified arguments are supported.

#### `@config` Decorator
```python
@cfn.config  # No override, just turn function into config.
def print_greeting(greeting: str = 'Hello', entity: str = 'world'):
    print(f'{greeting} {entity}!')

@cfn.config(arg1="default", arg2=42)  # With defaults
def my_function(...):
    pass
```

### Utility Functions

#### `cli(config: Config | dict[str, Config])`
Generate automatic command-line interface for any configuration or multiple configurations.

**Parameters:**
- `config`: Either a single `Config` object or a (possibly nested) dict mapping command names to `Config`s. An empty-string (`''`) key marks the default command, run when no command is named.

**Examples:**
```python
# Single command
cfn.cli(my_config)

# Multiple commands
cfn.cli({'train': train_config, 'eval': eval_config, 'test': test_config})

# With a default command (run when no subcommand is given)
cfn.cli({'': train_config, 'eval': eval_config})
```

#### `get_required_args(config: Config) -> List[str]`
Get list of required arguments for a configuration.

### Special Syntax

- `@module.path.Class` - Absolute import path to any Python object
- `.RelativeClass` - Relative import (same module, like `./`)
- `..parent.Class` - Relative import (up one level, like `../`)
- `@@literal_string` - Escape literal `@` characters in the beginning of strings

> **Path Resolution:** The `.` syntax works like file system navigation where each dot moves up one module level in the Python package hierarchy, then navigates down to the specified target.


## 💡 Best Practices

### 1. Avoid Positional Arguments (`*args`) ⚠️

> **Warning:** Configuronic has limited support for positional arguments (`*args`). Use them only in exceptional cases (like functions that accept variable-length lists) and always use explicit `cfn.Config()` construction, never the decorator.

**Problems with positional arguments:**

1. **Implicit and unclear** - Hard to understand what arguments represent:
   ```python
   # ❌ Unclear what 1, 2, 3 represent
   func = cfn.Config(func, 1, 2, 3)
   ```

2. **Fragile** - Changing argument order breaks all configurations:
   ```python
   # ❌ If you change parameter order, all configs break
   @cfn.config("robot", "camera")
   def compose(camera, robot):  # Swapped order!
       ...
   ```

3. **Ambiguous override behavior** - Unclear what `override()` should do:
   ```python
   # ❌ What should sum_with45 contain? [4, 5] or [1, 2, 3, 4, 5]?
   sum_123 = cfn.Config(sum, 1, 2, 3)
   sum_with45 = sum_123.override(4, 5)
   ```

**Recommended approach:**
```python
# ✅ Use keyword arguments for clarity
config = cfn.Config(func, param1=1, param2=2, param3=3)

# ✅ Only use *args for functions designed for them
@cfn.config()  # No positional args in decorator
def sum_all(*numbers):
    return sum(numbers)

variadic_sum = cfn.Config(sum_all, 1, 2, 3)  # Explicit Config only
```

### 2. Create Separate Modules for Configurations
If you don't want your business logic modules to depend on `configuronic`, it's wise to have a separate package for configurations.
```python
# configs/models.py
transformer_base = cfn.Config(TransformerModel, layers=6, hidden_size=512)
transformer_large = transformer_base.override(layers=12, hidden_size=1024)

# configs/training.py
from .models import transformer_base
training_pipeline = cfn.Config(TrainingPipeline, model=transformer_base)
```

### 3. Import Inside Configuration Functions
In robotic applications, some configurations may depend on parituclar hardware and Python packages that provide drivers, that are not always available. If you don't want to force your users to install all of them, consider making imports inside the functions that you configure.
```python
@cfn.config()
def create_model(layers: int = 6):
    from my_project.models import TransformerModel
    return TransformerModel(layers=layers)
```

But in smaller projects it might be very convinient to put configurations alongside the methods they manage.

### 4. Use `override` to create as many custom configurations as you need
When working with text configuration files, it's natural to create separate files for different environments or use cases. In `configuronic`, just create new configuration variables that override the base config.

```python
# Base training configuration
base_training = cfn.Config(
    TrainingPipeline,
    model=cfn.Config(TransformerModel, layers=6, hidden_size=512),
    optimizer=cfn.Config(torch.optim.Adam, lr=0.001),
    batch_size=32,
    epochs=10
)

# Development environment - smaller, faster
dev_training = base_training.override(
    batch_size=8, epochs=2,
    **{"model.layers": 3, "model.hidden_size": 256})

# Production environment - optimized settings
prod_training = base_training.override(
    batch_size=64, epochs=100,
    **{"optimizer.lr": 0.0001})

# Experimental setup - large model
experimental_training = base_training.override(
    **{
        "model.layers": 12,
        "model.hidden_size": 1024,
        "optimizer.lr": 0.0005,
        "batch_size": 16
    })

# Quick debugging setup
debug_training = base_training.override(
    epochs=1, batch_size=2, **{"model.layers": 1})

# Pass the variants to cli() as a dict to switch between them from the command line.
# Make 'dev' the default command (run when no preset is named) via the '' key.
if __name__ == "__main__":
    cfn.cli({
        '': dev_training,            # default: `python train.py` runs dev
        'dev': dev_training,
        'prod': prod_training,
        'experimental': experimental_training,
        'debug': debug_training,
    })
```

**Usage:**
```bash
python train.py              # Use the default (dev) config
python train.py dev          # Use development config
python train.py prod         # Use production config
python train.py experimental # Use experimental config
python train.py debug        # Use debug config

# Still supports all override capabilities
python train.py prod --epochs=50 --batch_size=128
```


## 🤝 Contributing
We welcome contributions! Here's how to get started:

### Development Setup
```bash
git clone https://github.com/Positronic-Robotics/configuronic.git
cd configuronic
uv pip install -e ".[dev]"
```

### Running Tests
```bash
pytest  # Run all tests
pytest --cov=configuronic  # Run with coverage
```
### 📋 Guidelines
- Follow existing code style and patterns
- Add tests for new functionality
- Ensure all tests pass before submitting
- Update documentation as needed

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE.md) file for details.

## 📞 Support

- 🐛 **Bug Reports**: [GitHub Issues](https://github.com/Positronic-Robotics/configuronic/issues)
- 💬 **Discussions**: [GitHub Discussions](https://github.com/Positronic-Robotics/configuronic/discussions) **FIXME: Create Discord**
- 📧 **Email**: hi@positronic.ro

---

**⭐ If you find Configuronic useful, please consider giving it a star on GitHub!**
