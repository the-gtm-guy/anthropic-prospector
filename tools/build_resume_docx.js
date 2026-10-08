// Builds an ATS-friendly resume .docx from a simple markdown resume (see servicetitan-sdm/send-ready/resume.md for the format).
// Setup:  npm install docx
// Usage:  node tools/build_resume_docx.js <input.md> <output.docx> [bodyHalfPoints=20]
// PDF:    soffice --headless --convert-to pdf --outdir <dir> <output.docx>   (LibreOffice)
// Layout is tuned for 2 US Letter pages at 10pt Calibri. If it spills to a third page, trim content or lower the margins.
const {
  Document, Packer, Paragraph, TextRun, AlignmentType, LevelFormat, BorderStyle, HeadingLevel,
} = require('docx');

const SRC = process.argv[2];
const OUT = process.argv[3];
const BODY = parseInt(process.argv[4] || '20', 10); // half-points (20 = 10pt)
const FONT = 'Calibri';
const NAVY = '1F3A5F';
const INK = '1A1A1A';
const GRAY = '4A4A4A';

const lines = fs.readFileSync(SRC, 'utf8').split('\n');

const children = [];
let section = null;
let expectMeta = false;
const headerLines = [];
let nameText = '';

function run(text, opts = {}) {
  return new TextRun({ text, font: FONT, size: BODY, color: INK, ...opts });
}

function flushHeader() {
  // name, contact line, target-title line
  children.push(new Paragraph({
    heading: HeadingLevel.HEADING_1,
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: nameText, font: FONT, size: BODY + 20, bold: true, color: NAVY })],
  }));
  if (headerLines[0]) {
    children.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 20 },
      children: [run(headerLines[0], { size: BODY })],
    }));
  }
  if (headerLines[1]) {
    children.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 40 },
      children: [run(headerLines[1], { bold: true, color: NAVY, size: BODY + 2 })],
    }));
  }
}

let headerFlushed = false;

for (const raw of lines) {
  const line = raw.replace(/\s+$/, '');
  if (!line.trim()) continue;

  if (line.startsWith('# ')) {
    nameText = line.slice(2).trim();
    continue;
  }
  if (line.startsWith('## ')) {
    if (!headerFlushed) { flushHeader(); headerFlushed = true; }
    section = line.slice(3).trim();
    expectMeta = false;
    children.push(new Paragraph({
      heading: HeadingLevel.HEADING_2,
      keepNext: true,
      children: [new TextRun({ text: section, font: FONT, size: BODY + 2, bold: true, allCaps: true, color: NAVY })],
    }));
    continue;
  }
  if (line.startsWith('### ')) {
    children.push(new Paragraph({
      heading: HeadingLevel.HEADING_3,
      keepNext: true,
      children: [new TextRun({ text: line.slice(4).trim(), font: FONT, size: BODY + 1, bold: true, color: INK })],
    }));
    expectMeta = true;
    continue;
  }
  if (line.startsWith('- ')) {
    children.push(new Paragraph({
      numbering: { reference: 'bullets', level: 0 },
      spacing: { after: 16 },
      children: [run(line.slice(2).trim())],
    }));
    continue;
  }
  // plain line
  if (!headerFlushed) { headerLines.push(line.trim()); continue; }
  if (expectMeta) {
    children.push(new Paragraph({
      keepNext: true,
      spacing: { after: 30 },
      children: [run(line.trim(), { italics: true, color: GRAY, size: BODY - 1 })],
    }));
    expectMeta = false;
    continue;
  }
  if (section === 'Tools & Technology') {
    const idx = line.indexOf(':');
    const label = line.slice(0, idx + 1);
    const rest = line.slice(idx + 1);
    children.push(new Paragraph({
      spacing: { after: 20 },
      children: [run(label, { bold: true }), run(rest)],
    }));
    continue;
  }
  children.push(new Paragraph({
    spacing: { after: section === 'Education' || section === 'Certifications' ? 10 : 50 },
    children: [run(line.trim())],
  }));
}
if (!headerFlushed) flushHeader();

const doc = new Document({
  creator: nameText,
  title: `${nameText} - Resume`,
  description: 'Resume',
  styles: {
    default: { document: { run: { font: FONT, size: BODY, color: INK } } },
    paragraphStyles: [
      {
        id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: FONT, size: BODY + 20, bold: true, color: NAVY },
        paragraph: { spacing: { before: 0, after: 20 }, alignment: AlignmentType.CENTER, outlineLevel: 0 },
      },
      {
        id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: FONT, size: BODY + 2, bold: true, allCaps: true, color: NAVY },
        paragraph: {
          spacing: { before: 100, after: 40 }, outlineLevel: 1,
          border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: NAVY, space: 1 } },
        },
      },
      {
        id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: FONT, size: BODY + 1, bold: true, color: INK },
        paragraph: { spacing: { before: 70, after: 0 }, outlineLevel: 2 },
      },
    ],
  },
  numbering: {
    config: [{
      reference: 'bullets',
      levels: [{
        level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 340, hanging: 200 } } },
      }],
    }],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 600, bottom: 560, left: 860, right: 860 },
      },
    },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log('wrote', OUT, buf.length, 'bytes');
});
