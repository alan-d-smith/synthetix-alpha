---
version: alpha
colors:
  canvas: "#050506"
  surface: "#0C0E12"
  raised: "#12151C"
  hover: "#171B24"
  border: "#252D3A"
  foreground: "#F0F4F8"
  secondary: "#A8B2C1"
  muted: "#707C8E"
  dataCyan: "#4CC9E9"
  dataViolet: "#9384FF"
  positive: "#59C58B"
  negative: "#EF6B72"
  warning: "#E5B45B"
typography:
  display:
    fontFamily: "Instrument Sans, Inter, sans-serif"
    fontSize: "24px"
    lineHeight: "30px"
  section:
    fontFamily: "Instrument Sans, Inter, sans-serif"
    fontSize: "16px"
    lineHeight: "22px"
  metric:
    fontFamily: "IBM Plex Mono, ui-monospace, monospace"
    fontSize: "22px"
    lineHeight: "26px"
  interface:
    fontFamily: "Inter, sans-serif"
    fontSize: "13px"
    lineHeight: "20px"
  data:
    fontFamily: "IBM Plex Mono, ui-monospace, monospace"
    fontSize: "12px"
    lineHeight: "16px"
  metadata:
    fontFamily: "Inter, sans-serif"
    fontSize: "11px"
    lineHeight: "16px"
rounded:
  control: "6px"
  panel: "8px"
  maximum: "10px"
spacing:
  xxs: "4px"
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "20px"
  xl: "24px"
  xxl: "32px"
components:
  signalTrace:
    accent: "dataCyan"
  table:
    rowHeight: "40px"
  sheet:
    maxWidth: "480px"
  sidebar:
    width: "224px"
---

## Overview

Synthetix Alpha is a desktop-first, paper-only autonomous options command center. Its visual North Star is a quiet control room: precise, compact, and market-oriented rather than a generic SaaS dashboard. The memorable signature is the Signal Trace, a real status line that exposes the Screen → Gather → Critique → Form → Risk → Execute workflow.

The product must never resemble a crypto casino, neon trading interface, generic AI chatbot, glass-heavy dashboard, or decorative marketing experience.

## Colors

`canvas` and `surface` create a layered near-black market canvas. Cyan is reserved for primary data, current state, and focus. Violet belongs only to comparative research. Positive, negative, and warning colors are semantic; they never communicate status without adjacent text or iconography.

Runtime token ownership is `app/globals.css`; Tailwind aliases consume those CSS variables. This document mirrors exact values and explains their intended roles.

## Typography

Instrument Sans creates restrained identity in page titles and the product mark. Inter carries product interaction. IBM Plex Mono is required for prices, percentages, contract symbols, IDs, timestamps, and tabular values. Use tabular figures for all numeric columns. Do not use oversized KPI typography.

Page title 24/30 weight 600. Section title 16/22 weight 600. Large metric 22/26 weight 500. Body 13/20. Dense table 12/16. Metadata and table headers 11/16, headers uppercase and tracked.

## Layout

Use a 4px rhythm. Desktop content uses 24px padding and a 12-column grid with 20px gutters. The sidebar is 224px, with a 64px compact state. Tablet uses 16px padding; mobile uses 12px. Dense data rows are 40px; standard rows are 48px.

At 1280px and above, preserve the full navigation and side-by-side analysis. From 900px to 1279px, use an icon rail and overlay inspector. Below 900px, stack analytical surfaces and preserve financial tables through horizontal scrolling rather than converting them to cards.

## Elevation & Depth

Static surfaces are separated by hairline borders, not shadows. The canvas carries an extremely low-contrast technical grid. Menus, sheets, dialogs, and command palettes use one low-contrast overlay shadow. Do not use glass blur as a surface treatment; the top utility bar alone may use a subtle translucent background to preserve scroll orientation.

## Shapes

Controls use 6px radius, panels and drawers use 8px, and 10px is the absolute maximum. Pills are reserved for compact state labels and filters. Do not use rounded rectangle cards as decoration.

## Components

Tables are primary financial surfaces: sticky headers, 40px dense rows, no zebra striping, monospace/right-aligned numeric cells, and a cyan left rule for a selected record. Inspector sheets are 480px on desktop and full-screen on mobile. Charts use cyan as the primary series, violet for comparison, semantic colors for sign, opaque tooltips, and subtle horizontal grids.

Status behavior is consistent: cyan/gray means operational, green means approved or positive, warning means delayed or approaching a limit, coral means rejected, halted, error, or unavailable execution. `PAPER` is always visible. `DEMO DATA` must be visible whenever the frontend falls back to mock data.

## Motion

Default transitions 140–180ms. Drawers 180–220ms. Charts draw once on first viewport entry (500–900ms). Respect `prefers-reduced-motion`: no reveal or chart draw, immediate state.

## Do's and Don'ts

Do make the current pipeline state, critic rationale, risk result, and execution limitation immediately visible. Do label historical research, mock data, and unavailable integration explicitly. Do preserve last known data during refresh and preserve table/chart geometry while loading.

Do not simulate successful fills, invent risk analytics or Greeks, hide configured-but-not-enforced governance, add a chatbot, or expose provider credentials to the browser. Respect reduced motion, use semantic controls, keep focus visible, and ensure every chart has a textual data alternative.
