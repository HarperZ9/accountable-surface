// Node gate for the browser contour overlay: normalized [0,1] coords must map to
// canvas pixels exactly, so what the spectator sees overlays the same frame.
// Run: node --test web/overlay.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { normToCanvas } from "./overlay.js";

test("normToCanvas scales normalized polylines to canvas pixels", () => {
  const out = normToCanvas([[[0, 0], [1, 1], [0.5, 0.5]]], 200, 100);
  assert.deepEqual(out, [[[0, 0], [200, 100], [100, 50]]]);
});

test("normToCanvas handles multiple paths and empty input", () => {
  assert.deepEqual(normToCanvas([], 10, 10), []);
  assert.deepEqual(normToCanvas([[[0.25, 0.5]]], 40, 20), [[[10, 10]]]);
});
