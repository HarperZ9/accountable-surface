// Node gate for the browser re-check of the world's COMPOSED action certificate. The verdict is
// the lattice meet of per-step sub-verdicts (gate, effect, grounding); re-running the meet over
// the certificate's own evidence must reproduce the verdict it carries.
//
// Run: node --test web/recheck.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { meet, recheckComposed } from "./recheck.js";

test("meet: REFUTED absorbs, UNVERIFIABLE attenuates, all-VERIFIED wins, empty fails closed", () => {
  assert.equal(meet(["verified", "verified"]), "verified");
  assert.equal(meet(["verified", "refuted"]), "refuted");
  assert.equal(meet(["verified", "unverifiable"]), "unverifiable");
  assert.equal(meet(["refuted", "unverifiable"]), "refuted");   // refuted dominates
  assert.equal(meet([]), "unverifiable");                        // empty -> fail closed
});

test("recheckComposed reproduces a verified action certificate from its evidence", () => {
  const cert = {
    claim: "action: decision=allow verdict=pass", verdict: "verified", oracle: "composed-v1",
    evidence: [["step0:proof-surface-gate-v1", "verified"], ["step1:accountable-surface-effect-v1", "verified"]],
  };
  const r = recheckComposed(cert);
  assert.equal(r.verdict, "verified");
  assert.equal(r.matches, true);
  assert.equal(r.subs.length, 2);
  assert.equal(r.subs[0].verdict, "verified");
});

test("recheckComposed reproduces a refuted (denied) action certificate", () => {
  const cert = {
    claim: "action: decision=deny verdict=not-acted", verdict: "refuted", oracle: "composed-v1",
    evidence: [["step0:proof-surface-gate-v1", "refuted"]],
  };
  const r = recheckComposed(cert);
  assert.equal(r.verdict, "refuted");
  assert.equal(r.matches, true);
});
