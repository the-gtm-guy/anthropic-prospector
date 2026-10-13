# ServiceTitan: Sales Development Representative (JR115835)

Posting: https://servicetitan.wd1.myworkdayjobs.com/ServiceTitan/job/US-Remote/Sales-Development-Representative_JR115835-3 (if that link doesn't open, use the Apply link on the posting). Locations: US Remote, Glendale CA, Chicago IL, Salt Lake City UT, St. Louis MO and one more. Within 40 miles of an office you work onsite 1-2 days a week. Pay in California: $28.85 an hour (about $60K) plus commission, equity and benefits.

This replaces the closed manager application (`../servicetitan-sdm/`, JR116181). That folder is kept for reference.

## Do these in order

1. **LinkedIn, Part 1 (about 30 minutes):** `linkedin-paste-in-checklist.md`. Do the name, headline, About, Intaker and Nuve, and Open to Work. Recruiters check your profile within a day of seeing your resume.
2. **Apply and text Arman at the same time.** This is what Arman asked for so he can short stack you.
   - Open the posting and click Apply. Use **jorgenllc@gmail.com** (the email on your resume).
   - Upload `send-ready/Johnny_Scott_Jorgenson_Resume.pdf`. The `.docx` next to it is the editable copy. If the form has an optional cover letter box, paste `send-ready/cover-letter.md`. If it asks for a location preference, pick Glendale, CA.
   - **The moment you click Submit,** send Arman the text in `send-ready/outreach-messages.md` (section 1) with the PDF attached.
3. **LinkedIn, Part 2 (about an hour, within a day or two):** the rest of the checklist.
4. **Message an SDR leader** with the notes in `send-ready/outreach-messages.md` (section 3), after you've applied.
5. **Prep for interviews:** `fit-and-interview-prep.md`.

## Before you submit

- [ ] **Read the "from your profile" list** in `source/candidate-interview-addendum.md`. Those figures are your own Oct 6 claims that you never re-confirmed in our chats (the Nuve $842.4K and 162%, the trade show, all the CROP and Big Bus numbers, the dates). Tell me about any that are off and I'll fix the resume and LinkedIn in one pass.
- [ ] **Check the "about 185%" at Intaker** against your Intaker numbers if you can see them. It comes from about 23 opportunities x 27% closed x about $600 MRR, which is roughly $3,700 against a $2,000 quota. If your real attainment is lower, tell me and I'll change it everywhere.
- [ ] **CROP:** confirm that "PDR" stands for Partnership Development Representative and that CROP's records show a Mar 2024 start. Two recommendations call you an "SDR fellow" there, so use the titles and dates CROP would confirm.
- [ ] **Education:** replace "B.S., Business" and "A.A., Business Administration" with the exact degrees and majors on your diplomas.
- [ ] Open the PDF on your phone. It should be one page and read cleanly.
- [ ] The resume leaves off the two HubSpot certifications, which expire this month. Renew them and tell me to add them back, or remove them from LinkedIn.
- [ ] Use the same email address on the application, the resume and the referral.
- [ ] Fill in `[Name]` in the SDR-leader messages.
- [ ] Write your own answers to "Why an SDR role?" and "Why leave Intaker after about six months?" (`fit-and-interview-prep.md`, Risks 1 and 2).

## What's in this folder

| File | What it is |
|---|---|
| `send-ready/` | The files you send: resume (`.pdf`, `.docx`, `.md`), cover letter, and outreach messages. No working notes in these |
| `linkedin-paste-in-checklist.md` | Step-by-step profile update with plain-text paste blocks, split into "before you apply" and "after" |
| `linkedin-rewrite.md` | The LinkedIn copy (headline, About, roles, skills, posts) with an auto-generated compliance table |
| `fit-and-interview-prep.md` | Fit scorecard, risks, the numbers and math to say out loud, likely questions, questions to ask |
| `source/` | The job description and the interview notes for this application (the earlier notes are in `../servicetitan-sdm/source/`) |

The 2026 LinkedIn limits and formatting rules every LinkedIn draft must meet are in `../servicetitan-sdm/linkedin-2026-standards.md`.

## What changed from the manager package

- **Resume:** one page, production first (162% and $842.4K, about 185%, 30-35 demos a month). Coaching and enablement are one line each. State of California and GOCO are compressed. Tools include Salesforce Sales Cloud, Chili Piper, Nooks, Orum, ZoomInfo, Clay, Fireflies, n8n and Zapier. The header says open to hybrid in Glendale. Contract roles are labeled "Contract". Gong is not claimed, and Salesloft is listed as a 3-week pilot.
- **LinkedIn:** the headline and About are SDR-first, the skills list leads with prospecting and outbound (leadership skills moved down), and Open to Work targets SDR, BDR, Inside Sales and Account Executive titles.
- **Provenance:** the interview answers you gave are the firmest facts. Many other figures come from your own Oct 6 LinkedIn profile and weren't re-confirmed in chat. `source/candidate-interview-addendum.md` lists which is which. I left the +20% team-output lift (60 demos, $126K a month) and "built the first enablement program" out of the SDR copy, because an SDR role doesn't need them and they're the claims a former Nuve leader would most likely dispute. If you can back them with data, tell me and I'll put them back.

## Editing

- **Resume:** edit `send-ready/resume.md`, then rebuild the Word file with `node tools/build_resume_docx.js servicetitan-sdr/send-ready/resume.md servicetitan-sdr/send-ready/Johnny_Scott_Jorgenson_Resume.docx` (and convert to PDF), or ask Claude to do it. It has to stay on one page.
- **LinkedIn copy:** edit `linkedin-rewrite.md`, then run `python3 tools/build_linkedin_checklist.py`. It checks everything against the standards, refreshes the compliance table, and rebuilds the paste blocks in the checklist. It exits with an error if a hard limit or format rule is broken.
