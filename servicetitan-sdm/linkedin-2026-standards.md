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
| About | 1,500 to 2,200 characters for the recommended version, 1,200 minimum for a short alternative. The first sentence says what you do, who for, and a proof number, and the first 200 characters contain the role and a number. Prose paragraphs 350 characters or fewer. Bullet lines 220 or fewer. Tools named inside sentences, not in a keyword list. One call to action at the end that names the role and location. | 200 to 350 |
| Experience, core role | A one-sentence context statement (company, product, buyer segment, deal size), a blank line, then 3 to 5 bullets. 400 to 1,000 characters. | 150 or fewer, including the context statement |
| Experience, supporting role | 1 to 3 bullets, 600 characters or fewer. A context statement is optional. | 150 or fewer |
| Skills | 25 to 30 relevant hard skills in priority order. No generic traits ("Communication") and no software basics. | |
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

## Profile elements beyond copy

| Element | Standard | Evidence |
|---|---|---|
| Profile photo | Square, at least 400 × 400 pixels. Shoulders-up, face about 60% of the frame, direct eye contact, even light, plain background. | Size is confirmed. The rest is practitioner advice. |
| Banner | 1584 × 396 pixels, under 8 MB. Phones show about the center 60% to 75%, and the photo covers the bottom-left, so text goes in the center band only. | Sizes and crop behavior agree across guides. |
| Identity verification | Free. CLEAR in the US. Do it after the name matches your ID. | LinkedIn reports about 60% more profile views and 50% more engagement for verified members. |
| Recommendations | 3 to 5 recent ones, with at least one from a sales leader who can vouch for quota and coaching. Offer to send a draft. | Standard practice. |
| Open to Work | "Recruiters only" if employed. LinkedIn tries to hide it from recruiters at your company but doesn't guarantee it. | LinkedIn behavior. |
| Dates, titles, employment type | Know the month and year you started and left each job, and use the title a former manager would confirm if called. Never stretch a date. | Background-check services verify dates, often to the month, after an offer. |
| Education | Your actual major, not a category label. | Practitioner advice. |
| Activity | About 10 minutes a day of 2 to 3 sentence comments while searching, and follow the accounts you want to be associated with. | Plausible and cheap. LinkedIn hasn't confirmed a ranking effect. |

## Claims we don't rely on

- **Skill assessments and verified-skill badges:** LinkedIn retired them and removed the badges in 2024.
- **"Verified profiles get 30% more recruiter messages":** LinkedIn's own 30% figure was for connection requests.
- **"17x more views from endorsements":** couldn't verify. The practitioner target is about 10 endorsements on each top skill.
- **"Keyword lists are penalized":** no LinkedIn source. We still write tools and outcomes into sentences, which fits LinkedIn's semantic search.
- **"Open to Work Spotlight" boosts ranking:** unverified.
- **Exactly 15 to 25 skills:** not an official rule. We use 25 to 30.
- **Pinned skills:** sources say three, one says five, and the profile has shown five. We order the list so the first three matter most.

See `linkedin-framework-crosscheck.md` for the claim-by-claim comparison against the framework you shared.

## How we check

```
python3 tools/build_linkedin_checklist.py
```

It validates every headline, About, role description, the skills list and post hook in `linkedin-rewrite.md` and the connection notes and InMail in `send-ready/outreach-messages.md`. It then refreshes the compliance table at the top of `linkedin-rewrite.md` and rebuilds the paste blocks in `linkedin-paste-in-checklist.md`. It exits with an error if any hard limit or format rule is broken. Warnings mean a target was missed.

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
- [LinkedIn Help: Skill Assessments, no longer available](https://www.linkedin.com/help/learning/answer/a1690529)
- [LinkedIn Help: verification](https://www.linkedin.com/help/linkedin/answer/140551) and [Social Media Today on LinkedIn's verification statistics](https://www.socialmediatoday.com/news/linkedin-expands-profile-verification-more-users/697245/)
- [LinkedIn: 2026 hiring release (AI-Assisted Search and Hiring Assistant)](https://tcommunity.linkedin.com/product-updates/2026-linkedin-hiring-release-2275) and [LinkedIn Recruiter](https://business.linkedin.com/in/en/hire/recruiter)
- [CareerBldr: pinning skills on LinkedIn 2026](https://careerbldr.com/blog/how-to-pin-skills-on-linkedin-2026/) and [LinkedInPreview: skills section 2026](https://linkedinpreview.com/blog/linkedin-skills-section-optimization-2026)
- [Neal Schaffer: LinkedIn banner size](https://nealschaffer.com/linkedin-banner-size/) (1584 × 396, mobile crop, photo overlap)
- [LinkedIn Help: Personalize invitations to connect](https://www.linkedin.com/help/linkedin/answer/46662) (urges brevity, no numeric cap)
