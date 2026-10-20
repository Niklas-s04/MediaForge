---
name: MediaForge Self-Hosted Studio
description: The implemented Stitch studio interface for MediaForge.
colors:
  primary: "#284e3a"
  primary-hover: "#103725"
  accent: "#466555"
  background: "#f9f9f8"
  surface: "#ffffff"
  surface-soft: "#f3f4f2"
  text: "#1a1c1b"
  muted: "#414843"
  placeholder: "#667068"
  border: "#e2e3e1"
  border-strong: "#c1c8c1"
  focus: "#406651"
  on-primary: "#ffffff"
  success-background: "#eaf2ec"
  dark-background: "#141715"
  dark-surface: "#1b1e1c"
  dark-surface-soft: "#222623"
  dark-text: "#ecefea"
  dark-muted: "#adb8b0"
  dark-border: "#2b302c"
  dark-border-strong: "#48544b"
  dark-primary: "#39735e"
  dark-primary-hover: "#30634f"
  dark-accent: "#90d4b9"
  dark-success-background: "#1d2a23"
typography:
  headline:
    fontFamily: "Geist, 'Segoe UI', sans-serif"
    fontSize: "28px"
    fontWeight: 600
    lineHeight: "36px"
    letterSpacing: "-0.84px"
  title:
    fontFamily: "Geist, 'Segoe UI', sans-serif"
    fontSize: "16px"
    fontWeight: 600
    lineHeight: "22px"
    letterSpacing: "-0.24px"
  body:
    fontFamily: "Geist, 'Segoe UI', sans-serif"
    fontSize: "14px"
    lineHeight: 1.5
  label:
    fontFamily: "Geist, 'Segoe UI', sans-serif"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: "16px"
  technical:
    fontFamily: "'JetBrains Mono', monospace"
    fontSize: "12px"
    fontWeight: 400
rounded:
  control: "4px"
  panel: "8px"
spacing:
  compact: "8px"
  field-gap: "12px"
  mobile-panel: "16px"
  panel: "20px"
  section: "32px"
  queue: "48px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.control}"
    padding: "0 24px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-secondary:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
  field:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
  work-panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.panel}"
    padding: "20px"
---

# Design System: MediaForge Self-Hosted Studio

## Overview

The visual authority is the supplied Google Stitch project **MediaForge Self-Hosted Studio**, project `9468772688105973646`. Its newer light screen `2168953198f4469983a9487eca61080f` establishes the composition: a compact navigation bar, a centered work panel, and jobs below. The older dark screen `43362ee042c64849a00484b75b823676` is an alternate theme reference, not a second layout.

This is an extracted record of the implemented interface, not a new brand direction. The user requested fidelity to Stitch. No additional creative metaphor or product positioning is inferred.

## Colors

The primary forest green marks actions; the quieter accent marks status and progress. Warm near-white surfaces and restrained neutral text establish hierarchy in light mode. Dark mode changes surface and foreground tokens while retaining the same geometry.

**The Contrast Rule.** Dark primary buttons use the darker `dark-primary` token with white labels; the light placeholder uses the `placeholder` token. These are deliberate readability adjustments to the reference. Use `dark-accent` for dark-theme status and emphasis rather than as the white-label button fill.

## Typography

Geist is locally served in regular, medium, and semibold weights. JetBrains Mono regular distinguishes technical metadata, destination text, counts, percentages, and logs. Font licenses accompany the files in `apps/frontend/public/fonts`.

The headline becomes (26px / 34px) at the tablet breakpoint. The page introduction uses (15px / 24px); ordinary buttons and navigation use (13px). Preserve this compact hierarchy.

## Layout

The desktop navigation is (56px) high with a (960px) inner container. The work column is at most (680px), inset (16px) from either viewport edge. It begins (44px) below navigation; jobs follow the main panel after (48px).

At (760px) and below, navigation wraps and the main top spacing becomes (32px). At (480px) and below, panel padding becomes (16px), the preview stacks, and format/quality selectors become one column. Desktop preview media is (172px × 97px); the mobile image spans its container at (16:9).

## Elevation & Depth

Surfaces mainly separate through tone. The work panel has a minimal shadow; the format menu uses a stronger floating shadow. Their exact values are in the sidecar. Do not add decorative elevation to the main composition.

## Shapes

Panels and job-list containers have gently rounded corners using the panel radius. Controls, thumbnails, and badges use the smaller control radius. Job rows use thin separators rather than individual rounded cards.

## Components

Primary actions use a solid green fill and white text; secondary actions use a soft neutral fill. Hover changes color without translation. Focus remains visible through a (2px) outline with (3px) offset; text fields also use a focused border and outline.

Format and quality are native selects. The URL inspection preview presents real backend metadata and media. Advanced options expand within the work panel. Jobs use a compact title, technical percentage, thin progress bar, and descriptive status.

The active navigation item uses a fine underline. Theme switching, controls, progress changes, and panel reveals are immediate in the studio stylesheet, without decorative entrance motion.

Preview images reserve their dimensions and show a compact duration label at the bottom right when the API provides a positive duration. Failed thumbnails fall back to the existing logo without changing the media frame. Below 760px, branding and theme control occupy the first navigation row; tool navigation occupies the second. Footer diagnostics share the footer's 16px horizontal inset.

## Do's and Don'ts

- **Do** retain the supplied light screen's composition in both themes.
- **Do** preserve real application states, accessible labels, keyboard focus, and existing API behavior.
- **Do** update this file and its sidecar from actual implementation changes.
- **Don't** substitute the test fixture for real production preview media.
- **Don't** invent account, settings, or filesystem-destination interactions absent from the backend.
