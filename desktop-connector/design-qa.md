# Design QA · RokidHub Desktop Connector 0.4.1

## Evidence

- Source visual truth: `C:\Users\Azat\.codex\generated_images\01a03855-b733-7ee2-8819-b12369ff7219\exec-97779e31-e659-414d-b645-0f1361c101d9.png`
- Rendered implementation: `L:\pythonProject\RokidGlasses\rokidhub-desktop-connector\build\ui-overview-default-project.png`
- Combined comparison: `L:\pythonProject\RokidGlasses\rokidhub-desktop-connector\build\ui-qa-comparison-default-project.png`
- Focused default-project state: `L:\pythonProject\RokidGlasses\rokidhub-desktop-connector\build\ui-projects-default.png`
- English implementation state: `L:\pythonProject\RokidGlasses\rokidhub-desktop-connector\build\ui-overview-en.png`
- Source pixels: 1487 × 1058.
- Implementation pixels and native logical viewport: 1180 × 780 at device pixel ratio 1.
- Normalization: the source was scaled proportionally to 1096 × 780 and placed beside the unscaled 1180 × 780 implementation. No crop or density resampling was applied to the implementation.
- State: paired PC, stopped Connector, project `RokidGlasses`, voice alias `Рокид`, access mode `ask`. The source's running-status copy was intentionally replaced with the truthful paired/stopped state while preserving the same hierarchy and primary action.

## Full-view comparison

The two panes in `ui-qa-comparison-default-project.png` show the same desktop overview state and expose all important text at readable size. The implementation preserves the source's approximately 20/80 sidebar-to-content split, top status hero, two-column project/access controls, green primary action, privacy statement, grouped activity rows, circular outline status mark, and a consistent monochrome icon family. No content overlaps, clips, or leaves a persistent action unreachable at the minimum supported window size.

The focused Projects capture verifies the new extension that is not present in the source overview: exactly one project has a green Font Awesome `dot-circle-o` radio mark, the selected row uses the existing green surface token, all paths remain readable, and the destructive action remains visually separated. The English full-view capture was inspected separately for longer-label wrapping and clipping.

## Findings

No actionable P0, P1, P2, or P3 differences remain. The default-project radio control uses the same packaged Font Awesome outline family instead of a platform-stock indicator.

## Required fidelity surfaces

- Fonts and typography: Segoe UI Variable/Segoe UI matches the Windows product target. Heading, body, muted, and field-label hierarchy is preserved in both RU and EN. No truncation remains.
- Spacing and layout rhythm: sidebar proportion, main margins, hero alignment, two-column form, dividers, and activity rhythm match the selected direction. Controls remain visible at 1020 × 680 minimum size.
- Colors and visual tokens: near-black base, graphite surfaces, off-white text, muted gray-green copy, and `#62f238` action/accent color map directly to the RokidHub direction. Danger color is reserved for removal only.
- Image quality and asset fidelity: the supplied RokidHub raster logo is used directly and scaled with smooth aspect-preserving interpolation. All UI icons come from the packaged, licensed Font Awesome 4.0.3 library; no custom SVG, CSS illustration, placeholder logo, emoji, or Windows stock icon remains.
- Copy and content: Russian copy follows the selected visual hierarchy; English copy is complete and fits at the same viewport. Status wording is deliberately truthful to runtime state.
- Interaction and accessibility: all navigation destinations, comboboxes, project actions, start/stop, pairing/check, autostart, language switch, tray open/close, and tray exit are wired. Native keyboard focus and Windows scaling are retained by Qt. The UI uses readable 14 px-equivalent body text and high-contrast focus borders.

## Comparison history

1. First pass (`ui-qa-comparison-v1.png`): P2 activity region was visually empty, settings text clipped, selected project showed its voice alias instead of the folder name, and the stopped state showed both Start and disabled Stop.
2. Fixes: added truthful local readiness rows, removed the clipped settings subtitle, separated project folder name from voice alias, changed activity to a divided list, and made Start/Stop mutually visible by state.
3. Post-fix evidence (`ui-qa-comparison-v3.png`): all earlier P2 findings were resolved; a P3 stock-icon-family difference remained.
4. Icon pass (`ui-qa-comparison-icons-v2.png`): replaced every visible stock icon with one monochrome Font Awesome family, increased their optical size, and matched the source's circular outline hero status mark. The P3 difference is resolved.
5. Default-project pass (`ui-qa-comparison-default-project.png`, `ui-projects-default.png`): replaced implicit list reordering with an explicit radio selection, kept the established tokens, verified persistence and list-order stability, and updated overview copy to describe the actual behavior.

## Implementation checklist

- [x] Match the selected overview hierarchy and brand tokens.
- [x] Keep all existing Connector actions functional.
- [x] Add working sidebar destinations.
- [x] Add close-to-tray and explicit Exit behavior.
- [x] Add automatic Windows language detection and manual RU/EN override.
- [x] Verify Russian and English full-view states.
- [x] Verify explicit default-project selection and persistence without list reordering.
- [x] Pass unit and GUI smoke tests.

final result: passed
