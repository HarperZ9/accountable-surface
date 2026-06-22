// recheck.js — re-derive a Certificate's verdict in the browser, from its own evidence.
//
// The world's action certificates are COMPOSED (oracle "composed-v1"): the verdict is the lattice
// meet of per-step sub-verdicts (gate, effect, grounding). Re-running the meet over the evidence
// reproduces the verdict the certificate carries — proof, not assertion. Mirrors
// coherence_membrane.composition.compose: REFUTED absorbs, UNVERIFIABLE attenuates,
// all-VERIFIED -> VERIFIED, empty -> UNVERIFIABLE (fail closed).

export function meet(verdicts) {
  if (!verdicts.length) return "unverifiable";
  if (verdicts.includes("refuted")) return "refuted";
  if (verdicts.includes("unverifiable")) return "unverifiable";
  return "verified";
}

// Re-derive a composed certificate's verdict from its own per-step evidence. Returns the
// re-derived verdict, the sub-verdicts it combined, and whether it matches the carried verdict.
export function recheckComposed(cert) {
  const subs = (cert.evidence || []).map(([name, verdict]) => ({ name, verdict }));
  const verdict = meet(subs.map(s => s.verdict));
  return { verdict, subs, matches: verdict === (cert.verdict || "") };
}
