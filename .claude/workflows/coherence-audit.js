export const meta = {
  name: 'coherence-audit',
  description: 'Adversarial reliability sweep of SEM — hunt bug-class siblings, duplicated mechanisms, parallel systems, spec-vs-reality gaps, and tautological checks; cross-check against docs/BUG_CLASSES.md',
  whenToUse: 'Periodically, or after a batch of fixes, to find the NEXT reliability improvement before a user reports it. The wins in this repo come from closing bug CLASSES, not instances — this is the hunt that finds them.',
  phases: [
    { title: 'Find', detail: 'one agent per coherence dimension, in parallel' },
    { title: 'Verify', detail: 'adversarially confirm each candidate is real + actionable' },
    { title: 'Synthesize', detail: 'rank, cross-check vs the ledger, propose the next fix' },
  ],
}

// Optional scope override: args = { scope: "coordinator/", focus: "battery" }
const scope = (args && args.scope) || 'coordinator/ battery_adapters/ devices/ features/'
const focus = (args && args.focus) ? `\n\nFOCUS HINT (bias toward, don't ignore the rest): ${args.focus}` : ''

const LEDGER = 'docs/BUG_CLASSES.md'

// The generative insight of this repo, given to every agent so findings speak
// the same language: a fix is instance-local but the bug CLASS survives in the
// sibling paths. We hunt the shapes, not the instances.
const PREAMBLE = `You are auditing the SEM Home Assistant integration (Python) for RELIABILITY COHERENCE, not style.
Core lens: **a fix is instance-local but the bug CLASS survives in the sibling paths** — the same mechanism
breaks again in the next brand / charger / signal / battery. First READ ${LEDGER} (the bug-class ledger) so you
know the known classes and their guards. Search scope: ${scope}.${focus}
A finding is only worth reporting if it is a REAL coherence risk a user could hit — not a hypothetical, not a
nitpick. For each, give: file:line, the shape, WHY it can bite (a concrete scenario), and the cheapest structural closure.`

const FINDING_SCHEMA = {
  type: 'object',
  properties: {
    dimension: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          location: { type: 'string', description: 'file:line (or files) where it lives' },
          shape: { type: 'string', description: 'the recurring shape / mechanism' },
          scenario: { type: 'string', description: 'concrete way a user hits it' },
          siblings: { type: 'string', description: 'other paths the same shape lives in' },
          closure: { type: 'string', description: 'cheapest structural fix + a guard that makes regression unrepresentable' },
          ledger_class: { type: 'string', description: 'matching class number/name in the ledger, or NEW' },
          severity: { type: 'string', enum: ['blocker', 'high', 'medium', 'low'] },
        },
        required: ['title', 'location', 'shape', 'scenario', 'closure', 'ledger_class', 'severity'],
      },
    },
  },
  required: ['dimension', 'findings'],
}

// The five coherence dimensions — the sweep that found #587/#588/#589/#590 by hand.
const DIMENSIONS = [
  {
    key: 'bug-class-siblings',
    prompt: `${PREAMBLE}

DIMENSION: **bug-class sibling sweep**. For EACH class in ${LEDGER}, go to its "Where it lives" and check the
SIBLING paths — the next brand, charger, battery, signal. A class marked GUARDED may still have an unswept sibling
(the guard checks a read is annotated, not correct; a detector may cover grid but not battery). Classes marked
PARTIAL definitely have open siblings — find the exact file:line. Report each sibling where the class's mechanism
is NOT yet closed, and whether the existing guard would catch it.`,
  },
  {
    key: 'duplicated-mechanism',
    prompt: `${PREAMBLE}

DIMENSION: **duplicated mechanism**. Find the SAME mechanism (debounce, retry, reconcile, snapshot/restore/swap,
streak-count, warn-once, sign-audit, freshness check) implemented in 2+ places that could drift out of sync. For
each: name the two+ sites, why divergence bites, and the single primitive they should share. (Known-and-declined
dedups are listed under "Marginal refactor" in the ledger — don't re-report those; DO report new ones.)`,
  },
  {
    key: 'parallel-systems',
    prompt: `${PREAMBLE}

DIMENSION: **parallel systems that are one concept**. Find two things modeled SEPARATELY that are really one
(like arbitrage-vs-scheduler, or the EV budget before it was unified, or the ONE priority list). Symptom: a value
computed in two places, a decision made in two layers that must agree, state kept in two stores. For each: the two
systems, the concept they share, and what breaks when they disagree.`,
  },
  {
    key: 'spec-vs-reality',
    prompt: `${PREAMBLE}

DIMENSION: **spec-vs-reality gap** — something DESIGNED but never fully WIRED. Look for: a method/flag/health-signal
computed but never surfaced as an entity or acted on; a config key read but never written (or written never read);
a docstring/design-doc/comment describing behaviour the code doesn't implement; an autodetect branch that can't be
reached. VERIFY the assumed thing actually EXISTS (grep for the entity/key/call). This is how #590 was found (a
health method that was never an entity). Report each gap with proof it's unwired.`,
  },
  {
    key: 'tautologies',
    prompt: `${PREAMBLE}

DIMENSION: **tautological / can't-fail checks**. Find any "validation" or "health check" algebraically incapable of
firing — e.g. checking a derived value against the formula that defined it (the energy-balance check is 0=0 because
home is DEFINED by the balance). Also: try/except that swallows the very error it's meant to detect, an assert on a
just-assigned value, a guard whose condition is always true/false. For each: why it can't fire, and the INDEPENDENT
check that actually would.`,
  },
]

phase('Find')
log(`Coherence sweep over: ${scope}`)

// pipeline: each dimension's candidates get verified as soon as that finder
// returns — no barrier, so a fast dimension isn't held by a slow one.
const perDimension = await pipeline(
  DIMENSIONS,
  d => agent(d.prompt, { label: `find:${d.key}`, phase: 'Find', schema: FINDING_SCHEMA }),
  (found, d) => {
    const items = (found && found.findings) || []
    if (!items.length) return { dimension: d.key, verified: [] }
    return parallel(items.map(f => () =>
      agent(
        `Adversarially verify this SEM reliability finding. Default to REJECTED unless you can prove it's real.
Read the actual code at ${f.location} and confirm: (1) the shape is really there, (2) the scenario can actually
happen in a real install (not hypothetical), (3) the proposed closure is correct and wouldn't break siblings.
If the ledger_class is "${f.ledger_class}", sanity-check that classification against ${LEDGER}.

FINDING: ${JSON.stringify(f)}`,
        {
          label: `verify:${f.ledger_class}`,
          phase: 'Verify',
          schema: {
            type: 'object',
            properties: {
              real: { type: 'boolean' },
              reason: { type: 'string' },
              corrected_severity: { type: 'string', enum: ['blocker', 'high', 'medium', 'low'] },
              corrected_ledger_class: { type: 'string' },
            },
            required: ['real', 'reason'],
          },
        },
      ).then(v => ({ ...f, verdict: v })).catch(() => null),
    )).then(vs => ({ dimension: d.key, verified: vs.filter(Boolean) }))
  },
)

const confirmed = perDimension
  .filter(Boolean)
  .flatMap(d => d.verified)
  .filter(f => f.verdict && f.verdict.real)

log(`${confirmed.length} confirmed findings across ${DIMENSIONS.length} dimensions`)

phase('Synthesize')
const synthesis = await agent(
  `You are the synthesis step of a SEM coherence audit. Below are the ADVERSARIALLY-CONFIRMED findings.
Read ${LEDGER} once more. Produce a prioritised report for the maintainer (Guido):

1. Rank the findings by (severity × how many siblings the shape touches). The best fix closes a whole CLASS.
2. For each: is it an existing ledger class (which?), a new recurring shape (draft the one-row ledger entry:
   Symptom / Root shape / Where it lives / Closure / Guard / Refs), or a one-off?
3. Recommend THE ONE to do next — cheapest structural closure with the widest blast radius — and sketch the guard
   (AST lint / isolation oracle / contradiction detector) that would make the class unrepresentable.
4. Flag any finding that CONTRADICTS the ledger's current status (e.g. a class marked GUARDED with a live sibling).

Be concrete and short. This report drives the next reliability PR.

CONFIRMED FINDINGS:
${JSON.stringify(confirmed, null, 2)}`,
  { label: 'synthesize', phase: 'Synthesize' },
)

return { confirmedCount: confirmed.length, confirmed, report: synthesis }
