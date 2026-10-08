# LinkedIn 2026 Copy Standards

Every LinkedIn headline, About section, experience block, post hook and message drafted for this application must meet these limits and targets. `tools/build_linkedin_checklist.py` checks the copy in `linkedin-rewrite.md` and `send-ready/outreach-messages.md` against them and fails on any hard-limit or format violation.

**Read this first:** LinkedIn publishes very few of these numbers. They come from third-party guides (linked below) that agree on the hard limits but disagree on what shows before "see more." Treat the visible-length figures as estimates, and check your own profile in the phone app after every change.

## Hard limits (longer text won't save)

| Field | Limit | Notes |
|---|---|---|
| Headline | 220 characters | Older guides say 120. One outlier claims 240 on mobile. |
| About | 2,600 characters | Stay at least 100 under the cap. |
| Experience title | 100 characters | |
| Experience description | 2,000 characters | Confirm in the editor. Only one source stated this plainly. |
| Skills | 100 entries | LinkedIn Help Center. Older guides say 50. |
| Post | 3,000 characters | |
| Connection note | 300 characters, **200 on many free accounts** | Free accounts may also be capped at a few notes a month. We write to 200 so it works anywhere. |
| InMail | 200-character subject, about 1,900-character body | Premium or Sales Navigator feature. |

## What shows before "see more" (estimates)

| Where | Visible length |
|---|---|
| Headline in search, comments and mobile feeds | About 45 to 70 characters (estimates run 40 to 80) |
| About on a phone | About 200 characters (desktop shows about 265 to 300) |
| Post | About 210 characters on desktop, about 140 on mobile |

So: the headline opens with the job title and the top keyword. The About opens with the role plus one proof number. A post hook fits in 140 characters.

## Targets we hold ourselves to

| Field | Target | Words |
|---|---|---|
| Headline | 120 to 220 characters. First 60 characters contain "Sales Development" or "SDR". No hype words, no "Open to Work". | About 25 to 35 |
| About | 1,500 to 2,200 characters for the recommended version, 1,200 minimum for a short alternative. First 200 characters contain the role and a number. Prose paragraphs 350 characters or fewer. Bullet lines 220 or fewer. One call to action at the end. | 200 to 400 |
| Experience, core role | 400 to 1,000 characters, 3 to 6 bullets | About 60 to 160 |
| Experience, supporting role | 600 characters or fewer, 1 to 3 bullets | |
| Every bullet | 35 words or fewer and 230 characters or fewer (two desktop lines). Opens with the result. | |
| Numbers in bullets | First bullet of each role has a number. At least half of the bullets have one. | |
| Post | Hook 140 characters or fewer. Total under 1,300 (the limit is 3,000). | |
| Connection note | 200 characters or fewer, counted with a 12-character first name | |
| InMail | Body under 1,000 characters (our style target, the limit is 1,900) | |

## Format rules

- **Plain text only.** LinkedIn fields don't render markdown, so no `**`, backticks or `#` headings.
- **Bullets** are the "•" character at the start of a line.
- **No Unicode "bold" or "italic" lettering.** It isn't searchable, and screen readers read it badly.
- **No emojis** in the headline, About or experience text.
- **Blank line between paragraphs.** Keep blocks to two or three lines so they read on a phone.
- **First person** in the About. Swap stock words ("passionate," "results-driven") for something concrete.
- **Numbers as digits** ("30–35", "8+", "27%").
- **No placeholders** in paste text. Anything in square brackets means the block isn't ready.
- **Name tools inside bullets.** Recruiters search for them.

## How we check

```
python3 tools/build_linkedin_checklist.py
```

It validates every headline, About, role description and post hook in `linkedin-rewrite.md` and the connection notes and InMail in `send-ready/outreach-messages.md`. It then refreshes the compliance table at the top of `linkedin-rewrite.md` and rebuilds the paste blocks in `linkedin-paste-in-checklist.md`. It exits with an error if any hard limit or format rule is broken. Warnings mean a target was missed.

## Sources

- [UniLink: LinkedIn character limits 2026](https://www.unilink.us/blog/linkedin-character-limits-2026) (experience description 2,000, title 100, practical target 400 to 900)
- [PromiseClick: LinkedIn character limits 2026](https://www.promiseclick.com/blog/linkedin-character-limits-2026)
- [PromiseClick: About section best practices 2026](https://www.promiseclick.com/blog/linkedin-about-section-best-practices-2026) (1,500 to 2,200 characters)
- [PromiseClick: Experience section best practices 2026](https://www.promiseclick.com/blog/linkedin-experience-section-best-practices-2026) (lead with measurable outcomes)
- [ConnectSafely: About section](https://connectsafely.ai/articles/linkedin-about-section) (about 265 to 275 characters before "see more" on desktop, about 200 on mobile)
- [AuthoredUp: About section](https://authoredup.com/blog/linkedin-about-section) (formatting, Unicode lettering caveats)
- [Eden: LinkedIn character limits 2026](https://eden.so/blog/linkedin-character-limits/) and [Justpollen](https://www.justpollen.com/blog/linkedin-character-limit) (headline visible length, post limits)
- [Shopify: LinkedIn headline examples](https://www.shopify.com/blog/linkedin-headline-examples) (first 45 or so characters carry the weight)
- [LinkedIn Help: Skill endorsements](https://www.linkedin.com/help/linkedin/answer/31888) (skills cap)
- [LinkedInPreview: post character limit 2026](https://linkedinpreview.com/blog/linkedin-post-character-limit-2026) and [the "see more" cutoff](https://medium.com/@artyom.shimanski/the-linkedin-see-more-cutoff-why-210-characters-decide-your-posts-fate-bc05bf211e0f)
- [ConnectSafely: LinkedIn message character limits 2026](https://connectsafely.ai/articles/linkedin-message-character-limit-guide-2026) (connection note and InMail limits)
- [LinkedIn Help: Personalize invitations to connect](https://www.linkedin.com/help/linkedin/answer/46662) (urges brevity, no numeric cap)
