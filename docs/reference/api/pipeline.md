# Python API: pipeline stages

The loop's five stages, one module each, in execution order. The driver
(`cp2k_forge.cli`) sequences them; each consumes and produces extended-XYZ plus manifest
state, so they are individually testable.

## Generate

```{eval-rst}
.. automodule:: cp2k_forge.generate
```

## Decorrelation

```{eval-rst}
.. automodule:: cp2k_forge.decorrelation
```

## Subsample

```{eval-rst}
.. automodule:: cp2k_forge.subsample
```

## DIRECT selection

```{eval-rst}
.. automodule:: cp2k_forge.direct
```

## Label

```{eval-rst}
.. automodule:: cp2k_forge.label
```

## Isolated-atom references

```{eval-rst}
.. automodule:: cp2k_forge.e0s
```

## Train

```{eval-rst}
.. automodule:: cp2k_forge.train
```

## Validate

```{eval-rst}
.. automodule:: cp2k_forge.validate
```

## Reports

```{eval-rst}
.. automodule:: cp2k_forge.report
```
