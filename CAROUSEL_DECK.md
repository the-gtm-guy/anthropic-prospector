# LinkedIn carousel: anthropic-prospector

This is a six-slide LinkedIn document post: portrait slides at 1080 × 1350 px (4:5),
exported as one PDF, plus the post and first-comment copy. Copy limits: a headline of eight
words or fewer and a body of 25 words or fewer per slide. These limits, the palette and the
contrast table below are checked by [tests/test_carousel.py](tests/test_carousel.py).

Ground rules:

- **Show what the tool does, nothing more.** No meetings booked, pipeline or revenue
  numbers: there are none to show.
- **Label the data.** Every piece of tool output on a slide comes from the fictional sample
  territory, and the slide says so.
- **No Anthropic or Claude logos.** This is an independent project. The palette and type
  follow Anthropic's public brand guidelines; the logos are not ours to use.

## Design system

### Palette

| Name | Hex | Use |
|---|---|---|
| Dark | `#141413` | Dark slide background; text on light slides |
| Light | `#faf9f5` | Light slide background; text on dark slides |
| Mid Gray | `#b0aea5` | Captions and slide numbers on dark slides; hairlines |
| Light Gray | `#e8e6dc` | Cards and chips on light slides |
| Orange | `#d97757` | The one primary accent per slide |
| Blue | `#6a9bcc` | Secondary accent: connectors, diagrams |
| Green | `#788c5d` | Tertiary accent: "validated", "strong", success chips |

### Contrast

WCAG 2.x ratios. AA needs 4.5:1 for body text and 3:1 for large text (24 px bold or 32 px
regular and up).

| Foreground | Background | Ratio | Verdict |
|---|---|---|---|
| Light | Dark | 17.50:1 | Any text |
| Mid Gray | Dark | 8.29:1 | Any text |
| Blue | Dark | 6.30:1 | Any text |
| Orange | Dark | 5.90:1 | Any text, including highlighted words |
| Green | Dark | 5.01:1 | Any text |
| Dark | Light | 17.50:1 | Any text |
| Dark | Light Gray | 14.73:1 | Any text, e.g. on chips |
| Green | Light | 3.49:1 | Large text only |
| Orange | Light | 2.96:1 | Shapes only, never text |
| Blue | Light | 2.78:1 | Shapes only, never text |
| Mid Gray | Light | 2.11:1 | Hairlines only, never text |

The resulting rule: **accent-coloured words appear only on dark slides.** On light slides
the accents are fills, bars and icons, and all text is Dark.

### Type and layout

- **Headlines:** Poppins SemiBold, 72–80 px, at most two lines, tracking −1%.
- **Body:** Lora Regular, 36 px, line height 1.35, at most four lines.
- **Labels and slide numbers:** Poppins Medium, 24 px.
- **Terminal and code:** a monospace face (JetBrains Mono or SF Mono), 26 px.
- **Grid:** 1080 × 1350 px with 80 px outer margins. The headline sits in the top third,
  and the visual fills the middle.
- **Footer:** your name or handle bottom left, "n / 6" bottom right. On dark slides both
  are Mid Gray. On light slides they are Dark at 70% opacity, since Mid Gray fails as text
  on Light.
- **One idea and one orange accent per slide.** Leave at least a third of the slide empty.

## Slides

### Slide 1: Hook

- **Headline:** Stop spraying lists. Start with signals.
- **Body:** I built a CLI that turns public hiring, web and DNS signals into qualified accounts and ready-to-send briefs.
- **Background:** Dark
- **Visual:** A thin signal line rising from left to right, with three nodes along it labelled "hiring", "stack" and "DNS".
- **Design prompt:** Portrait 1080×1350 slide, solid background #141413. Headline top-left in Poppins SemiBold 80 px, colour #faf9f5, with the single word "signals" in #d97757. Body below in Lora 36 px #faf9f5. Lower half: one 4 px line in #d97757 rising gently from the bottom-left corner to the right margin, with three 20 px circular nodes on it, labelled "hiring", "stack" and "DNS" in Poppins Medium 24 px #b0aea5. Generous negative space, no gradients, no logos. Footer: handle bottom-left and "1 / 6" bottom-right in Poppins Medium 24 px #b0aea5.
- **Alt text:** Dark slide headed "Stop spraying lists. Start with signals." A line rises across the slide through three points labelled hiring, stack and DNS.

### Slide 2: The problem

- **Headline:** Cold lists have no "why now"
- **Body:** Most accounts on a list aren't qualified, and nothing tells the rep what changed. So outreach sounds generic and gets ignored.
- **Background:** Light
- **Visual:** Five identical grey list rows. One row is lifted out with an orange outline and a "why now?" chip.
- **Design prompt:** Portrait 1080×1350 slide, solid background #faf9f5. Headline top-left in Poppins SemiBold 76 px #141413, body in Lora 36 px #141413. Middle: five stacked horizontal cards in #e8e6dc with 24 px corner radius, each holding two short placeholder bars in #b0aea5. The third card is shifted 32 px right and outlined with a 4 px #d97757 stroke, with a small chip reading "why now?" in Poppins Medium 24 px #141413 on #e8e6dc. Flat style, no shadows, no logos. Footer: "2 / 6" bottom-right in Poppins Medium 24 px #141413 at 70% opacity.
- **Alt text:** Light slide headed "Cold lists have no why now". Five identical list rows; one row stands out with an orange outline and a tag asking "why now?".

### Slide 3: How it works

- **Headline:** Scrape. Map a wedge. Score. Brief.
- **Body:** Job boards, company pages and DNS become cited evidence. Rules pick a Claude wedge and score MEDDPICC; Claude drafts the outreach.
- **Background:** Light
- **Visual:** Four cards in a 2×2 grid, joined by arrows in reading order: Scrape, Wedge, Score, Brief, each with a two-line caption.
- **Design prompt:** Portrait 1080×1350 slide, solid background #faf9f5. Headline top-left in Poppins SemiBold 72 px #141413, body in Lora 34 px #141413. Middle: a 2×2 grid of rounded cards (24 px radius) in #e8e6dc, joined in reading order by 4 px arrows in #6a9bcc. Each card has a 72 px circle filled #d97757 holding a step number in Poppins SemiBold 40 px #141413, a title in Poppins SemiBold 36 px #141413, and a caption in Lora 26 px #141413. Titles and captions: "Scrape: job boards, pages, DNS", "Wedge: caching, thinking, marketplace", "Score: MEDDPICC and tier", "Brief: why now, four touches". Flat, no logos. Footer "3 / 6".
- **Alt text:** Light slide headed "Scrape. Map a wedge. Score. Brief." Four connected cards show the pipeline: scrape job boards, pages and DNS; map to a Claude wedge; score MEDDPICC; write the brief.

### Slide 4: The scorecard

- **Headline:** Unknown isn't bad. It's a question.
- **Body:** Every element shows score, status and next action. Unknowns lower coverage, not the score. Claude can't inflate scores or invent evidence.
- **Background:** Dark
- **Visual:** A terminal screenshot of the MEDDPICC table with an "Illustrative data" badge, plus two orange callouts on "unknown" and "validated".
- **Design prompt:** Portrait 1080×1350 slide, solid background #141413. Headline top in Poppins SemiBold 72 px #faf9f5, with "a question" in #d97757. Body in Lora 32 px #faf9f5. Middle: a terminal window with 24 px corner radius and a 1 px #b0aea5 border, containing a crisp screenshot of the scorecard (capture it as described under Production notes). Top-left of the window: a chip reading "Illustrative data" in Poppins Medium 22 px #141413 on #788c5d. Two callout lines in #d97757 point to an "unknown" row and the "validated" row, labelled in Poppins Medium 24 px #d97757. No logos. Footer "4 / 6" in #b0aea5.
- **Alt text:** Dark slide headed "Unknown isn't bad. It's a question." A terminal shows a MEDDPICC scorecard for a fictional company, labelled illustrative data, with callouts on an unknown element and a validated one.

### Slide 5: The wedges

- **Headline:** Three Claude wedges, each tied to evidence
- **Body:** Prompt caching for repeated context. Extended thinking for multi-step agents. Cloud marketplace buying through Bedrock, Vertex AI or Foundry.
- **Background:** Light
- **Visual:** Three rows, one per wedge. Each has a simple accent-coloured shape and two "triggered by" chips.
- **Design prompt:** Portrait 1080×1350 slide, solid background #faf9f5. Headline top-left in Poppins SemiBold 72 px #141413, body in Lora 34 px #141413. Middle: three full-width rows separated by 1 px hairlines in #b0aea5. Each row has, on the left, a 96 px flat shape: three stacked offset cards in #d97757 for prompt caching, a branching path in #6a9bcc for extended thinking, three overlapping cloud outlines in #788c5d for cloud marketplace. Next to the shape is the wedge name in Poppins SemiBold 40 px #141413, and on the right two chips in Lora 24 px #141413 on #e8e6dc. Chips: "RAG", "long documents" / "agents", "evals" / "AWS", "Google Cloud". Flat, no logos. Footer "5 / 6".
- **Alt text:** Light slide headed "Three Claude wedges, each tied to evidence". Rows for prompt caching (triggered by RAG and long documents), extended thinking (agents and evals) and cloud marketplace (AWS and Google Cloud).

### Slide 6: Try it

- **Headline:** Public data only. Open source. Try it.
- **Body:** Runs with zero keys: try prospector qualify lexiconlegal.example --offline. Respects robots.txt and rate limits; no personal data scraped.
- **Background:** Dark
- **Visual:** The command in a code chip, the repository URL, and an optional QR code to the repository.
- **Design prompt:** Portrait 1080×1350 slide, solid background #141413. Headline top-left in Poppins SemiBold 80 px #faf9f5, with "Try it." in #d97757. Body in Lora 34 px #faf9f5. Middle: a code chip with a 2 px #b0aea5 outline and 16 px radius, containing `prospector qualify lexiconlegal.example --offline` in a monospace 28 px #faf9f5. Below it: github.com/the-gtm-guy/anthropic-prospector in Poppins Medium 30 px #6a9bcc, and an optional 240 px QR code to the same URL in #faf9f5 on #141413 with a quiet zone. No logos. Footer "6 / 6" in #b0aea5.
- **Alt text:** Dark slide headed "Public data only. Open source. Try it." The command to run the tool offline, the repository address github.com/the-gtm-guy/anthropic-prospector and a QR code to it.

## LinkedIn post

### Post copy

> Most outbound starts from a list. I wanted mine to start from evidence.
>
> So I built anthropic-prospector, a Python CLI that qualifies West Coast B2B startups for
> Claude:
>
> → reads public job boards (Greenhouse, Lever, Ashby), company pages and DNS
> → turns what it finds into cited evidence: "hiring 5 AI engineers", "building on the OpenAI API", "runs on Google Cloud"
> → maps each account to a Claude wedge: prompt caching, extended thinking, or buying through a cloud marketplace
> → scores MEDDPICC honestly: unknown is grey, not red, and Claude can't inflate a score
> → drafts a four-touch outbound brief with a why-now
>
> It runs with zero API keys on a fictional sample territory, respects robots.txt and rate
> limits, and never scrapes personal data.
>
> The slides walk through how it works. The code and a sample brief are linked in the
> comments.
>
> What's the one signal you trust most before a first touch?
>
> #SalesDevelopment #MEDDPICC #Claude #Python #GTM

### First comment

> Code: https://github.com/the-gtm-guy/anthropic-prospector
> A sample brief from the fictional territory: https://github.com/the-gtm-guy/anthropic-prospector/blob/main/examples/lexiconlegal-example.md

LinkedIn tends to show posts with outside links to fewer people, so the links go in the
first comment.

### Document title

How I qualify accounts from public signals

## Production notes

**Capture the scorecard for slide 4.**

1. Run `COLUMNS=100 prospector qualify lexiconlegal.example --offline` in a terminal with
   a dark theme set to the deck palette: background #141413, foreground #faf9f5.
2. Screenshot the table at 2× scale.
3. Crop to the banner, the table and the verdict line. Keep the "DATA MOCK" banner in
   frame.

**Export the PDF.**

1. Build each slide as a 1080 × 1350 frame (Canva custom size, or a Figma frame).
2. Export all six slides as one PDF with the fonts embedded (Canva: PDF Standard;
   Figma: export the frames as PDF).
3. Keep it under 100 MB and name it `anthropic-prospector-how-it-works.pdf`.
4. On LinkedIn: Start a post → Add a document → upload the PDF → set the document title
   above.
5. Then paste the post copy, publish, and add the first comment.

**Accessibility.** LinkedIn documents have no per-page alt text. The post copy covers what
the slides say, and the alt text above can go in the document description, or serve as
speaker notes if you present the deck.

**Before posting:**

- [ ] The repository is public, and the README's Mermaid diagram renders.
- [ ] The slide 4 screenshot comes from the current version.
- [ ] Each slide's text matches this file, and the copy limits still hold:
      run `pytest tests/test_carousel.py`.
- [ ] No logos, no invented results.
