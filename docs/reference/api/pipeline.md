# API — pipeline stages

The loop's five stages, one module each, in execution order. The driver
(`cp2k_forge.cli`) sequences them; each consumes and produces extended-XYZ plus manifest
state, so they are individually testable.

## Generate

::: cp2k_forge.generate

## Decorrelation

::: cp2k_forge.decorrelation

## Subsample

::: cp2k_forge.subsample

## DIRECT selection

::: cp2k_forge.direct

## Label

::: cp2k_forge.label

## Isolated-atom references

::: cp2k_forge.e0s

## Train

::: cp2k_forge.train

## Validate

::: cp2k_forge.validate

## Reports

::: cp2k_forge.report
