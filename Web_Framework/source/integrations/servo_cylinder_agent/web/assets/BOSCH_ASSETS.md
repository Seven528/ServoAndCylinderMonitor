# Bosch assets for the internal demonstration

Copyright and trademark rights remain with Bosch. These are not original project
artwork and are not relicensed under a project software license.

On 2026-10-09 the owner confirmed Bosch employment and Bosch-internal demonstration
use, explicitly requesting official brand assets. This directory implements that
scope; it is not a statement of public redistribution rights or certification.
Do not include these assets in an external/public package without separately
confirming the applicable distribution requirements.

## Provenance

- bosch-supergraphic.svg: decoded without geometry/color edits from the
  `--sem__asset__supergraphic` SVG data URI in
  https://frok-bg.ui.bosch.tech/styles/brands/bosch/styles/semantic/index.css
  The official component token is in
  https://frok-bg.ui.bosch.tech/styles/brands/bosch/styles/components/header.css
  The local 6px, centered/cover presentation follows the inspected official header.
- bosch-logo.svg: original SVG paths/viewBox from `.o-minimal-header__logo` at
  https://frok-bg.ui.bosch.tech/?brand=bosch&color-mode=light
  Standalone SVG explicitly includes the official light-header wordmark fill
  #ea0016 and black emblem, previously supplied by the page styles at
  https://frok-bg.ui.bosch.tech/styles/frontend-kit-organisms.css
  Paths and proportions are unchanged. No fake logo or font-rendered wordmark.
- Applicable source terms:
  https://frok-bg.ui.bosch.tech/termsOfUse/?brand=bosch&color-mode=light

Both SVGs are served locally without third-party runtime requests. They contain
no scripts, event handlers, external href/src or foreignObject elements. The
Supergraphic's native internal gradients are preserved; no substitute CSS rainbow
was created. Bosch fonts and icon fonts are not included in this iteration.
