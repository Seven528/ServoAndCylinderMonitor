# Industrial workbench design references

Reviewed on 2026-10-09. These are reference observations, not a claim of Bosch
certification, an official implementation, or authorization to redistribute assets.

## Current decision: direction B and official internal-demo assets

After reviewing the first implementation, the owner selected direction B and
confirmed Bosch employment/internal demonstration use, explicitly requesting the
brand ribbon and related assets. The earlier no-assets decision below is historical
and superseded for this local demo. The current page uses the official logo SVG and
Supergraphic SVG from FROK, preserved locally with provenance in
web/assets/BOSCH_ASSETS.md. This does not imply external/public distribution.

The header follows the observed 6px centered/cover Supergraphic treatment. The logo
keeps its original 108:24 proportions. A graphite rail, light canvas, softer dividers,
round icon terminals and 4px control rounding implement B without sacrificing canvas
space. The rounding is a project adaptation, not a claimed official Bosch rule.

## Official sources actually inspected

1. Frontend Kit 6.0.1, Bosch brand / light mode:
   https://frok-bg.ui.bosch.tech/?brand=bosch&color-mode=light
   The landing page identifies FROK as part of the Digital Design System and
   provides HTML/CSS/JS component documentation. Inspected with web retrieval and
   the browser. Light and dark are available; dark is not mandatory.
2. Digital Design System / Brand Guide:
   https://brandguide.bosch.com/hub/53
   This official link redirects to authentication. No private guide was accessed,
   and no unavailable requirements are represented here as verified rules.
3. Published Bosch color gradations:
   https://frok-bg.ui.bosch.tech/styles/brands/bosch/styles/gradations/gradations.css
   Read the actual published CSS; relevant tokens appear in the table below.
4. Published foundations:
   https://frok-bg.ui.bosch.tech/styles/frontend-kit-foundations.css
   Observed root typography at 1rem / 1.5, semantic heading levels, and zero-radius
   form controls. The rendered homepage resolves its UI font to Bosch Sans.
5. Published component styles:
   https://frok-bg.ui.bosch.tech/styles/frontend-kit-atoms.css
   Observed semantic button tokens and tab navigation with a baseline separator and
   explicit focus outline. Individual button/typography guide routes returned 403
   during this session; do not infer detailed guidance from inaccessible pages.
6. Frontend Kit Terms and Conditions:
   https://frok-bg.ui.bosch.tech/termsOfUse?brand=bosch&color-mode=light
   Read in the actual browser. Section 5 ties content use to an existing contractual
   relationship with Bosch and describes limited onward distribution. The owner has
   subsequently confirmed the Bosch-internal use context; that confirmation, not
   public availability alone, is the basis for the local asset inclusion.

## Adopted palette and hierarchy

| Official published token | Value | Local use |
| --- | --- | --- |
| blue-50 | #007bc0 | Primary actions, focus and active markers |
| blue-40 | #00629a | Hover/pressed blue and readable link emphasis |
| blue-95 | #e8f1ff | Selected control and contextual information background |
| gray-20 | #2e3033 | Primary text |
| gray-40 | #595e62 | Secondary text |
| gray-80 / gray-85 | #c1c7cc / #d0d4d8 | Control edges and structural dividers |
| gray-95 / white | #eff1f2 / #ffffff | Navigation/fields and work surfaces |
| green-40 | #006c3a | Successful state text with explicit labels |
| red-40 | #be0004 | Error text, never the default action |
| yellow-40 / yellow-95 | #725b00 / #ffefd1 | Warning text/background |

These role assignments are local engineering choices using observed color values,
not a transcription of all official semantic tokens. Native PNG geometry colors,
height bands and risk colors are unchanged. The official Supergraphic is reused,
not recreated with a CSS gradient. The two official SVGs are local; no external CSS
dependency, icon font or font payload is installed.

## Typography, controls and density

- System sans-serif stack supports Chinese; Bosch Sans is not bundled in this pass.
  Local density: 14px interactive controls/body, 12px auxiliary labels, 16–20px
  section/product headings, 1.5 line height, tabular numerals. These sizes are local
  choices for a dense inspection tool, not an assertion of official Chinese sizing.
- Mostly rectangular 4px-radius controls, flat surfaces and selective dividers
  replace rounded card stacks. Blue is reserved for actions/selection; neutral
  surfaces remain dominant. The official ribbon's internal gradients are preserved;
  no additional decorative gradients, animation dependency or card shadows.
- Generic existing SVG line icons plus focus/history/info shapes are authored in
  this project. They are not Bosch icons or an approximation of the Bosch emblem.
- Tables use readable rows, fixed header emphasis, numeric alignment and row hover.
  Focus, selected, disabled, working, failed and disconnected states remain textual
  as well as visual. Status colors do not imply an engineering risk result.
- Full Agent name is in About. File/configuration/status share a result line;
  detailed metrics and reports remain disclosures. File/history share a narrow rail.

## Skills, concept images and implementation

The available catalog and installed skill paths contained no official frontend
design skill. The ImageGen skill was read and used through the built-in tool for
two independent direction images. No skill installation or substitute claim was
made. Generated concepts are not source geometry or engineering evidence; their
illustrative labels/counts must never populate the product.

- A: light rail, collapsed auxiliary panels, canvas-first working surface.
- B: graphite rail, light canvas and an optional docked assistant.
- Implemented after owner feedback: B's graphite rail and optional docking, official
  Bosch logo/ribbon and softened controls, using real HTML/CSS/JS and native PNG.
  No generated concept image is served by the web app.

Concept files are retained under ignored output/design/industrial-workbench/ as
direction-a.png and direction-b.png. Exact generation prompts are retained there
in prompts.md. Screenshots and geometry measurements are in the matching ignored
output/playwright/industrial-workbench/ directory and VALIDATION.md.

## Ownership

The latest browser review intentionally supersedes the reserved height-row and
browser-details decisions: the height-only row now collapses outside Height Map;
the report UI/adapter and redundant status/About/More/LOCAL text are removed.
Reports remain on disk and queryable by the Agent. CD Analysis Agent gets a wider
reading pane, online/offline text, a 200x78px composer model/effort/speed picker and
an explicitly authorized, browser-dependent dictation entry. File/history use
248px and scrollable names. All are local product decisions, not Bosch rules.

layout-state.js owns bounded panel preferences and breakpoint projection; layout.js
owns DOM/accessibility and focus restoration. workbench-layout.css owns geometry;
workbench-panels.css owns optional panels; style.css owns shared controls/results.
Result identity, viewer and transport modules keep their existing roles; the
browser report module is retired while the server report reader remains available.
