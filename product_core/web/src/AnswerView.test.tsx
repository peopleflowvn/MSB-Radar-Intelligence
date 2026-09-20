import { describe, expect, it } from "vitest";
import { AnswerTurn, extractAnswerCoverage } from "./AnswerView";

function turn(trace: Record<string, unknown>): AnswerTurn {
  return { text: "", sources: [], people: [], trace };
}

describe("answer coverage", () => {
  it("reports the full CandidateSet without pretending all profiles were deep-read", () => {
    expect(extractAnswerCoverage(turn({
      search_v2: { candidate_total: 120, judged: 120, not_read: 0, complete: true },
      pass1: { candidate_total: 60, judged: 55, unknown: 3, not_read: 5 },
    }))).toEqual({
      candidateTotal: 120,
      judged: 120,
      unknown: 0,
      notRead: 0,
      complete: true,
      degraded: false,
    });
  });

  it("prefers the normalized answer coverage contract", () => {
    expect(extractAnswerCoverage(turn({ answer_coverage: {
      candidate_total: 120, judged: 55, unknown: 3, not_read: 65,
      complete: false, retrieval_degraded: true,
    } }))).toMatchObject({
      candidateTotal: 120, judged: 55, unknown: 3, notRead: 65,
      complete: false, degraded: true,
    });
  });
});
