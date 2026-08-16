# Brand - fathm

**Locked:** 2026-08-16  
**Visual system:** **final** - `brand/fathm-brand-final.html` (canonical)  
**Historical:** `brand/historical/fathm-brand-system-v1.html` (sunk-a era; do not use for new work)

## Definition

**fathm** *(v.)* - to understand something fully, down to its source.

## Lock

| Item | Value |
|------|--------|
| Product / company | **fathm** |
| Format / standard | **Analysis Package** (`ap`, e.g. `ap/0.2`) |
| Metaphor | **chart room** · **sounding line** |
| Tagline | to understand something fully, down to its source |
| Support line | the provenance standard for ai-driven analysis |
| Mark idea | **The letter is the instrument** - F is a sounding line |
| Repo | https://github.com/TM-Elden/fathm |

## The mark (final)

One object. Crop it = icon. Set it before **athm** = wordmark. Nothing else to keep consistent.

### Construction rules

| ID | Rule |
|----|------|
| **R·01** | **The arms are type.** Top arm at cap height, second at x-height - bone - so they shake hands with the letters that follow. |
| **R·02** | **The line is the instrument.** Brass always. Enters above the word and exits below it - only element that crosses the baseline. |
| **R·03** | **The weight is the payoff.** Round brass lead ~1.3× stroke. Settles below the baseline: the measurement, taken. |
| **R·04** | **Flat forever.** No gradients, glows, or shadows on the mark itself. Depth belongs to the environment, not the object. |

### Wordmark composition
- SVG **F / sounding-line** + serif **athm** (Reckless Neue Light preferred; Newsreader fallback)
- Always lowercase body letters
- Never: sunk brass "a" (retired), all-caps wordmark, side-by-side second mark in body, gradients on the F

### Icon / avatar
Crop the F mark alone (ink ground + brass/bone strokes, or brass ground + ink strokes for small tiles).

### Motion (optional)
Hero "sounding" drop/settle is allowed; respect `prefers-reduced-motion`.

## Color tokens (final)

| Token | Hex | Use |
|-------|-----|-----|
| Ink | `#07090D` | page background |
| Ink 2 | `#0A0E16` | elevated ink / blueprint panels |
| Slate | `#121826` | cards, panels |
| Brass | `#E8B36A` | instrument line, weight, accent |
| Brass dim | `#B98C4F` | brass on light (bone) surfaces |
| Driftwood | `#93856F` | secondary text, captions |
| Bone | `#E8E0D5` | primary text / light ground (final; was `#F4EFE6` in v1) |
| Line | `rgba(147,133,111,.22)` | hairlines |

Brass budget: still ~10% of a page max for accent - instrument is brass by nature.

## Type

| Role | Face | Job |
|------|------|-----|
| Display / voice | **Reckless Neue** Light (fallback **Newsreader**) opsz 72 | definitions, lockup "athm", headlines |
| UI / body | **Archivo** | UI, body, nav |
| Utility / data | **IBM Plex Mono** | eyebrows, labels, timestamps, provenance |

## Copy: the definition device

```
[term] (n./v.) - [plain definition, <=14 words, no jargon].
```

Rules: lowercase term · serif · part-of-speech brass italic · one entry per surface · must be true of the product.

### Lexicon

| Term | Definition |
|------|------------|
| fathm (v.) | to understand something fully, down to its source. |
| sounding (n.) | a single verified measurement. the unit of trust. |
| provenance (n.) | where a claim came from, and how it got here. |
| the standard (n.) | one structure for every analysis. enforced, not suggested. |
| chart room (n.) | where all your data packages can be questioned at once. |

### Surfaces (see final HTML)
- Hero lockup + definition + mono kicker  
- Deck title slide  
- App icon tiles  
- Business card (mark corner)  
- Launch post (definition first, news plain, link last - no emoji/hashtags)

## Do / don't

**Do**
- Reproduce F from SVG geometry in brand-final  
- Use Reckless/Newsreader for voice lines  
- Say Analysis Package for the format; fathm for the product  

**Don't**
- Ship the v1 sunk-a wordmark on new surfaces  
- Put two marks on one surface  
- Style the instrument with gradients  

## Engineering docs
Prefer plain hyphen `-` in markdown/specs. Brand HTML may use its own punctuation.

## Domain (open)
fathm.ai / org handles - track separately.
