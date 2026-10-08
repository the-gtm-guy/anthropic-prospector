# ServiceTitan: Manager, Sales Development I (JR116181, US Remote)

Job link: https://servicetitan.wd1.myworkdayjobs.com/en-US/ServiceTitan/job/US-Remote/Manager--Sales-Development-I_JR116181

## Do these in order

1. **Update LinkedIn:** `linkedin-paste-in-checklist.md`. Every box in it is plain text you can paste.
2. **Text Arman for the referral:** `send-ready/outreach-messages.md`, section 1. Send the resume and blurb once he replies.
3. **Apply** with `send-ready/Johnny_Scott_Jorgenson_Resume.pdf` (or the `.docx`) and `send-ready/cover-letter.md`.
4. **Message the hiring manager** with the notes in `send-ready/outreach-messages.md`, section 3.
5. **Prep for interviews:** `hiring-manager-review.md` (8 likely questions with coaching) and `performance-benchmarks.md` (how your numbers compare).

## Before you submit

- [ ] Renew both HubSpot certifications (they expire in Oct 2026) or remove them from the resume and LinkedIn.
- [ ] Be ready to say the Intaker math out loud: about 23 opportunities a month x 27% closed x about $600 MRR is roughly $3,700 against a $2,000 quota, or about 185%.
- [ ] Confirm the Nuve and Big Bus titles on the resume would hold up in a reference check.
- [ ] Fill in `[Name]` in the hiring-manager messages.

## What's in this folder

| File | What it is |
|---|---|
| `fit-assessment.md` | Whether to apply, the requirements scorecard, risks, backup plan |
| `linkedin-paste-in-checklist.md` | Step-by-step profile update with paste-ready text |
| `linkedin-framework-crosscheck.md` | Claim-by-claim check of the Gemini LinkedIn framework against verified research, with what was adopted, adapted or skipped |
| `linkedin-2026-standards.md` | The 2026 LinkedIn character limits, word targets and formatting rules every LinkedIn draft must meet |
| `send-ready/` | Final resume (`.docx`, `.pdf`, `.md`), cover letter, and outreach messages. No working notes in these |
| `hiring-manager-review.md` | Hiring-manager screen of the drafts, interview questions, submit checklist |
| `performance-benchmarks.md` | Industry benchmarks as interview talk tracks (not resume claims) |
| `resume-servicetitan-sdm.md` | Working resume with Writer's Notes (judgment calls, items to verify) |
| `linkedin-rewrite.md` | Working LinkedIn rewrite with the reasoning behind each choice |
| `cover-letter-and-referral.md` | Working cover letter and outreach kit with notes |
| `source/` | Job description, LinkedIn snapshot (Oct 6), and interview notes |

## Editing LinkedIn copy

Edit the paste blocks in `linkedin-rewrite.md`, then run `python3 tools/build_linkedin_checklist.py`. It checks everything against `linkedin-2026-standards.md`, refreshes the compliance table at the top of the rewrite file, and rebuilds the paste blocks in `linkedin-paste-in-checklist.md`. It exits with an error if a hard limit or format rule is broken.

## Editing the resume

Edit `send-ready/resume.md`, then rebuild the Word and PDF files with `tools/build_resume_docx.js` (usage is at the top of that file), or ask Claude to do it.
