# Python API

The package is organised in three layers. Each section below documents one layer,
module by module.

## Pipeline stages

The loop's five stages, one module each, in execution order. The driver
(`cp2k_forge.cli`) sequences them; each consumes and produces extended-XYZ plus manifest
state, so they are individually testable.

### Generate

```{eval-rst}
.. automodule:: cp2k_forge.generate
```

### Decorrelation

```{eval-rst}
.. automodule:: cp2k_forge.decorrelation
```

### Subsample

```{eval-rst}
.. automodule:: cp2k_forge.subsample
```

### DIRECT selection

```{eval-rst}
.. automodule:: cp2k_forge.direct
```

### Label

```{eval-rst}
.. automodule:: cp2k_forge.label
```

### Isolated-atom references

```{eval-rst}
.. automodule:: cp2k_forge.e0s
```

### Train

```{eval-rst}
.. automodule:: cp2k_forge.train
```

### Validate

```{eval-rst}
.. automodule:: cp2k_forge.validate
```

### Reports

```{eval-rst}
.. automodule:: cp2k_forge.report
```

## Configuration and I/O

The data layer: campaign configuration, CP2K input/output, units, the dataset file and
the run-state machine.

### Configuration

```{eval-rst}
.. automodule:: cp2k_forge.config
```

### CP2K input templating and log parsing

```{eval-rst}
.. automodule:: cp2k_forge.cp2k_io
```

### Units

```{eval-rst}
.. automodule:: cp2k_forge.units
```

### Dataset

```{eval-rst}
.. automodule:: cp2k_forge.dataset
```

### Seed loading

```{eval-rst}
.. automodule:: cp2k_forge.seed
```

### Manifest (run state)

```{eval-rst}
.. automodule:: cp2k_forge.manifest
```

## Environment and engines

The runtime layer: the CLI driver, the preflight doctor, CP2K discovery, the MD engines
and the stage timers.

### CLI driver

```{eval-rst}
.. automodule:: cp2k_forge.cli
```

### Doctor (preflight)

```{eval-rst}
.. automodule:: cp2k_forge.doctor
```

### CP2K discovery

```{eval-rst}
.. automodule:: cp2k_forge.cp2k_env
```

### MD engines

```{eval-rst}
.. automodule:: cp2k_forge.engines
```

### Timing

```{eval-rst}
.. automodule:: cp2k_forge.timing
```
