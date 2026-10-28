# Python API: pipeline stages

The loop's five stages, one module each, in execution order. The driver
(`cp2k_forge.cli`) sequences them; each consumes and produces extended-XYZ plus manifest
state, so they are individually testable.

## Generate

```{automodule} cp2k_forge.generate
```

## Decorrelation

```{automodule} cp2k_forge.decorrelation
```

## Subsample

```{automodule} cp2k_forge.subsample
```

## DIRECT selection

```{automodule} cp2k_forge.direct
```

## Label

```{automodule} cp2k_forge.label
```

## Isolated-atom references

```{automodule} cp2k_forge.e0s
```

## Train

```{automodule} cp2k_forge.train
```

## Validate

```{automodule} cp2k_forge.validate
```

## Reports

```{automodule} cp2k_forge.report
```
