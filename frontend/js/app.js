/* ResilientEdTech — frontend logic */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const api = (path, opts) => fetch(path, opts).then(async (r) => {
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || `Permintaan gagal (${r.status})`);
    }
    return r.json();
  });

  let translations = {};

  async function loadTranslations() {
    try {
      const [en, ms] = await Promise.all([
        fetch('/locales/en.json').then(r=>r.json()),
        fetch('/locales/ms.json').then(r=>r.json())
      ]);
      translations = { en, ms };
      renderTranslations();
      renderConstraintChips();
    } catch (e) {
      // fallback to embedded minimal map
      translations = {
        en: {
          brandTitle: "ResilientEdTech",
      brandTagline: "Innovative educational technology for low-resource remote teaching",
      navHome: "Home",
      navPlan: "Plan",
      navConstraints: "Constraints",
      navAnalysis: "Analysis",
      navReview: "Plan",
      navHelp: "Help",
      topbarMeta2: "Official Teaching Support",
      heroEyebrow: "Lesson Plan Analysis System",
      heroTitle: "Create a resilient teaching plan for remote classrooms.",
      heroText: "Automated analysis, adaptation for real constraints, and a ready-to-use plan aligned with curriculum goals.",
      heroStart: "Get Started",
      heroHow: "How does it work?",
      panelEyebrow: "Quick Start",
      panelTitle: "Three simple steps",
      step1Title: "Upload",
      step1Desc: "Submit your lesson plan file or photo.",
      step2Title: "Choose constraints",
      step2Desc: "Pick your device and connectivity limits.",
      step3Title: "Build",
      step3Desc: "Get an adapted teaching plan instantly.",
      uploadHeading: "Upload Your Lesson Plan",
      uploadHelp: "Take a photo or upload a PDF / Word / text file. Our vision model will read it for you.",
      dropzoneClick: "Click to choose",
      dropzoneOr: "or drag a file here",
      dropzoneHint: "Handwritten image, scan, PDF, DOCX, or TXT · max 15 MB",
      subjectLabel: "Subject",
      gradeLabel: "Grade / Year",
      topicLabel: "Topic",
      subjectPlaceholder: "Example: Science",
      gradePlaceholder: "Example: Year 7",
      topicPlaceholder: "Example: Cells as Living Units",
      lessonTextLabel: "Lesson plan text",
      lessonTextHint: "(auto-filled from your file — edit if needed)",
      lessonTextPlaceholder: "Paste or type your lesson plan here…",
      cvPreviewSummary: "Model vision preview (preprocessed scan)",
      cvPreviewAlt: "Page processed by the vision model",
      constraintsHeading: "What are your constraints?",
      constraintsHelp: "Choose all that apply — the plan will adapt to your conditions.",
      runButton: "Analyse & Build Plan",
      analysisEyebrow: "Curriculum Review",
      analysisTitle: "Alignment Analysis",
      planEyebrow: "Resilient Design",
      planTitle: "Your Teaching Plan",
      helpPrompt: "Need help?",
      helpTitle: "Tool & Term Assistant",
      helpText: "Not sure what a suggested tool means? Ask for a short explanation and low-resource tips.",
      faqPlaceholder: "Example: What is Plickers?",
      faqButton: "Ask",
      footerText: "ResilientEdTech · Built for remote teachers · Lesson plan analysis · Offline-friendly support",
      extractReading: "Reading",
      extractUsingModel: "with the vision model…",
      extractReadMethod: "Read via",
      extractConfidence: "OCR confidence",
      extractWords: "words",
      extractReview: "Please review the text below, then continue.",
      extractFailed: "Failed to read this file:",
      runHintEmpty: "Please upload or paste your lesson plan first.",
      runHintAnalysing: "Analyser is reviewing your plan…",
      runHintAuditing: "Auditor is adapting the plan to your constraints…",
      errorOccurred: "Error occurred:",
      faqProcessing: "Processing…",
      faqCannotAnswer: "Cannot answer:",
      faqWhatIs: "What is",
      faqHowToLabel: "How to use:",
      faqAlternativesLabel: "Low-tech alternatives:",
      learningObjectives: "Learning Objectives",
      successCriteria: "Success Criteria",
      technologyRecommendations: "Technology Recommendations (tap for details)",
      addressConstraints: "Addressing Your Constraints",
      lessonFlow: "Lesson Flow",
      assessment: "Assessment",
      materials: "Materials",
      curriculumAlignment: "Curriculum Alignment",
      poweredBy: "Powered by",
      detectedStandards: "Detected standards:",
      alignmentLabel: "alignment",
      gapsTitle: "Gaps to close",
      recsTitle: "Recommended actions",
      noMajorGaps: "No major gaps detected. 🎉",
      statusFallbackRule: "● Rule-based mode ·",
      statusOffline: "● offline",
      offlineModeLabel: "Ollama offline",
      phaseLabel: "Phase",
      activityLabel: "Activity",
      technologyLabel: "Technology (fit for constraints)",
      faqToolContext: "and how can I use it in a low-resource classroom?",
      printButton: "Print",
      faqButtonAsk: "Ask",
        },
        ms: {
          brandTitle: "ResilientEdTech",
      brandTagline: "Teknologi pendidikan inovatif untuk pengajaran jarak jauh sumber rendah",
      navHome: "Utama",
      navPlan: "Rancang",
      navConstraints: "Had",
      navAnalysis: "Analisis",
      navReview: "Rancangan",
      navHelp: "Bantuan",
      topbarMeta2: "Sokongan Mengajar Rasmi",
      heroEyebrow: "Sistem Analisis Rancangan Pengajaran",
      heroTitle: "Cipta rancangan pengajaran tahan lasak untuk bilik darjah jauh.",
      heroText: "Analisis automatik, penyesuaian kepada had sebenar, dan rancangan sedia guna sejajar dengan objektif kurikulum.",
      heroStart: "Mula",
      heroHow: "Bagaimana ia berfungsi?",
      panelEyebrow: "Mula Cepat",
      panelTitle: "Tiga langkah mudah",
      step1Title: "Muat naik",
      step1Desc: "Hantar fail rancangan pengajaran atau foto.",
      step2Title: "Pilih had",
      step2Desc: "Pilih had peranti dan sambungan anda.",
      step3Title: "Bina",
      step3Desc: "Dapatkan rancangan pengajaran yang disesuaikan dengan segera.",
      uploadHeading: "Muat Naik Rancangan Pengajaran Anda",
      uploadHelp: "Ambil foto atau muat naik fail PDF / Word / teks. Model visi kami akan membacanya untuk anda.",
      dropzoneClick: "Klik untuk pilih",
      dropzoneOr: "atau seret fail ke sini",
      dropzoneHint: "Imej tulisan tangan, imbasan, PDF, DOCX, atau TXT · maks 15 MB",
      subjectLabel: "Subjek",
      gradeLabel: "Gred / Tahun",
      topicLabel: "Topik",
      subjectPlaceholder: "Contoh: Sains",
      gradePlaceholder: "Contoh: Tahun 7",
      topicPlaceholder: "Contoh: Sel sebagai Unit Hidup",
      lessonTextLabel: "Teks rancangan pengajaran",
      lessonTextHint: "(diisi automatik dari fail anda — sunting jika perlu)",
      lessonTextPlaceholder: "Tampal atau taip rancangan pengajaran anda di sini…",
      cvPreviewSummary: "Pratonton penglihatan model (imbasan pra-proses)",
      cvPreviewAlt: "Halaman yang diproses oleh model visi",
      constraintsHeading: "Apakah had anda?",
      constraintsHelp: "Pilih semua yang berkenaan — rancangan akan disesuaikan dengan keadaan anda.",
      runButton: "Analisis & Bina Rancangan",
      analysisEyebrow: "Ulasan Kurikulum",
      analysisTitle: "Analisis Penjajaran",
      planEyebrow: "Reka Bentuk Tahan Lasak",
      planTitle: "Rancangan Pengajaran Anda",
      helpPrompt: "Perlukan bantuan?",
      helpTitle: "Pembantu Alat & Istilah",
      helpText: "Tidak pasti apa maksud alat yang dicadangkan? Tanya untuk penjelasan ringkas dan petua sumber rendah.",
      faqPlaceholder: "Contoh: Apa itu Plickers?",
      faqButton: "Tanya",
      footerText: "ResilientEdTech · Dibina untuk guru jarak jauh · Analisis rancangan pengajaran · Sokongan mesra luar talian",
      extractReading: "Membaca",
      extractUsingModel: "menggunakan model visi…",
      extractReadMethod: "Dibaca melalui",
      extractConfidence: "Keyakinan OCR",
      extractWords: "patah perkataan",
      extractReview: "Sila semak teks di bawah, kemudian teruskan.",
      extractFailed: "Gagal membaca fail ini:",
      runHintEmpty: "Sila muat naik atau tampal rancangan pengajaran anda terlebih dahulu.",
      runHintAnalysing: "Penganalisis sedang menyemak rancangan anda…",
      runHintAuditing: "Juru audit sedang menyesuaikan rancangan mengikut had anda…",
      errorOccurred: "Ralat berlaku:",
      faqProcessing: "Memproses…",
      faqCannotAnswer: "Tidak dapat menjawab:",
      faqWhatIs: "Apa itu",
      faqHowToLabel: "Cara menggunakan:",
      faqAlternativesLabel: "Alternatif tanpa teknologi:",
      learningObjectives: "Objektif Pembelajaran",
      successCriteria: "Kriteria Kejayaan",
      technologyRecommendations: "Cadangan Teknologi (ketuk untuk butiran)",
      addressConstraints: "Menangani Had Anda",
      lessonFlow: "Aliran Pelajaran",
      assessment: "Penilaian",
      materials: "Bahan",
      curriculumAlignment: "Penjajaran Kurikulum",
      poweredBy: "Dikuasakan oleh",
      detectedStandards: "Standard dikesan:",
      alignmentLabel: "penjajaran",
      gapsTitle: "Jurang untuk ditutup",
      recsTitle: "Tindakan yang disyorkan",
      noMajorGaps: "Tiada jurang utama dikesan. 🎉",
      statusFallbackRule: "● Mod berasaskan peraturan ·",
      statusOffline: "● luar talian",
      offlineModeLabel: "Ollama luar talian",
      phaseLabel: "Fasa",
      activityLabel: "Aktiviti",
      technologyLabel: "Teknologi (sesuai untuk had)",
      faqToolContext: "dan bagaimana saya boleh menggunakannya dalam bilik darjah sumber rendah?",
      printButton: "Cetak",
      faqButtonAsk: "Tanya",
        }
      };
    }
  }

  const CONSTRAINT_ITEMS = [
    { key: "no_internet", label: { en: "No internet", ms: "Tiada internet" } },
    { key: "limited_connectivity", label: { en: "Limited connectivity", ms: "Sambungan terhad" } },
    { key: "single_device", label: { en: "One device only", ms: "1 peranti sahaja" } },
    { key: "restricted_hardware", label: { en: "Limited hardware", ms: "Peranti terhad" } },
    { key: "single_screen", label: { en: "One screen", ms: "1 skrin" } },
    { key: "no_power", label: { en: "No electricity", ms: "Tiada elektrik" } },
  ];

  let currentLang = localStorage.getItem("resilient_lang") === "ms" ? "ms" : "en";
  const state = { constraints: new Set(), lastTools: [] };

  function t(key) {
    return translations[currentLang][key] || translations.en[key] || key;
  }

  function renderTranslations() {
    document.querySelectorAll("[data-i18n-key]").forEach((el) => {
      const key = el.dataset.i18nKey;
      if (key) el.textContent = t(key);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      const key = el.dataset.i18nPlaceholder;
      if (key) el.placeholder = t(key);
    });
    document.querySelectorAll("[data-i18n-alt]").forEach((el) => {
      const key = el.dataset.i18nAlt;
      if (key) el.alt = t(key);
    });
  }

  function updateLangButtons() {
    ["en", "ms"].forEach((lang) => {
      const btn = $("lang-" + lang);
      if (!btn) return;
      btn.classList.toggle("active", currentLang === lang);
    });
  }

  function renderConstraintChips() {
    const wrap = $("constraints");
    wrap.innerHTML = "";
    CONSTRAINT_ITEMS.forEach((item) => {
      const chip = document.createElement("div");
      chip.className = "chip";
      chip.textContent = item.label[currentLang];
      if (state.constraints.has(item.key)) chip.classList.add("active");
      chip.onclick = () => {
        chip.classList.toggle("active");
        if (state.constraints.has(item.key)) state.constraints.delete(item.key);
        else state.constraints.add(item.key);
      };
      wrap.appendChild(chip);
    });
  }

  function setLanguage(lang) {
    if (currentLang === lang) return;
    currentLang = lang;
    localStorage.setItem("resilient_lang", lang);
    document.documentElement.lang = lang;
    renderTranslations();
    updateLangButtons();
    renderConstraintChips();
    const runHint = $("run-hint");
    if (runHint.textContent && runHint.textContent !== "") {
      runHint.textContent = t("runHintEmpty");
    }
  }

  function initializeLanguage() {
    document.documentElement.lang = currentLang;
    loadTranslations().then(() => {
      updateLangButtons();
    });
    updateLangButtons();
    renderConstraintChips();
    $("lang-en").onclick = () => setLanguage("en");
    $("lang-ms").onclick = () => setLanguage("ms");
  }

  // ---------------- Health badge ----------------
  api("/api/health").then((h) => {
    const badge = $("status-badge");
    if (h.llm_enabled) {
      badge.textContent = `● Llama 3.2 3B · ${h.model}`;
      badge.className = "badge badge-live";
    } else {
      badge.textContent = `${t("statusFallbackRule")} ${h.mode || t("offlineModeLabel")}`;
      badge.className = "badge badge-fallback";
    }
  }).catch(() => {
    $("status-badge").textContent = t("statusOffline");
  });

  // ---------------- Constraints chips ----------------
  initializeLanguage();

  // ---------------- File upload + extraction ----------------
  const dz = $("dropzone");
  const fileInput = $("file-input");

  dz.onclick = () => fileInput.click();
  dz.ondragover = (e) => { e.preventDefault(); dz.classList.add("drag"); };
  dz.ondragleave = () => dz.classList.remove("drag");
  dz.ondrop = (e) => {
    e.preventDefault();
    dz.classList.remove("drag");
    if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
  };
  fileInput.onchange = () => { if (fileInput.files.length) handleFile(fileInput.files[0]); };

  async function handleFile(file) {
    const box = $("extract-status");
    box.className = "extract-status busy";
    box.innerHTML = `<span class="spinner"></span>${t("extractReading")} <b>${escapeHtml(file.name)}</b> ${t("extractUsingModel")}`;
    box.classList.remove("hidden");

    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await api("/api/extract", { method: "POST", body: fd });
      $("lesson-text").value = res.text || "";

      const previewWrap = $("cv-preview-wrap");
      if (res.preview_image) {
        $("cv-preview").src = res.preview_image;
        previewWrap.classList.remove("hidden");
      } else {
        previewWrap.classList.add("hidden");
      }

      const bits = [`${t("extractReadMethod")} <b>${escapeHtml(res.method)}</b>`];
      if (res.confidence != null) bits.push(`${t("extractConfidence")} ~${res.confidence}%`);
      bits.push(`${res.word_count} ${t("extractWords")}`);

      if (res.warnings && res.warnings.length) {
        box.className = "extract-status warn";
        box.innerHTML = `${bits.join(" · ")}<br>⚠️ ${res.warnings.map(escapeHtml).join("<br>⚠️ ")}`;
      } else {
        box.className = "extract-status ok";
        box.innerHTML = `✅ ${bits.join(" · ")}. ${t("extractReview")}`;
      }
    } catch (err) {
      box.className = "extract-status warn";
      box.textContent = `${t("extractFailed")} ${err.message}`;
    }
  }

  // ---------------- Run: Analyse + Audit ----------------
  $("run-btn").onclick = run;

  async function run() {
    const lessonText = $("lesson-text").value.trim();
    if (!lessonText) {
      $("run-hint").textContent = t("runHintEmpty");
      return;
    }
    const meta = {
      subject: $("subject").value.trim() || null,
      form: $("form").value.trim() || null,
      topic: $("topic").value.trim() || null,
    };

    const btn = $("run-btn");
    btn.disabled = true;
    $("run-hint").innerHTML = `<span class="spinner"></span>${t("runHintAnalysing")}`;

    try {
      const analyst = await api("/api/analyse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lesson_text: lessonText, ...meta }),
      });
      renderAnalyst(analyst);

      $("run-hint").innerHTML = `<span class="spinner"></span>${t("runHintAuditing")}`;
      const auditor = await api("/api/audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lesson_text: lessonText,
          constraints: [...state.constraints],
          analyst_summary: analyst.summary,
          ...meta,
        }),
      });
      renderAuditor(auditor);

      $("results").classList.remove("hidden");
      $("run-hint").textContent = "";
      $("results").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      $("run-hint").textContent = `${t("errorOccurred")} ${err.message}`;
    } finally {
      btn.disabled = false;
    }
  }

  // ---------------- Render: Analyst ----------------
  function renderAnalyst(a) {
    $("analyst-summary").textContent = a.summary;

    // gauge
    const circ = 327;
    $("gauge-fg").style.strokeDashoffset = circ - (circ * a.overall_alignment_score) / 100;
    animateNumber($("score-num"), a.overall_alignment_score);
    const color = a.overall_alignment_score >= 70 ? "#16a34a" : a.overall_alignment_score >= 45 ? "#d97706" : "#e11d48";
    $("gauge-fg").style.stroke = color;

    $("alignments").innerHTML = (a.alignments || []).map((al) => `
      <div class="align-item">
        <span class="status-pill s-${al.status}">${al.status.replace("_", " ")}</span>
        <h4>${escapeHtml(al.dimension)}</h4>
        <p>${escapeHtml(al.notes)}</p>
      </div>`).join("");

    $("gaps").innerHTML = listItems(a.gaps, t("noMajorGaps"));
    $("recs").innerHTML = listItems(a.recommendations, "—");
    $("score-num").parentElement.querySelector("small").textContent = t("alignmentLabel");

    const cs = a.content_standards_detected || [];
    const ls = a.learning_standards_detected || [];
    $("standards").innerHTML = (cs.length || ls.length)
      ? `<strong>${t("detectedStandards")}</strong> ${[...cs, ...ls].map((s) => `<code>${escapeHtml(s)}</code>`).join(" ")}
         <span class="badge-inline">· ${t("poweredBy")} ${escapeHtml(a.powered_by)}</span>`
      : `<span class="small">${t("poweredBy")} ${escapeHtml(a.powered_by)}</span>`;
  }

  // ---------------- Render: Auditor ----------------
  function renderAuditor(res) {
    const p = res.revised_plan;
    state.lastTools = p.recommended_tools || [];
    renderFaqChips();

    const meta = [
      p.subject && `📚 ${p.subject}`,
      p.form && `🎓 ${p.form}`,
      p.topic && `📖 ${p.topic}`,
      p.duration && `⏱️ ${p.duration}`,
    ].filter(Boolean).map((m) => `<span>${escapeHtml(m)}</span>`).join("");

    const phaseRows = (p.phases || []).map((ph) => `
      <tr>
        <td><strong>${escapeHtml(ph.phase)}</strong><br><span class="muted small">${escapeHtml(ph.duration)}</span></td>
        <td>${escapeHtml(ph.activity)}</td>
        <td>${escapeHtml(ph.technology)}</td>
      </tr>`).join("");

    const solutions = (p.constraint_solutions || []).map((s) => `
      <div class="solution"><b>${escapeHtml(s.constraint)}:</b> ${escapeHtml(s.strategy)}</div>`).join("");

    const tools = (p.recommended_tools || []).map((t) =>
      `<span class="tool-tag" data-tool="${escapeHtml(t)}">${escapeHtml(t)} 🔍</span>`).join("");

    $("revised-plan").innerHTML = `
      <h3 class="plan-title">${escapeHtml(p.title)}</h3>
      <div class="plan-meta">${meta}</div>

      ${section(`🎯 ${t("learningObjectives")}`, ulist(p.objectives))}
      ${section(`✔️ ${t("successCriteria")}`, ulist(p.success_criteria))}
      ${tools ? section(`🧰 ${t("technologyRecommendations")}`, `<div class=\"tool-tags\">${tools}</div>`) : ""}
      ${solutions ? section(`🛠️ ${t("addressConstraints")}`, `<div class=\"solutions\">${solutions}</div>`) : ""}
      ${phaseRows ? section(`📋 ${t("lessonFlow")}`, `
        <table class=\"phases\">
          <thead><tr><th>${t("phaseLabel")}</th><th>${t("activityLabel")}</th><th>${t("technologyLabel")}</th></tr></thead>
          <tbody>${phaseRows}</tbody>
        </table>`) : ""}
      ${p.assessment ? section(`📝 ${t("assessment")}`, `<p>${escapeHtml(p.assessment)}</p>`) : ""}
      ${section(`🎒 ${t("materials")}`, ulist(p.materials))}
      ${p.alignment_note ? section(`📐 ${t("curriculumAlignment")}`, `<p>${escapeHtml(p.alignment_note)}</p>`) : ""}
      <p class="muted small">${t("poweredBy")} ${escapeHtml(res.powered_by)}</p>
    `;

    // tool tags -> FAQ
    $("revised-plan").querySelectorAll(".tool-tag").forEach((el) => {
      el.onclick = () => askFaq(`${t("faqWhatIs")} ${el.dataset.tool} ${t("faqToolContext")}`);
    });
  }

  // ---------------- FAQ ----------------
  $("faq-btn").onclick = () => askFaq($("faq-q").value.trim());
  $("faq-q").addEventListener("keydown", (e) => { if (e.key === "Enter") askFaq($("faq-q").value.trim()); });

  function renderFaqChips() {
    const wrap = $("faq-chips");
    wrap.innerHTML = "";
    state.lastTools.slice(0, 5).forEach((term) => {
      const chip = document.createElement("div");
      chip.className = "chip";
      chip.textContent = `${t("faqWhatIs")} ${term}?`;
      chip.onclick = () => askFaq(`${t("faqWhatIs")} ${term}?`);
      wrap.appendChild(chip);
    });
  }

  async function askFaq(question) {
    if (!question) return;
    $("faq-q").value = "";
    const answers = $("faq-answers");
    const slot = document.createElement("div");
    slot.className = "faq-item";
    slot.innerHTML = `<h4>${escapeHtml(question)}</h4><p><span class="spinner"></span>${t("faqProcessing")}</p>`;
    answers.prepend(slot);

    try {
      const ctx = $("revised-plan").textContent.slice(0, 2000) || null;
      const r = await api("/api/faq", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, context: ctx }),
      });
      slot.innerHTML = `
        <h4>${escapeHtml(r.term)}</h4>
        <p>${escapeHtml(r.explanation)}</p>
        ${r.how_to_execute && r.how_to_execute.length ? `<strong class="small">${t("faqHowToLabel")}</strong><ol>${r.how_to_execute.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ol>` : ""}
        ${r.low_resource_notes ? `<div class="lr">📶 ${escapeHtml(r.low_resource_notes)}</div>` : ""}
        ${r.alternatives && r.alternatives.length ? `<strong class="small">${t("faqAlternativesLabel")}</strong><ul>${r.alternatives.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ul>` : ""}
      `;
    } catch (err) {
      slot.innerHTML = `<h4>${escapeHtml(question)}</h4><p class="muted">${t("faqCannotAnswer")} ${escapeHtml(err.message)}</p>`;
    }
  }

  // ---------------- Print ----------------
  $("print-btn").onclick = () => window.print();

  // ---------------- helpers ----------------
  function section(title, body) {
    return `<div class="plan-section"><h4>${title}</h4>${body}</div>`;
  }
  function ulist(arr) {
    if (!arr || !arr.length) return `<p class="muted small">—</p>`;
    return `<ul>${arr.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>`;
  }
  function listItems(arr, empty) {
    if (!arr || !arr.length) return `<li class="muted">${escapeHtml(empty)}</li>`;
    return arr.map((x) => `<li>${escapeHtml(x)}</li>`).join("");
  }
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function animateNumber(el, target) {
    let cur = 0;
    const step = Math.max(1, Math.round(target / 30));
    const t = setInterval(() => {
      cur = Math.min(target, cur + step);
      el.textContent = cur;
      if (cur >= target) clearInterval(t);
    }, 20);
  }
})();
