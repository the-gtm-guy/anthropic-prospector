# EE-JOP

Job-search workspace for Johnny Scott Jorgenson. Current target: ServiceTitan, Manager, Sales Development I (`servicetitan-sdm/`).

## LinkedIn copy rule

Any LinkedIn text drafted here must meet `servicetitan-sdm/linkedin-2026-standards.md`. That covers headlines, About sections, experience bullets, post hooks, connection notes, InMail, and any alternative versions of them. The standards set 2026 character and word limits, what shows before "see more", and plain-text formatting.

- Put new or changed copy in `servicetitan-sdm/linkedin-rewrite.md` (messages go in `servicetitan-sdm/send-ready/outreach-messages.md`), then run `python3 tools/build_linkedin_checklist.py`. It must exit 0 with no FAIL rows before the copy is presented.
- When presenting options in chat, show the character and word count for each one.
- Use only facts from `servicetitan-sdm/source/candidate-interview.md` and the resume. Don't invent metrics.
