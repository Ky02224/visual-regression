const pptxgen = require('pptxgenjs');
const path = require('path');

const A = '/sessions/beautiful-determined-bell/mnt/outputs/assets';
const W = 23.39, H = 33.11;

// palette
const NAVY = '10294A', NAVY2 = '2E5C8A', ORANGE = 'FD6925';
const BG = 'F1F4F8', PANEL = 'FFFFFF', BORDER = 'D8DFE8';
const TXT = '1E2A38', MUTED = '46586E', ICE = 'A9C6E8';

const BODY_FT = 18, BUL_FT = 18, CAP_FT = 15, HEAD_FT = 28;

const pres = new pptxgen();
pres.defineLayout({ name: 'A1P', width: W, height: H });
pres.layout = 'A1P';
const s = pres.addSlide();
s.background = { color: BG };

// ---------------------------------------------------------------- estimator
function lines(text, ft, wIn) {
  const cpl = Math.max(8, Math.floor(wIn / (0.00685 * ft)));
  let n = 0;
  for (const para of String(text).split('\n')) n += Math.max(1, Math.ceil(para.length / cpl));
  return n;
}
function textH(text, ft, wIn) { return lines(text, ft, wIn) * ft * 1.30 / 72; }

// ---------------------------------------------------------------- header
const HDR_H = 4.42;
s.addShape(pres.ShapeType.rect, { x: 0, y: 0, w: W, h: HDR_H, fill: { color: NAVY } });
s.addImage({ path: `${A}/UOWMalaysiaLogo2022-05.png`, x: 0.78, y: 0.52, w: 5.6, h: 5.6 * 459 / 2084 });

const tiles = ['sdg09', 'sdg04', 'sdg10'];
tiles.forEach((t, i) => {
  s.addImage({ path: `${A}/${t}.png`, x: 18.36 + i * 1.44, y: 0.42, w: 1.32, h: 1.32 });
});

s.addText('AI-Based Visual Regression Testing for Web Applications', {
  x: 0.75, y: 1.86, w: W - 1.5, h: 1.18, align: 'center', fontFace: 'Cambria',
  fontSize: 52, bold: true, color: 'FFFFFF', margin: 0
});
s.addText('Detecting and classifying unintended UI changes across browsers, devices and locales', {
  x: 0.75, y: 3.02, w: W - 1.5, h: 0.55, align: 'center', fontFace: 'Calibri',
  fontSize: 27, color: ICE, italic: true, margin: 0
});
s.addText('Tan Kia Yen   ·   0207077   ·   Final Year Project, Bachelor of Computer Science   ·   Supervisor: Dr. Nor Rahayu Binti Ngatirin   ·   UOW Malaysia', {
  x: 0.75, y: 3.62, w: W - 1.5, h: 0.5, align: 'center', fontFace: 'Calibri',
  fontSize: 21, color: 'D6E3F2', margin: 0
});

// ---------------------------------------------------------------- geometry
const M = 0.75, GAP = 0.42;
const COLW = (W - 2 * M - 2 * GAP) / 3;
const COLX = [M, M + COLW + GAP, M + 2 * (COLW + GAP)];
const BODY_TOP = HDR_H + 0.42;
const FOOT_H = 1.22;
const BODY_BOT = H - FOOT_H - 0.34;
const BODY_H = BODY_BOT - BODY_TOP;

const PADX = 0.40, PADT = 0.30, PADB = 0.34, HEADH = 0.80, BLOCKGAP = 0.18;
const INNERW = COLW - 2 * PADX;

// ---------------------------------------------------------------- blocks
const P = (t, o = {}) => ({ k: 'p', t, ...o });
const UL = (items, o = {}) => ({ k: 'ul', items, ...o });
const IMG = (f, aspect, o = {}) => ({ k: 'img', f, aspect, ...o });
const STATS = (cards) => ({ k: 'stats', cards });
const SDG = (icon, title, body) => ({ k: 'sdg', icon, title, body });

const IMGW = INNERW * 0.95;
const STATH = 1.46;

function blockH(b, f = 1) {
  switch (b.k) {
    case 'p': return textH(b.t, (b.ft || BODY_FT) * f, INNERW) + (b.extra || 0);
    case 'ul': {
      const ft = (b.ft || BUL_FT) * f;
      let h = 0;
      for (const it of b.items) h += textH(it, ft, INNERW - 0.34) + 0.10;
      return h;
    }
    case 'img': return IMGW * b.aspect;
    case 'stats': return STATH;
    case 'sdg': return Math.max(1.56, textH(b.body, 17.5 * f, INNERW - 1.72) + 0.60 * f + 0.10);
  }
}
function panelH(p, f = 1) {
  let h = PADT + HEADH + PADB;
  p.blocks.forEach((b, i) => { h += blockH(b, f) + (i ? BLOCKGAP : 0); });
  return h;
}
function colTotal(col, f) { return col.reduce((a, p) => a + panelH(p, f), 0); }
function fitScale(col) {
  const need = BODY_H - 0.32 * (col.length - 1);
  let lo = 0.80, hi = 1.0;
  if (colTotal(col, hi) <= need) return hi;
  for (let i = 0; i < 30; i++) {
    const mid = (lo + hi) / 2;
    if (colTotal(col, mid) <= need) lo = mid; else hi = mid;
  }
  return lo;
}

// ---------------------------------------------------------------- content
const col1 = [
  {
    n: 1, title: 'Introduction & Aims', blocks: [
      P('A visual regression is a change to a web page that nobody meant to make: a button that vanishes after a CSS refactor, text that overflows only in Malay, a chart that renders blank on a phone. The functional tests still pass — the page is broken anyway.'),
      P('Visual Regression Workbench captures a page, compares it against an approved reference image, and classifies what changed, so a reviewer only opens the changes worth opening.'),
      P('Aims', { bold: true }),
      UL([
        'Detect unintended UI changes across browsers, devices and locales, automatically.',
        'Name the kind of change instead of only flagging pixels, so triage is not guesswork.',
        'Ship it as free, self-hosted software any team, student or NGO can run on a laptop.'
      ])
    ]
  },
  {
    n: 2, title: 'Problem Statement', blocks: [
      UL([
        'Manual checking does not scale. 3 pages × 3 locales × 3 devices is 27 screens to inspect by eye every release. It gets skipped.',
        'Pixel-only tools cry wolf. Anti-aliasing, font hinting and animation produce diffs that mean nothing. Reviewers stop looking, then switch the check off.',
        'Commercial platforms are out of reach. Percy, Applitools and Chromatic charge per snapshot and upload screenshots to a third-party cloud — a blocker for student teams, small companies, and anyone with data-residency rules.',
        'The layouts that break most are tested least. Non-English text and small viewports are where truncation, overlap and clipping appear first.'
      ])
    ]
  },
  {
    n: 3, title: 'Target Users', blocks: [
      UL([
        'QA engineers and frontend developers in small and medium teams.',
        'Release owners who approve or block a deployment.',
        'University project teams with no QA budget and no licence.',
        'Public-sector and NGO web teams serving multilingual audiences who cannot send screenshots off-site.'
      ])
    ]
  },
  {
    n: 4, title: 'App Features', blocks: [
      UL([
        'Dashboard for runs, baselines, reports and approvals, with live updates.',
        'Baseline versioning — old versions archived, rollback in one click.',
        'Locale, timezone and device-aware capture (en-US, ms-MY, zh-CN; desktop and phone).',
        'A DOM sidecar rides with every screenshot, giving structural comparison rather than pixel arithmetic.',
        'AI change classification: missing element, layout shift, text issue, colour regression, broken image.',
        'Playwright SDK drop-in — one line: visualSnapshot(page, "homepage").',
        'Role-based access control: admin / developer / viewer.',
        'HTML report, JSON, JUnit output and GitHub commit-status checks.',
        'SQLite by default or PostgreSQL; deployed with docker-compose up.'
      ])
    ]
  }
];

const col2 = [
  {
    n: 5, title: 'Methodology', blocks: [
      P('Python + FastAPI, Playwright capture, PyTorch (ResNet50 Siamese) with OpenCV/SSIM, a React dashboard, SQLite or PostgreSQL. Every component is open source.'),
      P('Evaluation — measured, not asserted', { bold: true }),
      UL([
        'Detection: baselines captured from the clean demo pages, then every page reloaded with ?defect=<mode> — 9 defect types × 9 cases = 81 defective plus 9 clean controls. Ground truth comes from the injected mode, never from the model.',
        'Classification: 500 trials over 10 random seeds on real third-party pages with injected DOM mutations, with a 95% confidence interval.',
        'Every number here is re-checked by CI on each push; the build fails on any miss or false alarm.'
      ])
    ]
  },
  { n: 6, title: 'System Architecture & Workflow', blocks: [IMG('architecture.png', 0.81)] },
  {
    n: 7, title: 'Findings & Results', blocks: [
      STATS([['81/81', 'defects detected'], ['0/9', 'false alarms'], ['95.00%', 'classification'], ['1,044', 'tests passing']]),
      P('100% recall on all nine injected defect types — missing CTA, shifted card, theme shift, text truncation, overlay obstruction, broken image, misaligned fields, unreadable text, z-index issue.', { ft: CAP_FT }),
      IMG('charts.png', 677 / 1263),
      IMG('triptych.png', 858 / 1320),
      P('Above: the metrics row was removed. Pixel diff 6.14% over one 1392 × 343 px region; labelled missing-element at 0.97 confidence; severity high; run fails.', { ft: CAP_FT }),
      P('Honestly reported: 15 of the 25 residual errors fall between label pairs describing one event from two angles — a removal reflows what sits below it, an overflow is also a layout change. Treating those as interchangeable scores 98.00%; the strict 95.00% stays the headline.', { ft: CAP_FT })
    ]
  }
];

const col3 = [
  {
    n: 8, title: 'SDG Alignment', blocks: [
      SDG('sdg09', 'SDG 9 — Industry, Innovation and Infrastructure  (primary)',
        'Web interfaces are how people now reach banking, healthcare, enrolment and government services; a broken interface is an outage for the person who cannot finish the task. Targets 9.1 and 9.5 — this puts measured, automated release quality within reach of teams that cannot buy it.'),
      SDG('sdg04', 'SDG 4 — Quality Education',
        'Free, self-hosted, and documented with decision records that explain why each choice was made. Target 4.4 — students practise industry release engineering on real tooling instead of reading about it.'),
      SDG('sdg10', 'SDG 10 — Reduced Inequalities',
        'Capture is locale, timezone and device aware, and was evaluated in English, Malay and Chinese on desktop and phone — so layouts used by non-English speakers and low-end devices get the same scrutiny as the English desktop view.')
    ]
  },
  {
    n: 9, title: 'Impact, Benefit & Feasibility', blocks: [
      UL([
        'Review effort collapses. Across 90 benchmark screens the reviewer opens only what is flagged, and 0 false alarms means no wasted triage.',
        'It catches what functional tests miss — all nine defect types, including ones that raise no console error and break no assertion.',
        'Zero licence cost, and no data leaves the organisation: screenshots stay on the team\'s own machine or server.',
        'Realistic to run. CPU-only inference, no GPU; SQLite on a laptop, PostgreSQL when a team needs it; docker-compose up is the whole deployment.',
        'It degrades safely. With no model present it falls back to pixel comparison and keeps detecting, so adoption never waits on training a model.',
        'Replicable anywhere — every component is open source, so any institution can stand up its own instance at no cost.'
      ])
    ]
  },
  {
    n: 10, title: 'Conclusion & Recommendations', blocks: [
      P('Detection is effectively solved on this benchmark — 81 of 81 defects caught, no false alarms — and classification stands at 95.00% with a stated confidence interval. The two are reported separately on purpose: they fail for different reasons, and one combined figure would hide which half is weak.'),
      P('Recommendations & next work', { bold: true }),
      UL([
        'Close the 10 residual errors outside the overlapping label pairs and refine the change taxonomy.',
        'Extend the benchmark from the demo portal to production sites at scale.',
        'Add accessibility checks — contrast ratio, focus order — alongside the visual diff.',
        'Offer a shared community instance so student teams get visual QA with no setup at all.'
      ])
    ]
  }
];

// ---------------------------------------------------------------- draw
function drawPanel(p, x, y, w, f) {
  const h = p.h;
  s.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.10,
    fill: { color: PANEL }, line: { color: BORDER, width: 1 },
    shadow: { type: 'outer', color: '8FA0B5', blur: 9, offset: 2, angle: 90, opacity: 0.28 }
  });
  // number chip + header
  const hasChip = p.n !== '';
  if (hasChip) {
    s.addShape(pres.ShapeType.roundRect, {
      x: x + PADX, y: y + PADT, w: 0.66, h: 0.66, rectRadius: 0.16,
      fill: { color: NAVY }, line: { color: NAVY, width: 0 }
    });
    s.addText(String(p.n), {
      x: x + PADX, y: y + PADT, w: 0.66, h: 0.66, align: 'center', valign: 'middle',
      fontFace: 'Calibri', fontSize: 24, bold: true, color: 'FFFFFF', margin: 0
    });
  }
  s.addText(p.title, {
    x: x + PADX + (hasChip ? 0.88 : 0), y: y + PADT - 0.04,
    w: w - 2 * PADX - (hasChip ? 0.88 : 0), h: 0.74, valign: 'middle',
    fontFace: 'Calibri', fontSize: hasChip ? HEAD_FT : HEAD_FT - 4, bold: true, color: NAVY, margin: 0
  });

  let cy = y + PADT + HEADH;
  const ix = x + PADX;
  const imx = ix + (INNERW - IMGW) / 2;
  p.blocks.forEach((b, i) => {
    if (i) cy += BLOCKGAP;
    const bh = blockH(b, f);
    if (b.k === 'p') {
      const ft = (b.ft || BODY_FT) * f;
      s.addText(b.t, {
        x: ix, y: cy, w: INNERW, h: bh, valign: 'top', margin: 0,
        fontFace: 'Calibri', fontSize: ft, bold: !!b.bold,
        color: b.ft ? MUTED : TXT, lineSpacingMultiple: 1.05, align: 'left'
      });
    } else if (b.k === 'ul') {
      const ft = (b.ft || BUL_FT) * f;
      const items = b.items.map((t, j) => ({
        text: t,
        options: { bullet: { code: '25AA' }, breakLine: j < b.items.length - 1, paraSpaceAfter: 6 }
      }));
      s.addText(items, {
        x: ix, y: cy, w: INNERW, h: bh, valign: 'top', margin: 0, indentLevel: 0,
        fontFace: 'Calibri', fontSize: ft, color: b.ft ? MUTED : TXT, lineSpacingMultiple: 1.05
      });
    } else if (b.k === 'img') {
      s.addImage({ path: `${A}/${b.f}`, x: imx, y: cy, w: IMGW, h: bh });
    } else if (b.k === 'stats') {
      const n = b.cards.length, g = 0.15;
      const cw = (INNERW - (n - 1) * g) / n;
      b.cards.forEach((c, j) => {
        const cx = ix + j * (cw + g);
        s.addShape(pres.ShapeType.roundRect, {
          x: cx, y: cy, w: cw, h: STATH, rectRadius: 0.10,
          fill: { color: NAVY }, line: { color: NAVY, width: 0 }
        });
        s.addText(c[0], {
          x: cx, y: cy + 0.12, w: cw, h: 0.72, align: 'center', valign: 'middle', margin: 0,
          fontFace: 'Calibri', fontSize: 32, bold: true, color: ORANGE
        });
        s.addText(c[1], {
          x: cx, y: cy + 0.84, w: cw, h: 0.46, align: 'center', valign: 'top', margin: 0,
          fontFace: 'Calibri', fontSize: 14.5, color: 'D6E3F2'
        });
      });
    } else if (b.k === 'sdg') {
      s.addImage({ path: `${A}/${b.icon}.png`, x: ix, y: cy, w: 1.5, h: 1.5 });
      s.addText(b.title, {
        x: ix + 1.72, y: cy - 0.05, w: INNERW - 1.72, h: 0.60 * f, valign: 'top', margin: 0,
        fontFace: 'Calibri', fontSize: 19 * f, bold: true, color: NAVY, lineSpacingMultiple: 1.0
      });
      s.addText(b.body, {
        x: ix + 1.72, y: cy + 0.58 * f, w: INNERW - 1.72, h: bh - 0.58 * f, valign: 'top', margin: 0,
        fontFace: 'Calibri', fontSize: 17.5 * f, color: TXT, lineSpacingMultiple: 1.04
      });
    }
    cy += bh;
  });
}

const GF = Math.min(...[col1, col2, col3].map(fitScale));
[col1, col2, col3].forEach((col, ci) => {
  const f = GF;
  col.forEach(p => { p.h = panelH(p, f); });
  const total = col.reduce((a, p) => a + p.h, 0);
  let gap = (BODY_H - total) / Math.max(1, col.length - 1);
  console.log(`col${ci + 1}: scale ${f.toFixed(3)} → body ${(BODY_FT * f).toFixed(1)}pt, content ${total.toFixed(2)}in / ${BODY_H.toFixed(2)}in, gap ${gap.toFixed(2)}in`);
  if (gap > 0.80) gap = 0.80;
  let y = BODY_TOP;
  col.forEach(p => { drawPanel(p, COLX[ci], y, COLW, f); y += p.h + gap; });
});

// ---------------------------------------------------------------- footer
s.addShape(pres.ShapeType.rect, { x: 0, y: H - FOOT_H, w: W, h: FOOT_H, fill: { color: NAVY } });
s.addText([
  { text: 'References  ·  United Nations (2015) Transforming our world: the 2030 Agenda for Sustainable Development, A/RES/70/1.  ·  He, K. et al. (2016) Deep Residual Learning for Image Recognition, CVPR.  ·  Wang, Z. et al. (2004) Image Quality Assessment: From Error Visibility to Structural Similarity, IEEE TIP.  ·  Deka, B. et al. (2017) Rico: A Mobile App Dataset for Building Data-Driven Design Applications, UIST.', options: { breakLine: true } },
  { text: 'Built with Playwright, FastAPI, PyTorch, OpenCV and React, all open source.   ·   Contact: Tan Kia Yen, kiayentan6@gmail.com', options: { breakLine: true } },
  { text: 'SDG icons based on the United Nations Sustainable Development Goals (un.org/sustainabledevelopment). The content of this publication has not been approved by the United Nations and does not reflect the views of the United Nations or its officials or Member States.' }
], {
  x: 0.75, y: H - FOOT_H + 0.12, w: W - 1.5, h: FOOT_H - 0.22, align: 'center', valign: 'middle',
  fontFace: 'Calibri', fontSize: 13, color: 'C7D9EC', margin: 0, lineSpacingMultiple: 1.10
});

pres.writeFile({ fileName: '/sessions/beautiful-determined-bell/mnt/outputs/SDG_Poster_A1.pptx' })
  .then(f => console.log('written', f));
