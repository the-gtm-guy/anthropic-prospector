#!/usr/bin/env python3
"""Check LinkedIn copy against the 2026 standards and rebuild the paste-in checklist.

Usage:
    python3 tools/build_linkedin_checklist.py                       # check, then update the files
    python3 tools/build_linkedin_checklist.py --check               # check only, write nothing
    python3 tools/build_linkedin_checklist.py --dir servicetitan-sdm  # a different application folder

The folder defaults to servicetitan-sdr (the active application).

Reads:   <folder>/linkedin-rewrite.md, <folder>/send-ready/outreach-messages.md
Writes:  the compliance table in linkedin-rewrite.md and the generated regions of
         linkedin-paste-in-checklist.md (between the BEGIN/END comment markers).
Exits 1 if any hard limit or format rule is broken. Rules live in
servicetitan-sdm/linkedin-2026-standards.md (shared by every application folder).
"""
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_DIR = 'servicetitan-sdr'
STANDARDS = 'servicetitan-sdm/linkedin-2026-standards.md'

HYPE = ['passionate', 'results-driven', 'rockstar', 'ninja', 'guru', 'synergy', 'thought leader', 'visionary']
EMOJI = re.compile('[\U0001F300-\U0001FAFF☀-➿⭐✅❌]')
UNICODE_BOLD = re.compile('[\U0001D400-\U0001D7FF]')
NAME_PAD = 'x' * 12  # worst-case first name when counting messages

results = []  # (item, chars, words, rule, status, notes)


def record(item, text, rule, fails, warns, extra=''):
    status = 'FAIL' if fails else ('WARN' if warns else 'OK')
    notes = '; '.join(fails + warns) or extra
    if fails or warns:
        notes = notes + ('; ' + extra if extra else '')
    results.append((item, len(text), len(text.split()), rule, status, notes))


def format_issues(text):
    out = []
    if re.search(r'\*\*|`|^#{1,6} ', text, re.M):
        out.append('markdown characters')
    if EMOJI.search(text):
        out.append('emoji')
    if UNICODE_BOLD.search(text):
        out.append('Unicode bold lettering')
    if re.search(r'\[[^\]]*\]', text):
        out.append('bracketed placeholder')
    if '\n\n\n' in text:
        out.append('more than one blank line in a row')
    return out


# ---------- parsing ----------

def parse_blocks(md, kind):
    pat = re.compile(r'### %s (?P<id>[A-Z])(?P<tag>[^\n]*)\n+```text\n(?P<body>.*?)\n```' % kind, re.S)
    return [(m['id'], m['tag'].strip(), m['body']) for m in pat.finditer(md)]


def parse_roles(md):
    sec = md[md.index('## 3. Experience'):md.index('## 4. Skills')]
    roles = []
    for chunk in re.split(r'\n### ', sec)[1:]:
        heading = chunk.split('\n', 1)[0].strip()
        title = re.search(r'\*\*Title:\*\* `([^`]*)`', chunk)
        desc = re.search(r'```text\n(.*?)\n```', chunk, re.S)
        if not (title and desc):
            continue
        dl = re.search(r'\*\*Dates/Location:\*\* ([^\n]*)', chunk).group(1)
        parts = [p.strip() for p in dl.split('·')]
        roles.append(dict(
            heading=heading,
            title=title.group(1),
            company=re.search(r'\*\*Company:\*\* ([^\n]*)', chunk).group(1).strip(),
            dates=parts[0],
            location=' · '.join(parts[1:]),
            kind=re.search(r'\*\*Role type:\*\* (\w+)', chunk).group(1),
            desc=desc.group(1),
            skills=re.search(r'\*\*Skills to tag:\*\* ([^\n]*)', chunk).group(1).strip(),
            notes=[n[2:-2] for n in re.findall(r'^\*\(.*\)\*$', chunk, re.M)],
        ))
    return roles


# ---------- checks ----------

def check_headline(hid, tag, text):
    fails, warns = [], []
    n = len(text)
    if n > 220:
        fails.append('over 220 by %d' % (n - 220))
    if n < 120:
        warns.append('under 120 characters')
    first60 = text[:60]
    if not re.search(r'sales development|sdr', first60, re.I):
        warns.append("first 60 characters lack 'Sales Development' or 'SDR'")
    if re.search(r'open to work|seeking', text, re.I):
        fails.append("'Open to Work' or 'Seeking' in headline")
    hype = [h for h in HYPE if h in text.lower()]
    if hype:
        warns.append('hype words: ' + ', '.join(hype))
    fails += format_issues(text)
    record('Headline ' + hid, text, '120-220 chars, title in first 60', fails, warns, "shows: '%s'" % first60.rstrip(' |'))


def check_about(aid, tag, text):
    fails, warns = [], []
    recommended = 'recommended' in tag
    n, w = len(text), len(text.split())
    if n > 2600:
        fails.append('over 2,600 by %d' % (n - 2600))
    elif n > 2500:
        warns.append('within 100 of the 2,600 cap')
    lo = 1500 if recommended else 1200
    if n < lo or n > 2200:
        warns.append('outside %s-2,200 characters' % format(lo, ','))
    if w < 200 or w > 350:
        warns.append('outside 200-350 words')
    first200 = text[:200]
    if not re.search(r'\d', first200):
        warns.append('no number in first 200 characters')
    if not re.search(r'sdr|sales development', first200, re.I):
        warns.append("first 200 characters lack 'SDR' or 'Sales Development'")
    for para in text.split('\n\n'):
        lines = para.split('\n')
        has_bullets = any(l.startswith('• ') for l in lines)
        for l in lines:
            if l.startswith('• ') and len(l) > 220:
                warns.append('bullet over 220 characters')
        if not has_bullets and len(para) > 350:
            warns.append('prose paragraph over 350 characters')
    fails += format_issues(text)
    rule = '1,500-2,200 chars, 200-350 words' if recommended else '1,200-2,200 chars, 200-350 words'
    record('About ' + aid, text, rule, fails, warns, 'first 200 chars checked')


def check_role(role):
    fails, warns = [], []
    desc = role['desc']
    n = len(desc)
    words = len(desc.split())
    paras = [p for p in desc.split('\n\n') if p.strip()]
    context = None
    if paras and not paras[0].startswith('• '):
        context = paras[0].strip()
        rest = paras[1:]
    else:
        rest = paras
    body_lines = [l for p in rest for l in p.split('\n') if l.strip()]
    bullets = [l[2:] for l in body_lines if l.startswith('• ')]
    if len(bullets) != len(body_lines):
        fails.append("every line after the context statement must start with '• '")
    if context and '\n' in context:
        fails.append('context statement must be one line')
    if len(role['title']) > 100:
        fails.append('title over 100 characters')
    if n > 2000:
        fails.append('description over 2,000')
    if role['kind'] == 'core':
        rule = 'core: context + 3-5 bullets, <=150 words, 400-1,000 chars'
        if not context:
            warns.append('no context statement')
        if n < 400 or n > 1000:
            warns.append('outside 400-1,000 characters')
        if not 3 <= len(bullets) <= 5:
            warns.append('bullet count outside 3-5')
    else:
        rule = 'supporting: 1-3 bullets, <=150 words, <=600 chars'
        if n > 600:
            warns.append('over 600 characters')
        if not 1 <= len(bullets) <= 3:
            warns.append('bullet count outside 1-3')
    if words > 150:
        warns.append('over 150 words')
    if context and len(context.split()) > 40:
        warns.append('context statement over 40 words')
    longest = max((len(b.split()) for b in bullets), default=0)
    if any(len(b.split()) > 35 or len(b) > 230 for b in bullets):
        warns.append('a bullet is over 35 words or 230 characters')
    if bullets and not re.search(r'\d', bullets[0]):
        warns.append('first bullet has no number')
    with_digits = sum(1 for b in bullets if re.search(r'\d', b))
    if bullets and with_digits * 2 < len(bullets):
        warns.append('fewer than half the bullets have a number')
    fails += format_issues(desc)
    record('Role: ' + role['heading'], desc, rule, fails, warns,
           '%s%d bullets, longest %d words, %d with numbers' % ('context + ' if context else '', len(bullets), longest, with_digits))


GENERIC_SKILLS = {'communication', 'leadership', 'teamwork', 'microsoft word', 'microsoft office', 'microsoft powerpoint',
                  'problem solving', 'time management', 'hard working'}


def parse_list_block(md, heading):
    m = re.search(r'### %s[^\n]*\n```text\n(.*?)\n```' % re.escape(heading), md, re.S)
    return [l.strip() for l in m.group(1).split('\n') if l.strip()] if m else []


def check_skills(skills, delete):
    fails, warns = [], []
    lowered = [x.lower() for x in skills]
    if len(skills) > 100:
        fails.append('over 100 skills')
    if not 25 <= len(skills) <= 30:
        warns.append('%d skills (target 25-30)' % len(skills))
    if len(set(lowered)) != len(lowered):
        fails.append('duplicate skills')
    generic = [x for x in skills if x.lower() in GENERIC_SKILLS]
    if generic:
        warns.append('generic skills: ' + ', '.join(generic))
    clash = [x for x in skills if x.lower() in {d.lower() for d in delete}]
    if clash:
        fails.append('in both keep and delete lists: ' + ', '.join(clash))
    record('Skills list', '\n'.join(skills), '25-30 skills, no generic traits', fails, warns, '%d skills; first three: %s' % (len(skills), ', '.join(skills[:3])))


def check_posts(md):
    for i, hook in enumerate(re.findall(r'Hook: \*"(.+?)"\*', md), 1):
        warns = []
        if len(hook) > 140:
            warns.append('hook over 140 characters')
        record('Post %d hook' % i, hook, 'hook <=140 chars', [], warns)


def check_outreach(md):
    for m in re.finditer(r'### ([^\n]*connection note[^\n]*)\n\n> ([^\n]*)', md):
        limit = 200 if '200' in m.group(1) else 300
        text = m.group(2).replace('[Name]', NAME_PAD)
        fails = ['over %d by %d' % (limit, len(text) - limit)] if len(text) > limit else []
        record('Connection note (%d)' % limit, text, '<=%d chars with a 12-char name' % limit, fails, [])
    m = re.search(r'### Follow-up InMail\n(.*?)\n---', md, re.S)
    if m:
        quoted = [l[2:] if l.startswith('> ') else l[1:] for l in m.group(1).split('\n') if l.startswith('>')]
        subject = next((re.sub(r'\*\*Subject:\*\* ?', '', l) for l in quoted if 'Subject:' in l), '')
        body = '\n'.join(quoted[quoted.index(next(l for l in quoted if 'Subject:' in l)) + 1:]).strip().replace('[Name]', NAME_PAD)
        fails, warns = [], []
        if len(subject) > 200:
            fails.append('subject over 200')
        if len(body) > 1900:
            fails.append('body over 1,900')
        elif len(body) > 1000:
            warns.append('body over 1,000 (style target)')
        record('InMail body', body, 'body <=1,000 chars (limit 1,900)', fails, warns)


# ---------- output ----------

def compliance_table():
    rows = ['| Item | Characters | Words | Rule | Status | Notes |', '|---|---|---|---|---|---|']
    for item, c, w, rule, status, notes in results:
        rows.append('| %s | %s | %s | %s | %s | %s |' % (item, format(c, ','), w, rule, status, notes.replace('|', '\\|')))
    counts = {s: sum(1 for r in results if r[4] == s) for s in ('OK', 'WARN', 'FAIL')}
    summary = '%d checks: %d OK, %d WARN, %d FAIL. Rules: `%s`. Rerun `python3 tools/build_linkedin_checklist.py` after any edit.' % (
        len(results), counts['OK'], counts['WARN'], counts['FAIL'], STANDARDS)
    return summary + '\n\n' + '\n'.join(rows)


def fence(t):
    return '```text\n' + t + '\n```'


def headline_region(headlines):
    out = ["- [ ] **Headline.** Paste option A. B and C are alternatives if you want a different angle. Only the first ~60 characters show in search and comments, so each one opens with the job title and the top keyword.", '']
    for hid, tag, text in headlines:
        out.append('**Option %s %s** · %d of 220 characters, %d words. Shows in search and comments: "%s"' % (
            hid, tag, len(text), len(text.split()), text[:60].rstrip(' |')))
        out += [fence(text), '']
    return '\n'.join(out).rstrip()


def about_region(abouts):
    out = ['Open the About section with its pencil icon, select everything, and paste **About A**. About B is a shorter alternative if you would rather lead with metrics.', '']
    for aid, tag, text in abouts:
        out.append('**About %s %s** · %s of 2,600 characters, %d words. A phone shows roughly the first 200 characters before "see more":' % (
            aid, tag, format(len(text), ','), len(text.split())))
        out += ['> ' + text[:200].replace('\n', ' ') + '...', '', fence(text), '']
    return '\n'.join(out).rstrip()


def roles_region(roles):
    out = []
    for r in roles:
        out += ['### ' + r['heading'], '',
                '- [ ] **Title** (replace the current one):', fence(r['title']),
                '- [ ] **Dates:** %s. **Location:** %s. (Leave these as they are if they already match.)' % (r['dates'], r['location']),
                '- [ ] **Description** (replace everything in the box; %d characters, %d words):' % (len(r['desc']), len(r['desc'].split())), fence(r['desc']),
                '- [ ] **Skills to tag:** ' + r['skills']]
        out += ['- [ ] **Note:** ' + n for n in r['notes']]
        out.append('')
    return '\n'.join(out).rstrip()


def skills_region(skills, delete):
    out = ["- [ ] **Make your Skills list match this list** (%d skills). Add the ones you're missing and delete everything that isn't on it. LinkedIn allows 100, but a focused list ranks better in recruiters' skill-based search. Put them in this order and pin the first five. If your account only pins three, the first three are the ones that matter most." % len(skills),
           '', fence('\n'.join(skills)), '',
           "- [ ] **Delete these.** They signal an engineering profile, or they're phrases recruiters don't search for: " + '; '.join(delete) + '.']
    return '\n'.join(out)


def replace_region(text, name, content):
    pat = re.compile(r'<!-- BEGIN:%s -->.*?<!-- END:%s -->' % (name, name), re.S)
    if not pat.search(text):
        raise SystemExit('missing markers for region: ' + name)
    return pat.sub(lambda _: '<!-- BEGIN:%s -->\n%s\n<!-- END:%s -->' % (name, content, name), text)


def main():
    args = sys.argv[1:]
    check_only = '--check' in args
    folder = DEFAULT_DIR
    if '--dir' in args:
        i = args.index('--dir')
        if i + 1 >= len(args):
            raise SystemExit('--dir needs a folder name')
        folder = args[i + 1]
    root = REPO / folder
    if not root.is_dir():
        raise SystemExit('no such folder: %s' % root)
    rewrite_path = root / 'linkedin-rewrite.md'
    checklist_path = root / 'linkedin-paste-in-checklist.md'
    outreach_path = root / 'send-ready' / 'outreach-messages.md'
    print('folder: %s' % folder)
    rewrite = rewrite_path.read_text()
    headlines = parse_blocks(rewrite, 'Headline')
    abouts = parse_blocks(rewrite, 'About')
    roles = parse_roles(rewrite)
    if not (headlines and abouts and roles):
        raise SystemExit('could not parse headlines, abouts or roles from linkedin-rewrite.md')
    for h in headlines:
        check_headline(*h)
    for a in abouts:
        check_about(*a)
    for r in roles:
        check_role(r)
    skills = parse_list_block(rewrite, 'Final skills list')
    delete = parse_list_block(rewrite, 'Delete these')
    if not skills:
        raise SystemExit('could not parse the final skills list from linkedin-rewrite.md')
    check_skills(skills, delete)
    check_posts(rewrite)
    if outreach_path.exists():
        check_outreach(outreach_path.read_text())

    for item, c, w, rule, status, notes in results:
        print('%-4s %-34s %5d chars %4d words  %s' % (status, item, c, w, notes))
    failed = any(r[4] == 'FAIL' for r in results)

    if not check_only:
        rewrite_path.write_text(replace_region(rewrite, 'compliance', compliance_table()))
        cl = checklist_path.read_text()
        cl = replace_region(cl, 'headline', headline_region(headlines))
        cl = replace_region(cl, 'about', about_region(abouts))
        cl = replace_region(cl, 'roles', roles_region(roles))
        cl = replace_region(cl, 'skills', skills_region(skills, delete))
        checklist_path.write_text(cl)
        print('updated %s/linkedin-rewrite.md and %s/linkedin-paste-in-checklist.md' % (folder, folder))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
