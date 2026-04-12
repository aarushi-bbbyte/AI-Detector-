/**
 * reportGenerator.js
 * Generates a PDF report for an AI detection result using jsPDF (loaded from CDN).
 * No backend needed — runs entirely in the browser.
 */

const JSPDF_CDN = "https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js";

async function loadJsPDF() {
  if (window.jspdf?.jsPDF) return window.jspdf.jsPDF;
  await new Promise((res, rej) => {
    if (document.querySelector(`script[src="${JSPDF_CDN}"]`)) { res(); return; }
    const s = document.createElement("script");
    s.src = JSPDF_CDN;
    s.onload = res;
    s.onerror = () => rej(new Error("Failed to load jsPDF"));
    document.head.appendChild(s);
  });
  return window.jspdf.jsPDF;
}

// ── Colour helpers ────────────────────────────────────────────────────────────

function scoreRgb(pct) {
  if (pct >= 75) return [239, 68,  68];   // red
  if (pct >= 50) return [249, 115, 22];   // orange
  if (pct >= 25) return [234, 179, 8];    // yellow
  return                [34,  197, 94];   // green
}

function confidenceRgb(conf) {
  if (conf > 0.7) return [34,  197, 94];  // green
  if (conf > 0.3) return [234, 179, 8];   // yellow
  return                 [100, 116, 139]; // slate
}

function hexToRgb(hex) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return [r, g, b];
}

// ── Layout constants ──────────────────────────────────────────────────────────
const PAGE_W    = 210; // A4 mm
const PAGE_H    = 297;
const MARGIN    = 18;
const CONTENT_W = PAGE_W - MARGIN * 2;

// ── Main export ───────────────────────────────────────────────────────────────

export async function downloadReport(result, meta = {}) {
  const JsPDF = await loadJsPDF();
  const doc   = new JsPDF({ unit: "mm", format: "a4" });

  let y = MARGIN; // current Y cursor

  // ── helpers ────────────────────────────────────────────────────────────────

  function checkPage(needed = 10) {
    if (y + needed > PAGE_H - MARGIN) {
      doc.addPage();
      y = MARGIN;
      drawHeader(false);
      y += 8;
    }
  }

  function text(str, x, fontSize = 10, rgb = [30, 41, 59], align = "left") {
    doc.setFontSize(fontSize);
    doc.setTextColor(...rgb);
    doc.text(str, x, y, { align });
  }

  function line(rgb = [30, 41, 59], lw = 0.3) {
    doc.setDrawColor(...rgb);
    doc.setLineWidth(lw);
    doc.line(MARGIN, y, PAGE_W - MARGIN, y);
  }

  function rect(x, yy, w, h, rgb, filled = true) {
    doc.setFillColor(...rgb);
    doc.setDrawColor(...rgb);
    if (filled) doc.rect(x, yy, w, h, "F");
    else        doc.rect(x, yy, w, h, "S");
  }

  function labelVal(label, val, x1 = MARGIN, x2 = MARGIN + 45) {
    checkPage(7);
    doc.setFontSize(9);
    doc.setTextColor(100, 116, 139);
    doc.text(label, x1, y);
    doc.setFontSize(10);
    doc.setTextColor(226, 232, 240);
    doc.text(String(val), x2, y);
    y += 6;
  }

  function sectionTitle(title) {
    checkPage(12);
    y += 4;
    doc.setFontSize(9);
    doc.setTextColor(100, 116, 139);
    doc.text(title.toUpperCase(), MARGIN, y);
    y += 3;
    line([51, 65, 85], 0.2);
    y += 5;
  }

  // ── background ─────────────────────────────────────────────────────────────
  function drawBackground() {
    doc.setFillColor(10, 15, 30);
    doc.rect(0, 0, PAGE_W, PAGE_H, "F");
  }

  function drawHeader(first = true) {
    if (first) drawBackground();
    // Header bar
    doc.setFillColor(13, 17, 30);
    doc.rect(0, 0, PAGE_W, 22, "F");
    // Logo mark
    doc.setFontSize(18);
    doc.setTextColor(99, 102, 241);
    doc.text("◈", MARGIN, 14);
    doc.setFontSize(14);
    doc.setTextColor(226, 232, 240);
    doc.text("AIScope", MARGIN + 8, 14);
    // Subtitle
    doc.setFontSize(8);
    doc.setTextColor(100, 116, 139);
    doc.text("AI Content Detection Report", MARGIN + 8, 19);
    // Date top right
    const now = new Date().toLocaleString();
    doc.setFontSize(7.5);
    doc.setTextColor(100, 116, 139);
    doc.text(now, PAGE_W - MARGIN, 14, { align: "right" });
    y = 30;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // PAGE 1
  // ═══════════════════════════════════════════════════════════════════════════
  drawBackground();
  drawHeader(true);

  // ── Document info ──────────────────────────────────────────────────────────
  const docName    = meta.filename     || "Pasted text";
  const vLabel     = meta.versionLabel || "";
  const submittedAt = meta.submitted_at
    ? new Date(Number(meta.submitted_at) * 1000).toLocaleString() : "—";

  doc.setFontSize(13);
  doc.setTextColor(226, 232, 240);
  doc.text(docName, MARGIN, y);
  y += 6;
  if (vLabel) {
    doc.setFontSize(9);
    doc.setTextColor(148, 163, 184);
    doc.text(`Version: ${vLabel}`, MARGIN, y);
    y += 5;
  }
  doc.setFontSize(8.5);
  doc.setTextColor(100, 116, 139);
  doc.text(`Analysed: ${submittedAt}`, MARGIN, y);
  y += 10;

  // ── Score dial (drawn as arc using bezier approximation → use filled rect gauge) ──
  const ai_pct    = result.ai_percentage  ?? 0;
  const hum_pct   = result.human_percentage ?? 0;
  const score     = result.score          ?? 0;
  const confidence = result.confidence    ?? 0;
  const label      = result.label         || "—";
  const confLevel  = result.confidence_level || "—";
  const scoreColor = scoreRgb(ai_pct);
  const confColor  = confidenceRgb(confidence);

  // Score gauge bar
  sectionTitle("Detection result");

  // Large percentage
  doc.setFontSize(36);
  doc.setTextColor(...scoreColor);
  doc.text(`${ai_pct.toFixed(1)}%`, MARGIN, y);
  doc.setFontSize(11);
  doc.setTextColor(148, 163, 184);
  doc.text("AI probability", MARGIN + 32, y);
  y += 4;

  // Progress bar
  const barW = CONTENT_W;
  rect(MARGIN, y, barW, 5, [30, 41, 59]);
  rect(MARGIN, y, barW * (ai_pct / 100), 5, scoreColor);
  y += 9;

  // Label + confidence badge
  doc.setFontSize(12);
  doc.setTextColor(226, 232, 240);
  doc.text(label, MARGIN, y);
  // Badge
  const badgeX = MARGIN + doc.getTextWidth(label) + 6;
  rect(badgeX - 2, y - 4, doc.getTextWidth(`${confLevel} confidence`) + 6, 5.5, [26, 26, 46]);
  doc.setFontSize(8.5);
  doc.setTextColor(...confColor);
  doc.text(`${confLevel} confidence`, badgeX + 1, y);
  y += 10;

  // ── Stats row ──────────────────────────────────────────────────────────────
  const statW = CONTENT_W / 3;
  const stats = [
    { label: "AI",         val: `${ai_pct.toFixed(1)}%`,    color: scoreColor },
    { label: "Human",      val: `${hum_pct.toFixed(1)}%`,   color: [34, 197, 94] },
    { label: "Raw score",  val: score.toFixed(3),             color: [148, 163, 184] },
  ];
  stats.forEach((s, i) => {
    const sx = MARGIN + i * statW;
    rect(sx, y, statW - 3, 14, [13, 17, 30]);
    doc.setFontSize(13);
    doc.setTextColor(...s.color);
    doc.text(s.val, sx + 3, y + 7);
    doc.setFontSize(7.5);
    doc.setTextColor(100, 116, 139);
    doc.text(s.label.toUpperCase(), sx + 3, y + 12);
  });
  y += 20;

  // ── Confidence meter ───────────────────────────────────────────────────────
  sectionTitle("Confidence");
  const confPct = Math.round(confidence * 100);
  doc.setFontSize(9);
  doc.setTextColor(148, 163, 184);
  doc.text("Confidence", MARGIN, y);
  doc.setFontSize(10);
  doc.setTextColor(...confColor);
  doc.text(`${confPct}%`, PAGE_W - MARGIN, y, { align: "right" });
  y += 4;
  rect(MARGIN, y, CONTENT_W, 4, [30, 41, 59]);
  rect(MARGIN, y, CONTENT_W * (confPct / 100), 4, confColor);
  y += 7;
  doc.setFontSize(8.5);
  doc.setTextColor(100, 116, 139);
  const confNote = confidence > 0.7 ? "Model is highly certain of this result"
                 : confidence > 0.3 ? "Moderate certainty — result may vary"
                 : "Low certainty — result is inconclusive";
  doc.text(confNote, MARGIN, y);
  y += 8;

  // ── Interpretation box ─────────────────────────────────────────────────────
  sectionTitle("How to interpret");
  rect(MARGIN, y, CONTENT_W, 16, [13, 17, 30]);
  doc.setFontSize(8.5);
  doc.setTextColor(148, 163, 184);
  const formula = `confidence = |score − 0.5| × 2  →  |${score.toFixed(3)} − 0.5| × 2 = ${confidence.toFixed(3)}`;
  doc.text(formula, MARGIN + 3, y + 6);
  doc.setTextColor(100, 116, 139);
  doc.text("Scores > 0.7 → high confidence   ·   0.3–0.7 → moderate   ·   < 0.3 → inconclusive", MARGIN + 3, y + 12);
  y += 22;

  // ── Model details ──────────────────────────────────────────────────────────
  const details = result.details || {};
  sectionTitle("Model details");
  labelVal("Model",            details.model            || "roberta-base-openai-detector");
  labelVal("Chunks analysed",  details.chunks_analyzed  ?? "—");
  labelVal("Word count",       details.word_count        ?? "—");
  labelVal("Score variance",   details.score_variance != null ? details.score_variance.toFixed(4) : "—");
  labelVal("Provider",         result.provider          || "huggingface");

  // ── Document preview ───────────────────────────────────────────────────────
  const preview = result.text_preview || meta.textPreview || "";
  if (preview) {
    sectionTitle("Document preview");
    const lines = doc.splitTextToSize(preview, CONTENT_W);
    lines.forEach(ln => {
      checkPage(6);
      doc.setFontSize(8.5);
      doc.setTextColor(148, 163, 184);
      doc.text(ln, MARGIN, y);
      y += 5;
    });
    y += 4;
  }

  // ── Per-chunk bar chart ────────────────────────────────────────────────────
  const chunkScores = details.chunk_scores || [];
  if (chunkScores.length > 0) {
    checkPage(50);
    sectionTitle(`Per-chunk AI scores (${chunkScores.length} chunks)`);

    const chartH   = 35;
    const chartW   = CONTENT_W;
    const barWidth = Math.min((chartW / chunkScores.length) - 1.5, 12);
    const barGap   = chartW / chunkScores.length;

    // Chart background
    rect(MARGIN, y, chartW, chartH, [13, 17, 30]);

    // Grid lines at 25%, 50%, 75%
    [0.25, 0.5, 0.75].forEach(pct => {
      const gy = y + chartH - (pct * chartH);
      doc.setDrawColor(30, 41, 59);
      doc.setLineWidth(0.2);
      doc.line(MARGIN, gy, MARGIN + chartW, gy);
      doc.setFontSize(6);
      doc.setTextColor(71, 85, 105);
      doc.text(`${pct * 100}%`, MARGIN + chartW + 1, gy + 1);
    });

    // Bars
    chunkScores.forEach((s, i) => {
      const bx  = MARGIN + i * barGap + (barGap - barWidth) / 2;
      const bh  = s * chartH;
      const by  = y + chartH - bh;
      const rgb = s >= 0.75 ? [239, 68, 68]
                : s >= 0.5  ? [249, 115, 22]
                : s >= 0.25 ? [234, 179, 8]
                :             [34, 197, 94];
      rect(bx, by, barWidth, bh, rgb);

      // Chunk number label
      if (chunkScores.length <= 20) {
        doc.setFontSize(5.5);
        doc.setTextColor(71, 85, 105);
        doc.text(String(i + 1), bx + barWidth / 2, y + chartH + 3.5, { align: "center" });
      }
    });

    y += chartH + 8;

    // Chunk score table
    checkPage(20);
    doc.setFontSize(8);
    doc.setTextColor(100, 116, 139);
    doc.text("Chunk", MARGIN, y);
    doc.text("AI Score", MARGIN + 20, y);
    doc.text("Classification", MARGIN + 45, y);
    y += 4;
    line([30, 41, 59], 0.2);
    y += 4;

    chunkScores.forEach((s, i) => {
      checkPage(6);
      const cls = s >= 0.75 ? "Likely AI"
                : s >= 0.5  ? "Possibly AI"
                : s >= 0.25 ? "Possibly Human"
                :             "Likely Human";
      const rgb = s >= 0.75 ? [239, 68, 68]
                : s >= 0.5  ? [249, 115, 22]
                : s >= 0.25 ? [234, 179, 8]
                :             [34, 197, 94];
      doc.setFontSize(8);
      doc.setTextColor(148, 163, 184);
      doc.text(`${i + 1}`, MARGIN, y);
      doc.setTextColor(...rgb);
      doc.text(`${(s * 100).toFixed(1)}%`, MARGIN + 20, y);
      doc.setTextColor(148, 163, 184);
      doc.text(cls, MARGIN + 45, y);
      y += 5.5;
    });
  }

  // ── Footer on every page ───────────────────────────────────────────────────
  const pageCount = doc.getNumberOfPages();
  for (let p = 1; p <= pageCount; p++) {
    doc.setPage(p);
    doc.setFillColor(10, 15, 30);
    doc.rect(0, PAGE_H - 10, PAGE_W, 10, "F");
    doc.setFontSize(7);
    doc.setTextColor(71, 85, 105);
    doc.text(
      "Generated by AIScope · roberta-base-openai-detector · For reference only — not a definitive assessment",
      PAGE_W / 2, PAGE_H - 4, { align: "center" }
    );
    doc.text(`Page ${p} of ${pageCount}`, PAGE_W - MARGIN, PAGE_H - 4, { align: "right" });
  }

  // ── Save ───────────────────────────────────────────────────────────────────
  const safeName = (meta.filename || "aiscope-report")
    .replace(/\.[^.]+$/, "")
    .replace(/[^a-z0-9_-]/gi, "_")
    .slice(0, 40);
  doc.save(`${safeName}_aiscope_report.pdf`);
}
