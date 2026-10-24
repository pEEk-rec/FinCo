# PLAN_LANDING.md: Cinematic landing page for FinCo (desktop first)

Implementer: Claude Code. Owner: the user. Scope: the public welcome/landing page only (`/welcome`, and `/` for a visitor who has not opened the app yet). The app screens are not changed.

Read first: this file, `docs/PLAN_UI.md` (tokens, typography, copy rules, the constellation component, verification loop), `docs/design/refs/` (add the owner's screen recording frames there as `landing_ref_*.png`), `STATUS.md`, `docs/decisions.md`.

---

## 0. Rules
- Autonomous; stop only for: any git command (propose one commit in `STATUS.md`: `Add cinematic landing page`), a dependency not listed in section 4, deployment or money, a test you cannot fix.
- No AI attribution anywhere. Never weaken tests.
- **Honesty rules still apply:** no statistics, user counts, testimonials, logos, awards or ratings. Product claims must be true of the built product. Illustrative UI examples are allowed **only on this page**, each visibly tagged "Example", and never phrased as results.
- Desktop (≥ 1024 px) gets the full experience. Tablet and mobile get a lighter version (section 6). `prefers-reduced-motion` gets a static, complete page.
- **Recorded exception to PLAN_UI §2.4:** atmospheric gradients and a generative sky are allowed **on this page only**. The app stays flat. Record this in `docs/decisions.md`.

---

## 1. What we take from the reference recording (and what we change)
The reference (an EV-camper site) works because of five things. We keep the techniques and replace the content with FinCo's own story.

| Reference technique | FinCo version |
|---|---|
| Full-bleed atmospheric hero (dusk sky, clouds), centred narrow serif headline, glass pill CTA, transparent nav | A **generative dusk sky** (no photo), FinCo serif headline, glass pill "Open FinCo" |
| Hero dissolves into deep colour as you scroll, then a huge centred statement | Scroll transforms **dusk into the app's light canvas**: confusion to clarity is our story |
| Bento cards with imagery and small tag chips | Capability cards with **live micro-animations built from our real components** |
| A row of short facts (OTA, 360°, AI, 24/7) | A row of **principles in words** (no numbers): see 3.5 |
| Final CTA over an animated light-leak gradient, minimal footer | Final CTA over a slow **aurora in FinCo colours**, minimal footer |

**Not copied:** the person-in-clouds photograph (no stock or AI people imagery), the product, the copy, the layout proportions.

---

## 2. The concept: "From scattered to clear"
Money arrives as noise: dozens of payments a week, half of them unexplained. FinCo turns them into something you understand and decide on. The page tells that story with one continuous visual: **particles that are transactions**, drifting like stars in a dusk sky, which fall, gather into labelled clusters and settle as the sky brightens into FinCo's warm light canvas, the same canvas the app uses. When the visitor reaches "Open FinCo", they are already in the app's world.

---

## 3. Sections (desktop)

### 3.1 Hero (100vh)
- **Sky:** WebGL2 fragment shader (hand-written, no library): vertical dusk gradient in FinCo-tuned tones (deep indigo top → lavender → warm peach horizon), two layers of slow fractal-noise clouds near the horizon drifting at different speeds (parallax), a faint grain to avoid banding. Mouse position shifts the cloud layers by a few pixels (inertia, eased). Fallback: a static CSS gradient with the same stops.
- **Particles:** 300 to 600 outlined triangles (1 to 1.5 px stroke, the constellation style from PLAN_UI §2.6) twinkling and drifting slowly; a few in the category hues, most pale. They part slightly around the cursor.
- **Nav:** transparent, wordmark left, three text links ("How it works", "Principles", "Privacy"), glass pill "Open FinCo" right; becomes a solid light bar after the hero.
- **Headline:** serif, light, very large (clamp 64 to 112 px), tight tracking (about -0.02em), centred, white with a soft shadow for contrast. Copy direction (owner may edit in `src/copy/landing.ts`): **"Every rupee, *understood*."** Subhead (sans, 18 px, 70% white): "FinCo reads your payments, asks only when it can't tell, and shows its work. You decide everything; it never moves your money."
- **CTAs:** glass pill "Open FinCo" (frosted, 1 px white border at 40%, backdrop blur) and a text link "See how it works ↓".
- **Entrance:** headline words fade and rise in sequence (600 ms each, staggered 80 ms), sky brightens from 70% to 100% over 1.5 s. No looping text animation.

### 3.2 The transformation (pinned, about 250vh of scroll)
A sticky full-screen stage driven by scroll progress (0 to 1):
- 0 to 0.3: sky darkens slightly at the top while the triangles start to fall and slow; a large centred line appears: **"Scattered."**
- 0.3 to 0.7: particles move along eased paths into 5 to 6 clusters labelled with category names (Food, Rent, Travel, Bills, Savings) and one hollow cluster labelled **"Needs you"** (the review idea). Line changes to **"Sorted."** The sky shader's colours interpolate toward the warm canvas colour.
- 0.7 to 1: the background is now the app's light canvas; clusters settle; one cluster pulses once and a small illustrative overlay card (the real capture overlay component from PLAN_CAPTURE C6, tagged "Example") slides in: "₹250 to Ramesh K. What was this?" with three guess chips; one chip activates on its own. Line changes to **"Understood."**
- Scrolling back reverses everything smoothly. All motion is a pure function of scroll progress (no timers), so it never desynchronises.

### 3.3 Statement
Huge centred serif on the light canvas, two lines: **"It asks at the moment you pay. Never in bulk."** Small mono label above: "HOW IT WORKS". Words reveal as they enter the viewport.

### 3.4 Capability cards (bento grid)
Asymmetric grid on the light canvas (white cards, hairline borders, 14 px radius, generous padding), each card with a serif title, one plain sentence, 2 to 4 small chips, and a **live micro-animation made from real components** (illustrative data, tagged "Example" in the card corner):
1. **Asks only when unsure:** the overlay card with three guesses; one gets chosen, Undo toast appears.
2. **Shows its work:** an evidence list with a confidence label expanding.
3. **Sees what's coming:** the calendar's low/expected/high band drawing in, with a commitment marker.
4. **Your goals, your pace:** a goal progress ring and a bucket bar filling.
5. **Learns what helps you:** an experiment card with "lower than all 6 of your previous comparable weeks" style wording (no figures beyond the example).
6. **Never moves your money:** a quiet card with a lock-free plain statement and the approval chip "You decide".
Hover: card lifts by 2 px with a hairline darkening (no shadows, no tilt), and its animation replays once.

### 3.5 Principles row (instead of statistics)
Four columns, mono label + short serif word: **"Private"** (stays on your device), **"Explained"** (every number traceable), **"Yours"** (nothing changes without you), **"Honest"** (says "not enough data" when it is true). No numbers.

### 3.6 Finale
Full-bleed section with a slow aurora: three to four large blurred radial gradients in FinCo colours (warm amber, soft violet for the agent, a calm green) drifting on long, out-of-phase loops (20 to 40 s), over a deep ink background so it echoes the reference's light leak. Mono label "START WITH ONE PAYMENT", serif headline **"See your month, clearly."**, primary pill "Open FinCo", text link "Read how your data is handled". Implemented with CSS (animated transforms on blurred layers) or the same shader; choose the cheaper one that meets the frame budget.

### 3.7 Footer
Light canvas, wordmark, one-line description, links (How it works, Privacy, GitHub if public). No newsletter form.

---

## 4. Implementation
- **Stack:** existing React + Vite + TypeScript + Tailwind tokens + Motion (scroll-linked values with `useScroll`/`useTransform`, sticky pinning with CSS `position: sticky`). Raw WebGL2 for the sky (one fragment shader, one full-screen triangle). Canvas 2D for particles (reuse the `Constellation` component with a new "story" mode driven by a progress value).
- **Optional dependency (pre-approved):** `lenis` for smooth inertial scrolling on desktop only, disabled for reduced motion and touch devices. Do not add anything else (no Three.js, no GSAP).
- **Typography:** use the PLAN_UI serif at display sizes. If it cannot reach the narrow, high-contrast look of the reference at 96 px or more, use **Instrument Serif** (OFL, self-hosted) for landing display text only; record the choice. Body stays the PLAN_UI sans; labels the mono.
- **Structure:** `src/screens/landing/` with `LandingPage.tsx`, `SkyCanvas.tsx` (+ `sky.frag.glsl`), `TransformationStage.tsx`, `CapabilityGrid.tsx`, `Principles.tsx`, `Finale.tsx`; all copy in `src/copy/landing.ts`; all colours from tokens (new landing-only tokens `sky-top`, `sky-mid`, `sky-horizon`, `aurora-*`).
- **Routing:** `/welcome` always; `/` shows the landing page until the user has opened the app once (local preference), then the dashboard.

---

## 5. Performance and quality budgets (desktop)
- Hero text is real HTML rendered before any canvas: Largest Contentful Paint target under 2.5 s on a mid laptop (measure with the Performance API in Playwright and report).
- 60 fps target while scrolling the transformation stage; main-thread work per frame under 8 ms; shader at device-pixel-ratio capped at 1.5; particle count adapts down if frame time exceeds budget for 1 s.
- Pause the sky and particles when off-screen or the tab is hidden.
- Total added JavaScript for the landing route under 120 KB gzipped (code-split from the app).
- Accessibility: all text meets WCAG AA against its background at every scroll position (test the transformation stage at progress 0, 0.5 and 1); keyboard focus visible on glass buttons; canvases are `aria-hidden`; the story is also told in text.

---

## 6. Tablet, mobile and reduced motion
- **< 1024 px:** no pinning and no smooth scroll; the sky becomes a static gradient image generated at build time (or CSS); 80 to 120 particles; the transformation becomes three stacked panels ("Scattered", "Sorted", "Understood") each with a short in-view animation; bento collapses to one column.
- **Reduced motion:** static sky, particles shown already sorted, no entrance animations, aurora static.

---

## 7. Verification loop (required)
1. Playwright screenshots at 1440×900 and 1920×1080 for hero, transformation progress 0 / 0.5 / 1, statement, grid, principles, finale; plus 390×844 and 1024×768.
2. **Playwright video recording** of a slow scripted scroll from top to bottom at 1440×900; extract frames (every 0.5 s) and review them against `docs/design/refs/landing_ref_*.png` and the checklist below; fix and re-record at least twice.
3. Checklist: no gradient or glass outside the hero and finale; no numbers presented as facts; every illustrative example tagged; text readable at every frame; no layout shift on load; motion reverses cleanly when scrolling up; nothing looks like a template (PLAN_UI §5 rules apply except the recorded gradient exception).
4. Report LCP, average and worst frame time during the scroll, and JS size in `STATUS.md` with the real numbers.

## 8. Done when
All sections built; budgets met or the real numbers and the reason recorded; screenshots and recorded-scroll frames reviewed; reduced-motion and mobile versions work; tests and lint green; one proposed commit recorded.
