# IMAGE_PROMPTS — generation prompts for the teaching front door

Ready-to-paste prompts for an image model (DALL·E, Midjourney, Imagen,
Firefly…) to produce the visual identity of the CBI/QVDF platform: state the
mission, show the key features, attract students. Conventions used
throughout: clean technical-illustration style, generous white space, a
restrained palette (deep slate `#1d232b`, signal blue `#2563eb`, alert red
`#b3261e`, confirm green `#2f9e5e`, amber `#c07a12`), no photorealism, no
clutter. Add `--ar 16:9` (or your tool's equivalent) for banners; square for
badges. Text rendering in image models is unreliable — where a caption
matters, generate the art and typeset the words yourself afterward.

---

## 1. Hero banner — "Diagnose congestion like a doctor"

> Wide technical-illustration banner. Left half: a stylized freeway corridor
> at dusk seen from above, one direction glowing with a red queue that fades
> to green downstream of a single pinch point; small detector dots along the
> road blink like vital-sign monitors. Right half: the same corridor
> abstracted into a clean space-time heatmap panel (time →, milepost ↑) with
> a red wedge, annotated by three thin callout lines to the points T0, T2,
> T3. A subtle stethoscope-shaped curve connects the real road to the
> diagram. Flat vector style, deep slate background, blue/red/green accent
> palette, generous negative space for a headline. No text in image.

*Typeset afterward:* "Do we actually understand freeway congestion?" +
"CBI/QVDF — the training platform for congestion diagnosis."

## 2. The medical-school analogy poster

> Split-panel editorial illustration. Left: a medical student studying a
> patient's vital-sign monitor (ECG trace). Right, mirrored composition: a
> young traffic engineer studying a corridor speed heatmap on an identical
> monitor — the ECG trace and the speed profile share the same visual rhythm.
> Between the panels, one connecting line morphs from heartbeat waveform into
> a traffic speed curve with a clear dip and recovery. Warm, human, hopeful
> tone; flat illustration; slate/blue/red palette; room at the bottom for a
> caption. No text.

*Caption:* "Real cases. Real mechanisms. Real diagnosis. — Traffic engineers
train like doctors here."

## 3. The queue anatomy diagram (T0 / T2 / T3)

> Minimalist scientific diagram, textbook quality. A single elegant curve of
> vehicle speed over one day dips into a valley: mark the descent point, the
> valley bottom, and the recovery point with three circled anchors. Beneath
> the curve, a subtle red area fills the valley (the queue), its width
> labeled by a horizontal bracket. To the right, a tiny freeway cross-section
> shows the queue physically stretching upstream. Extremely clean, thin
> lines, one red accent, mostly monochrome slate on white. Leave the three
> anchors empty circles for later labeling. No text.

*Labels to add:* T0 (onset) · T2 (worst) · T3 (clearance) · P = duration ·
"low speed is a symptom — the anatomy is the diagnosis."

## 4. The corridor cube — one week as a tensor

> Isometric 3-D illustration of a translucent glass cube made of thousands of
> tiny colored cells (green to red). The three visible faces are subtly
> different: one face shows a road with sensor dots (space), one shows a
> clock arc (time of day), one shows a small calendar strip (days). From one
> corner, three thin slices float away from the cube, each revealing a clean
> 2-D heatmap pattern. Modern data-visualization aesthetic, dark background,
> glowing cells, precise and calm. No text.

*Caption:* "One corridor-week is a single mathematical object. Three spatial
patterns × four rhythms × two day-types rebuild it — congestion is low-rank."

## 5. The engine arena — models compete on the same day

> A stylized amphitheater or racing-lane illustration: four abstract
> "engines" (a parabola, a cubic curve, a quartic bell, a trapezoid — each a
> glowing line-figure with its own accent color) race across the same
> space-time heatmap track toward a finish gate labeled with a checkmark
> shield. A scoreboard silhouette in the background. Playful but precise,
> flat vector, dark slate arena, four accent colors. No text.

*Caption:* "PAQ vs QVDF vs Newell vs trapezoid — every episode picks its own
winner. No model wins everywhere; the arena keeps everyone honest."

## 6. The physics gate — AI must pass through theory

> A grand minimalist gateway (two clean pylons and a beam) standing on a
> highway at dawn. Streaming toward it: colorful, slightly chaotic ribbons of
> "AI" data (neural-net node clusters, scattered points). Passing through the
> gate, the ribbons emerge ordered into smooth, parallel flow lines colored
> by speed. On the gate's beam, three small emblems: a conservation-law
> equation glyph, a fundamental-diagram curve glyph, a checkmark. Dramatic
> but clean; slate/blue with golden dawn light. No text.

*Caption:* "AI does not replace traffic-flow theory. It must pass through it.
— LWR · Newell · Daganzo, enforced in code."

## 7. The learning ladder — from hello world to corridor doctor

> A vertical illustrated ladder/staircase in five steps, each step a small
> vignette: (1) a green terminal checkmark; (2) a single sensor's day-curve
> with three hand-drawn circles; (3) a two-page paper with figures matching a
> screen beside it; (4) a full corridor dashboard glowing; (5) at the top, a
> person confidently pointing at a wall-sized corridor map explaining it to
> others. Rising warm light toward the top. Flat, friendly, aspirational
> style; palette as above. No text.

*Step labels:* 5-second health check → one sensor, one day, by hand →
reproduce the paper exactly → run a real corridor → diagnose and teach.

## 8. Recruiting badge / sticker

> Circular badge design, sticker-like: at the center a freeway on-ramp merges
> into a rising arrow whose head becomes a small fundamental-diagram curve;
> around it a thin ring. Bold, simple, two-color (slate + signal blue) with a
> single red queue accent under the arrow. High contrast, legible at 5 cm.
> Leave the ring empty for text. No text in image.

*Ring text to typeset:* "CBI · QVDF — TRAIN ON REAL FREEWAYS" (top) ·
"physics-gated AI" (bottom).

---

## Usage notes

- Generate at 2× the display size; downscale for crispness.
- For the website front door, pair image 1 (hero) with image 7 (ladder)
  below the fold; images 3 and 4 belong at the top of THEORY_FOUNDATIONS and
  FLOW_TENSOR_MATH respectively; image 6 belongs on MISSION.md; image 8 is
  for slides, stickers, and the GitHub social-preview card.
- Keep all final text typeset in the page, not baked into the image — it
  stays editable, translatable, and accessible.
