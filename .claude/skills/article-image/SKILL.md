---
name: article-image
description: Makes the cover image of a konnekt.cz article. From the article's topic it picks Czech attributes, a real university building or the school's official logo, generates or finds three candidates, publishes one page for Azamat to pick from, and after the pick commits the chosen image as the article's cover. Use when an article needs a cover or a new one.
---

# Article image

An article's cover is one image, 1536×1024. The site uses it twice: as the
cover on the article page, and, cropped, inside the dark link card
(`og:image`) that Telegram and other apps show when someone shares the link.
The card itself is drawn by the site at build time; this skill only makes the
image. The rules for images are in `docs/product/articles.md`, section
«Cover image». Read them first; they win over anything here.

## 1. Read the article and decide what it is about

Read `web/site/src/content/articles/<lang>/<slug>.md`: title, description,
rubric and the sections. Decide which case it is:

- **Country:** admission in general, nostrification, visa and residence,
  insurance, money, work, housing in general. The image carries a Czech
  attribute: the Czech flag, a view of Prague (Charles Bridge, Prague Castle),
  a Czech street without readable signs.
- **Universities in general:** a Czech attribute as above, plus the official
  logos of the schools the article names, as a strip (`coverLogos`, several
  ids).
- **One university or faculty:** a real photo of that school's or faculty's
  own building, plus its official logo (`coverLogos`, one id).

## 2. Make three candidates

Three different options, so the pick is a real choice: for example two
generated scenes and one real photo, or three real photos of the building
from different sides.

**Real photo (Wikimedia Commons).** Required for a building: a generated
building must never stand in for a real one.

```bash
S=.claude/skills/article-image/scripts
node $S/commons.mjs search "ČVUT Dejvice budova"          # OK = usable licence, ≥1536 px wide
node $S/commons.mjs get "File:…jpg" $W/c.jpg                # also writes c.jpg.credit.json
```

Open the photo and check it yourself: it is the right building (compare with
the school's own site), no recognisable faces in the foreground, no third-party
logos or advertising. Crop or not, the credit goes with it.

**Generated scene.** Write each prompt in English from these parts:

- Style, one of:
  - photo: `Natural editorial photograph, 35mm lens, soft daylight, calm warm neutral colours with small accents of muted ink blue and muted brick red, uncluttered, quiet.`
  - object: `Minimal still life rendered as soft matte clay 3D, one calm object group, on a plain seamless warm light-grey backdrop (#efede8) filling the whole frame, soft contact shadow, muted palette of warm off-white, muted ink blue (#3f6bb8) and muted brick red (#b23a3f), a little deep green.`
- The scene, with the Czech attribute in it. For the flag write it out:
  `a small desk flag of the Czech Republic on a thin stand, drawn exactly: white upper half, red lower half, a blue isosceles triangle from the pole side reaching the centre of the flag`.
- The rules, always, word for word:
  `Strictly: no people, no faces, no hands, no logos or brand marks, no emblems or coats of arms, no readable text, letters or numbers anywhere; any paper, card or booklet is completely blank. Composition: the main subject sits in the centre third of the frame, calm empty space to the left and right, so the image also works cropped to a near-square centre.`

Never ask the model for a real building, a university, a logo, a document or
a view from a window of a real place: it invents them.

Put the prompts in `$W/jobs.json` (`[{"id":"A","prompt":"…"}]`) and run:

```bash
op-broker run --reason "Konnekt: обложка статьи <slug>" \
  -e OPENAI_API_KEY="<op:// reference of «OpenAI API — openwhispr — omarchy», see ~/Knowledge/shared/apps/1password.md>" \
  -- node $S/generate.mjs $W/jobs.json $W
```

`generate.mjs` asks OpenAI for the newest `gpt-image-*` model available to the
key at run time and uses it; it prints the model and the cost (about $0.04
per image at 1536×1024, high). Never print the key or put it in a file.

Look at every generated image at full size before it goes further: a face,
a hand, a drawn logo, letters, a wrong flag (the blue triangle is at the
pole, white is on top) — throw it away and generate again.

## 3. One page for Azamat

Write `$W/manifest.json` with the articles and their candidates (`file`,
`source`, `credit` for a real photo, `logos`, `focus` — the horizontal point
from 0 to 1 the link card's crop centres on — and a one-line `note`), then:

```bash
node $S/pick-page.mjs $W/manifest.json $W/page
```

Publish `$W/page/index.html` with the Artifact tool, passing `$W/page/files.json`
as `files`. Check it at 390 and 1440 first. Post the link with the cost of the
round to whoever asked (in #konnekt: `agora post konnekt --reply <id> …`). The
page draws the link card after the site's template; once the site's own card
renders, it is the reference.

## 4. After the pick

On a branch from a fresh `origin/main`:

```bash
node $S/install.mjs ru <slug> $W/<picked file> --alt "<what is in the picture, in Russian>" \
  [--focus 0.6] [--logos cvut,cvut-fit] [--credit $W/c.jpg.credit.json]
```

It writes `web/site/src/assets/covers/<translationKey>.jpg` (one file for all
the article's languages) and sets `cover`, `coverAlt`, `coverFocus`,
`coverLogos`, `coverCredit` in the article. Run it for each language that has
the article, with that language's `coverAlt`. Build the site
(`pnpm --dir web exec astro build --root site`), look at the article page and its
link card (the `og:image` URL) at 390 and 1440 in both themes, and open a pull request. A logo id
must exist in `web/site/src/assets/logos/` with its source in the registry;
add a new school's official file there first (from the school's own site,
never redrawn).

Tools: node 22+, ffmpeg, op-broker.
