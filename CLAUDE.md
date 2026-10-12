# EE-JOP

Job-search workspace for Johnny Scott Jorgenson. Current target: ServiceTitan, Sales Development Representative, JR115835 (`servicetitan-sdr/`). The earlier Manager, Sales Development I application (`servicetitan-sdm/`) closed and is kept for reference.

## LinkedIn copy rule

Any LinkedIn text drafted here must meet `servicetitan-sdm/linkedin-2026-standards.md` (shared by every application folder). That covers headlines, About sections, experience bullets, post hooks, connection notes, InMail, and any alternative versions of them. The standards set 2026 character and word limits, what shows before "see more", and plain-text formatting.

- Put new or changed copy in `servicetitan-sdr/linkedin-rewrite.md` (messages go in `servicetitan-sdr/send-ready/outreach-messages.md`), then run `python3 tools/build_linkedin_checklist.py` (add `--dir <folder>` for another application folder). It must exit 0 with no FAIL rows before the copy is presented.
- When presenting options in chat, show the character and word count for each one.
- Use only facts from `servicetitan-sdm/source/candidate-interview.md`, `servicetitan-sdr/source/candidate-interview-addendum.md` and the resume. Don't invent metrics.

## Resume rule

The SDR resume (`servicetitan-sdr/send-ready/resume.md`) must stay on one page. After any edit, rebuild it with `node tools/build_resume_docx.js <resume.md> <resume.docx>`, convert to PDF, and confirm `pdfinfo` reports 1 page with a few lines to spare. Don't claim Gong (not used). Salesloft is a 3-week pilot only.
