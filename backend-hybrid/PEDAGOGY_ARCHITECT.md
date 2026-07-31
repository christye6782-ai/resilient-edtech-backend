# Merged agent — The Pedagogy Architect (Auditor + Differentiation)

Consolidates two roles into **one model call**: the Auditor (constraint-proof
lesson redesign) and the Differentiation Strategist (split the hands-on /
formative step into Remedial · Core · Enrichment tiers, mapped to KSSR
performance levels TP1–6).

## Why

The agents run offline on a local 3B model, where each call is slow. The
Differentiation Strategist operates on the very plan the Auditor produces, so
the two have high role cohesion — doing both in one structured call removes a
full round-trip. The Analyst (which *evaluates*) and the FAQ Coach (reactive,
per-question) stay separate on purpose: merging an evaluator with a generator
makes small models grade their own homework leniently, and the FAQ Coach has a
different lifecycle.

> **Presentation roles ≠ execution agents.** The UI can keep showing four named
> helpers in the rail; the backend just serves the Auditor + Differentiation
> sections from one endpoint.

## What's added / changed

| File | Change |
|---|---|
| `app/agents/pedagogy_architect.py` | **New.** The merged agent + combined JSON schema + partial-degradation logic + rule-based fallbacks. |
| `app/schemas.py` | **Superset.** Adds `DifferentiationTier`, `Differentiation`, `DesignRequest`, `DesignResult` (everything original is unchanged). |
| `app/data/differentiation_scaffolds.json` | **New.** The differentiation playbook (KSSR levels → tier templates + scaffold moves). |
| `app/config.py` | Adds `load_diff_scaffolds()`. |
| `app/main.py` | New **`POST /api/design`** (plan **+** tiers). `POST /api/audit` kept as a deprecated back-compat alias that returns only the plan. |

`app/agents/auditor.py` is still present — `pedagogy_architect` imports its
constraint map, tools digest and plan fallback, so nothing is duplicated.

## The key resilience feature — partial degradation

The combined schema is larger, which raises the chance a 3B model returns
*some* invalid JSON. So the agent salvages each part independently:

- Model returns a good plan **and** good tiers → both `*_source = "model"`.
- Model returns a good plan but thin/invalid tiers → keep the model plan,
  synthesise tiers from the playbook (`differentiation_source = "rule-based"`).
- Total failure → fully rule-based design.

`DesignResult.plan_source` and `.differentiation_source` report which path each
part took, so you can monitor model reliability in the field and decide whether
the merge is worth it vs. two smaller calls.

## API

```http
POST /api/design
{
  "lesson_text": "...",
  "constraints": ["No internet", "One device only", "No electricity"],
  "subject": "Science", "form": "Form 1", "topic": "Cell as a Unit of Life",
  "analyst_summary": "(optional — pass the Analyst's summary for grounding)"
}
```

```jsonc
// 200 OK
{
  "revised_plan": { "title": "...", "phases": [ ... ], ... },
  "differentiation": {
    "intro": "...",
    "note": "...",
    "tiers": [
      { "tier": "Remedial",   "malay": "Pemulihan", "tp": "TP1–2", "items": ["..."] },
      { "tier": "Core",       "malay": "Teras",     "tp": "TP3–4", "items": ["..."] },
      { "tier": "Enrichment", "malay": "Pengayaan", "tp": "TP5–6", "items": ["..."] }
    ]
  },
  "powered_by": "Cloud AI (gpt-4o-mini)",
  "plan_source": "model",
  "differentiation_source": "model"
}
```

### Frontend wiring (Design B)

The UI already renders an Auditor card and a Differentiation card. Point both at
one call:

```js
const r = await fetch('/api/design', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ lesson_text, constraints, subject, form, topic, analyst_summary }),
}).then(r => r.json());

renderAuditorCard(r.revised_plan);
renderDifferentiationCard(r.differentiation);   // r.differentiation.tiers → the 3 tier cards
```

## Apply

Drop these over the originals in `ResilientEdTech/app/` (commit first), alongside
the hybrid-engine files from `HYBRID.md`:

```
app/agents/pedagogy_architect.py     (new)
app/agents/auditor.py                (from backend-hybrid — still used as a helper/back-compat)
app/schemas.py                       (superset — replaces original)
app/config.py                        (adds load_diff_scaffolds)
app/main.py                          (adds /api/design)
app/data/differentiation_scaffolds.json   (new)
```

No new dependencies.
