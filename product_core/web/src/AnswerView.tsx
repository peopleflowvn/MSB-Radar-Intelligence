import { ReactNode, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AnswerPerson, AnswerSource, api, HuntRequestRow } from "./api";
import { inferFollowUpQuestions } from "./followUpInference";
import FormattedMarkdown, { LinkablePerson } from "./FormattedMarkdown";
import SourcePreview, { SourceRef } from "./SourcePreview";

/**
 * Hiển thị MỘT lượt trả lời của Answer Engine.
 *
 * Thay cho danh sách thẻ ứng viên cũ. Thẻ vừa chiếm gần hết màn hình, vừa lặp
 * lại y nguyên nội dung đã có trong câu trả lời, mà phần đánh giá trên thẻ lại
 * do một bộ chấm điểm khác sinh ra nên hay mâu thuẫn với chính câu trả lời.
 *
 * Ở đây câu trả lời là trung tâm; người chỉ còn là một dòng chip bấm được, và
 * trích dẫn [n] bấm ngay trong câu chữ để xem nguyên văn đoạn CV gốc.
 */

export interface AnswerStep {
  label: string;
  state: "active" | "done";
}

/** `TPerson` mặc định là người Talent (trích dẫn CV). Growth Radar dùng
 *  `AnswerTurn<ProspectAnswerPerson>` — cùng khuôn sự kiện SSE, chỉ khác hình
 *  dạng "người" trong kết quả (điểm ưu tiên thay vì trích dẫn CV). */
export interface AnswerTurn<TPerson = AnswerPerson> {
  text: string;
  stage?: string;
  /** "Đã nhận yêu cầu — đây là cách mình định làm", hiện ngay sau khi hiểu câu
   *  hỏi, trước khi các bước tốn thời gian chạy. */
  preamble?: string;
  /** Các bước đang/đã làm — để giao diện tick dần thay vì đổ token suy nghĩ. */
  steps?: AnswerStep[];
  sources: AnswerSource[];
  people: TPerson[];
  /** Radar tự phát hiện lỗi trong câu trả lời và viết lại. */
  revised?: boolean;
  /** Nguồn ngoài internet khi Radar tra web để trả lời. */
  webSources?: Array<{ title?: string; url: string }>;
  reasoning?: string;
  provider?: string;
  model?: string;
  trace?: Record<string, unknown>;
  /** Thời gian từ khi server nhận câu hỏi đến khi có câu trả lời hoàn chỉnh. */
  durationMs?: number;
}

function sourceRef(source: AnswerSource): SourceRef {
  return {
    documentId: source.document_id,
    snippet: source.snippet,
    personName: source.name,
    personId: source.person_id,
    label: `[${source.n}]`,
  };
}

function extractPersonInfo(person: AnswerPerson, sources: AnswerSource[] = []) {
  const attrs = person.attributes ?? {};
  const lowerAttrs: Record<string, string | number> = {};
  for (const [k, v] of Object.entries(attrs)) {
    lowerAttrs[k.toLowerCase().trim()] = v;
  }

  // 1. Role / Title
  let role =
    attrs["Chức danh"] ||
    attrs["Vị trí"] ||
    attrs["role"] ||
    attrs["title"] ||
    attrs["Nghề nghiệp"] ||
    attrs["Chuyên môn"] ||
    lowerAttrs["chức danh"] ||
    lowerAttrs["vị trí"] ||
    lowerAttrs["role"] ||
    lowerAttrs["title"] ||
    lowerAttrs["nghề nghiệp"] ||
    lowerAttrs["chuyên môn"] ||
    person.profile?.title;

  // 2. Company
  let company =
    attrs["Công ty"] ||
    attrs["Đơn vị"] ||
    attrs["company"] ||
    attrs["organization"] ||
    attrs["Nơi làm việc"] ||
    lowerAttrs["công ty"] ||
    lowerAttrs["đơn vị"] ||
    lowerAttrs["company"] ||
    lowerAttrs["nơi làm việc"] ||
    person.profile?.company;

  // 3. Location
  const location =
    attrs["Địa điểm"] ||
    attrs["Khu vực"] ||
    attrs["location"] ||
    attrs["city"] ||
    attrs["Tỉnh thành"] ||
    lowerAttrs["địa điểm"] ||
    lowerAttrs["khu vực"] ||
    lowerAttrs["location"] ||
    lowerAttrs["tỉnh thành"] ||
    person.profile?.location;

  // 4. Experience
  const experience =
    attrs["Kinh nghiệm"] ||
    attrs["Kinh nghiệm (năm)"] ||
    attrs["Số năm kinh nghiệm"] ||
    attrs["experience"] ||
    attrs["years_experience"] ||
    lowerAttrs["kinh nghiệm"] ||
    lowerAttrs["kinh nghiệm (năm)"] ||
    lowerAttrs["số năm kinh nghiệm"] ||
    lowerAttrs["experience"] ||
    (person.profile?.years_experience != null ? person.profile.years_experience : undefined);

  // 5. Matching sources
  const personSources = (sources || []).filter(
    (s) => s.person_id === person.person_id || (person.name && s.name === person.name)
  );
  const citationNums = (person.citations && person.citations.length > 0)
    ? person.citations
    : personSources.map((s) => s.n);

  // 6. Highlight text / why / snippet fallback
  let highlight = (person.why || "").trim();
  if (!highlight && personSources.length > 0) {
    const rawSnippet = personSources[0].snippet || "";
    const cleanSnippet = rawSnippet.replace(/[#*`_]/g, "").replace(/\s+/g, " ").trim();
    if (cleanSnippet) {
      highlight = cleanSnippet.length > 130 ? `${cleanSnippet.slice(0, 127)}…` : cleanSnippet;
    }
  }

  // If role is still missing, try to get a quick summary from the first line of snippet
  if (!role && personSources.length > 0) {
    const firstLine = (personSources[0].snippet || "").split("\n")[0]?.replace(/[#*`_]/g, "").trim();
    if (firstLine && firstLine.length < 75 && !firstLine.includes(person.name)) {
      role = firstLine;
    }
  }

  const headline = [role, company].filter(Boolean).join(" · ");

  return {
    headline: String(headline || ""),
    location: location ? String(location) : null,
    experience: experience ? String(experience) : null,
    citationNums,
    highlight: highlight || null,
    extraAttrs: Object.entries(attrs).filter(([k]) => {
      const lk = k.toLowerCase().trim();
      return !["chức danh", "vị trí", "role", "title", "nghề nghiệp", "chuyên môn", "công ty", "đơn vị", "company", "organization", "nơi làm việc", "địa điểm", "khu vực", "location", "city", "tỉnh thành", "kinh nghiệm", "kinh nghiệm (năm)", "số năm kinh nghiệm", "experience", "years_experience"].includes(lk);
    }),
  };
}

/** Một thẻ hồ sơ. `nearMiss`: người bị loại nhưng khớp một phần — hiện điều CÒN
 * THIẾU, không hiện lý do như một điểm mạnh (production 19/09: dòng 💡 hiện
 * "…không phải Senior Data Analyst" trên thẻ nằm cùng hàng với người phù hợp). */
function TalentPersonCard({
  person,
  sources,
  personLinkFrom,
  nearMiss,
  openHunts = [],
  onAddToHunt,
  isAddingToHunt,
  addedHuntName,
}: {
  person: AnswerPerson;
  sources: AnswerSource[];
  personLinkFrom: string;
  nearMiss: boolean;
  openHunts?: HuntRequestRow[];
  onAddToHunt?: (personId: number, huntId: number) => void;
  isAddingToHunt?: boolean;
  addedHuntName?: string;
}) {
  const info = extractPersonInfo(person, sources);
  const gap = (person.gap || "").trim();
  const note = nearMiss ? (gap || info.highlight) : info.highlight;
  return (
    <div
      className={`talent-compact-card${nearMiss ? " is-near-miss" : ""}`}
      title={`Hồ sơ của ${person.name}`}
    >
      <div className="talent-card-header">
        <div className="talent-card-avatar">
          {(person.name || "U")[0]?.toUpperCase()}
        </div>
        <div className="talent-card-title-wrap">
          <div className="talent-card-name-row">
            <Link
              to={`/person/${person.person_id}?from=${personLinkFrom}`}
              className="talent-card-name"
              title={`Mở hồ sơ 360° của ${person.name}`}
            >
              {person.name}
            </Link>
            {info.citationNums.length > 0 && (
              <span className="talent-card-citations" title="Trích dẫn bằng chứng trong CV">
                {info.citationNums.map((c) => `[${c}]`).join(" ")}
              </span>
            )}
          </div>
          {info.headline && (
            <div className="talent-card-headline" title={info.headline}>
              {info.headline}
            </div>
          )}
        </div>
      </div>

      {note && (
        <div className="talent-card-why" title={note}>
          <span className="talent-why-icon">{nearMiss ? "⚠️" : "💡"}</span>
          <span className="talent-why-text">
            {nearMiss && gap ? `Còn thiếu: ${gap}` : note}
          </span>
        </div>
      )}

      <div className="talent-card-attributes">
        {info.experience && (
          <span className="talent-attr-pill" title={`Kinh nghiệm: ${info.experience}`}>
            ⏱️ {String(info.experience).includes("năm") || String(info.experience).includes("tháng") ? info.experience : `${info.experience} năm KN`}
          </span>
        )}
        {info.location && (
          <span className="talent-attr-pill" title={`Địa điểm: ${info.location}`}>
            📍 {info.location}
          </span>
        )}
        {info.extraAttrs.slice(0, 2).map(([key, value]) => (
          <span key={key} className="talent-attr-pill" title={`${key}: ${value}`}>
            {`${key}: ${value}`}
          </span>
        ))}
      </div>

      <div className="talent-card-footer-row">
        <Link
          to={`/person/${person.person_id}?from=${personLinkFrom}`}
          className="talent-attr-pill profile-link-pill"
          title={`Xem chi tiết hồ sơ 360° của ${person.name}`}
        >
          Xem 360° →
        </Link>

        {openHunts.length > 0 && onAddToHunt && (
          <div className="talent-card-hunt-action" onClick={(e) => e.stopPropagation()}>
            <select
              className={`talent-card-hunt-select${addedHuntName ? " is-added" : ""}`}
              disabled={isAddingToHunt}
              value=""
              onChange={(e) => {
                const hid = Number(e.target.value);
                if (hid) onAddToHunt(person.person_id, hid);
              }}
              title="Thêm ứng viên vào đợt tuyển dụng hoặc nhiệm vụ săn"
            >
              <option value="" disabled>
                {isAddingToHunt
                  ? "⏳ Đang thêm…"
                  : addedHuntName
                  ? `✓ Đã vào: ${addedHuntName}`
                  : "🎯 + Đợt tuyển…"}
              </option>
              {openHunts.map((h) => (
                <option key={h.id} value={h.id}>
                  {h.title}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>
    </div>
  );
}

function TalentCardGroup({
  title,
  people,
  sources,
  personLinkFrom,
  nearMiss,
  openHunts = [],
  onAddToHunt,
  addingPersonId,
  addedHuntNames,
  onBulkAddToHunt,
  bulkStatus,
}: {
  title: string;
  people: AnswerPerson[];
  sources: AnswerSource[];
  personLinkFrom: string;
  nearMiss: boolean;
  openHunts?: HuntRequestRow[];
  onAddToHunt?: (personId: number, huntId: number) => void;
  addingPersonId?: number | null;
  addedHuntNames?: Record<number, string>;
  onBulkAddToHunt?: (huntId: number, targetPeople: AnswerPerson[]) => void;
  bulkStatus?: string | null;
}) {
  const [expanded, setExpanded] = useState(false);
  if (people.length === 0) return null;

  const INITIAL_LIMIT = 6;
  const hasMore = people.length > INITIAL_LIMIT;
  const visiblePeople = (!hasMore || expanded) ? people : people.slice(0, INITIAL_LIMIT);

  return (
    <div className={`talent-smart-section${nearMiss ? " is-near-miss" : ""}`}>
      <div className="talent-smart-header">
        <span className="talent-smart-title">
          <span>{title}</span> <span className="talent-smart-count">({people.length})</span>
        </span>

        <div className="talent-smart-header-right">
          {!nearMiss && openHunts.length > 0 && onBulkAddToHunt && people.length > 1 && (
            <div className="talent-bulk-hunt-wrap" onClick={(e) => e.stopPropagation()}>
              {bulkStatus ? (
                <span className="talent-smart-bulk-status">{bulkStatus}</span>
              ) : (
                <select
                  className="talent-card-hunt-select talent-bulk-hunt-select"
                  value=""
                  onChange={(e) => {
                    const hid = Number(e.target.value);
                    if (hid) onBulkAddToHunt(hid, people);
                  }}
                  title={`Thêm tất cả ${people.length} ứng viên vào đợt tuyển / nhiệm vụ săn`}
                >
                  <option value="" disabled>🎯 Thêm cả {people.length} vào đợt tuyển…</option>
                  {openHunts.map((h) => (
                    <option key={h.id} value={h.id}>
                      {h.title}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}

          {hasMore && (
            <button
              type="button"
              className="talent-header-expand-link"
              onClick={() => setExpanded((prev) => !prev)}
            >
              {expanded ? "Thu gọn ▴" : `Xem tất cả ${people.length} hồ sơ ▾`}
            </button>
          )}
        </div>
      </div>

      <div className="talent-smart-grid">
        {visiblePeople.map((person) => (
          <TalentPersonCard
            key={person.person_id}
            person={person}
            sources={sources}
            personLinkFrom={personLinkFrom}
            nearMiss={nearMiss}
            openHunts={openHunts}
            onAddToHunt={onAddToHunt}
            isAddingToHunt={addingPersonId === person.person_id}
            addedHuntName={addedHuntNames?.[person.person_id]}
          />
        ))}
      </div>

      {hasMore && (
        <div className="talent-cards-expand-row">
          <button
            type="button"
            className="talent-cards-expand-btn"
            onClick={() => setExpanded((prev) => !prev)}
          >
            {expanded
              ? "▴ Thu gọn danh sách ứng viên"
              : `▾ Xem thêm ${people.length - INITIAL_LIMIT} ứng viên khác`}
          </button>
        </div>
      )}
    </div>
  );
}

/** Thẻ ứng viên cho Talent Radar: người phù hợp và người GẦN phù hợp là hai nhóm
 * riêng — gộp chung dưới một tiêu đề thì người bị loại trông như một kết quả. */
function TalentSmartCards({
  people,
  personLinkFrom = "talent-ai",
  sources = [],
}: {
  people: AnswerPerson[];
  personLinkFrom?: string;
  sources?: AnswerSource[];
}) {
  if (!people || people.length === 0) return null;
  const qc = useQueryClient();
  const huntsQuery = useQuery({
    queryKey: ["hunts", "open-for-cards"],
    queryFn: () => api.hunts({ open: true, limit: 100 }).catch(() => ({ count: 0, limit: 100, offset: 0, results: [] })),
    staleTime: 60_000,
  });
  const openHunts = huntsQuery.data?.results ?? [];

  const [addingPersonId, setAddingPersonId] = useState<number | null>(null);
  const [addedHuntNames, setAddedHuntNames] = useState<Record<number, string>>({});
  const [bulkStatus, setBulkStatus] = useState<string | null>(null);

  const handleAddToHunt = async (personId: number, huntId: number) => {
    const hunt = openHunts.find((h) => h.id === huntId);
    setAddingPersonId(personId);
    try {
      await api.huntUpdate(huntId, { person_ids_add: [personId] });
      setAddedHuntNames((prev) => ({ ...prev, [personId]: hunt?.title || "Đợt tuyển" }));
      qc.invalidateQueries({ queryKey: ["hunts"] });
      qc.invalidateQueries({ queryKey: ["hunt-tasks"] });
    } catch (e) {
      console.error("Lỗi khi thêm vào đợt tuyển:", e);
    } finally {
      setAddingPersonId(null);
    }
  };

  const handleBulkAddToHunt = async (huntId: number, targetPeople: AnswerPerson[]) => {
    const hunt = openHunts.find((h) => h.id === huntId);
    const ids = targetPeople.map((p) => p.person_id);
    setBulkStatus(`Đang thêm ${ids.length} ứng viên…`);
    try {
      await api.huntUpdate(huntId, { person_ids_add: ids });
      const huntTitle = hunt?.title || "đợt tuyển";
      setBulkStatus(`✓ Đã thêm ${ids.length} ứng viên vào ${huntTitle}`);
      setAddedHuntNames((prev) => {
        const next = { ...prev };
        ids.forEach((id) => { next[id] = huntTitle; });
        return next;
      });
      qc.invalidateQueries({ queryKey: ["hunts"] });
      qc.invalidateQueries({ queryKey: ["hunt-tasks"] });
      setTimeout(() => setBulkStatus(null), 4000);
    } catch (e) {
      setBulkStatus("Lỗi khi thêm vào đợt tuyển");
      setTimeout(() => setBulkStatus(null), 3000);
    }
  };

  const matched = people.filter((p) => p.judgement_status !== "SUGGESTION");
  const near = people.filter((p) => p.judgement_status === "SUGGESTION");
  return (
    <>
      <TalentCardGroup
        title="Hồ sơ phù hợp"
        people={matched}
        sources={sources}
        personLinkFrom={personLinkFrom}
        nearMiss={false}
        openHunts={openHunts}
        onAddToHunt={handleAddToHunt}
        addingPersonId={addingPersonId}
        addedHuntNames={addedHuntNames}
        onBulkAddToHunt={handleBulkAddToHunt}
        bulkStatus={bulkStatus}
      />
      <TalentCardGroup
        title="Gần phù hợp — chưa đạt đủ tiêu chí"
        people={near}
        sources={sources}
        personLinkFrom={personLinkFrom}
        nearMiss
        openHunts={openHunts}
        onAddToHunt={handleAddToHunt}
        addingPersonId={addingPersonId}
        addedHuntNames={addedHuntNames}
      />
    </>
  );
}

/** 👍/👎 trên một câu trả lời. Gửi một lần, không cho đổi ý loạn xạ. */
function Rating({ turn, question, conversationId }: {
  turn: AnswerTurn<any>; question?: string; conversationId?: string;
}) {
  const [sent, setSent] = useState<"up" | "down" | null>(null);
  const [failed, setFailed] = useState(false);

  const send = (rating: "up" | "down") => {
    setSent(rating);
    api.aiFeedback({ rating, conversation_id: conversationId,
                     question, answer: turn.text })
      .catch(() => { setFailed(true); setSent(null); });
  };

  if (sent) {
    return <span className="answer-rating-done muted small">Cảm ơn phản hồi của bạn.</span>;
  }
  return (
    <div className="answer-rating">
      <span className="muted small">Câu trả lời này có dùng được không?</span>
      <button type="button" className="answer-rating-btn" title="Dùng được"
              onClick={() => send("up")}>👍</button>
      <button type="button" className="answer-rating-btn" title="Chưa dùng được"
              onClick={() => send("down")}>👎</button>
      {failed && <span className="muted small">Không gửi được, thử lại sau.</span>}
    </div>
  );
}

/** Mặc định dùng cho Talent (`turn.people` là `AnswerPerson[]`). Growth Radar
 *  truyền `getFollowUps` riêng vì "ứng viên" ở đây là "khách hàng". */
function getFollowUpSuggestions(turn: AnswerTurn<any>, question?: string): string[] {
  return inferFollowUpQuestions(turn, { domain: "talent", question });
}

export interface WorkflowModelItem {
  role: string;
  provider?: string;
  model?: string;
  icon?: string;
}

export interface AnswerCoverage {
  method: string;
  candidateTotal: number;
  evaluated: number;
  judged: number;
  unknown: number;
  notRead: number;
  complete: boolean;
  degraded: boolean;
}

/** Normalize both Search V2 and the legacy pass trace into one honest UI contract. */
export function extractAnswerCoverage<TPerson>(turn: AnswerTurn<TPerson>): AnswerCoverage | null {
  const trace = turn.trace as any;
  const source = trace?.answer_coverage || trace?.search_v2 || trace?.pass2 || trace?.pass1;
  if (!source || typeof source !== "object") return null;
  const number = (value: unknown) => Math.max(0, Number.isFinite(Number(value)) ? Number(value) : 0);
  const candidateTotal = number(source.candidate_total ?? source.population ?? source.retrieved);
  const judged = number(source.judged);
  const method = String(source.method || "deep_read");
  const evaluated = number(source.evaluated ?? (method === "deep_read" ? judged : candidateTotal));
  const unknown = number(source.unknown ?? source.criteria_unknown);
  const notRead = number(source.not_read ?? source.unread ?? Math.max(0, candidateTotal - judged));
  if (!candidateTotal && !judged && !unknown && !notRead) return null;
  return {
    method,
    candidateTotal,
    evaluated,
    judged,
    unknown,
    notRead,
    complete: Boolean(source.complete ?? (candidateTotal > 0 && notRead === 0 && unknown === 0)),
    degraded: Boolean(source.degraded || source.retrieval_degraded || source.semantic_degraded),
  };
}

function CoverageSummary<TPerson>({ turn }: { turn: AnswerTurn<TPerson> }) {
  const coverage = extractAnswerCoverage(turn);
  if (!coverage) return null;
  const partial = !coverage.complete || coverage.unknown > 0 || coverage.notRead > 0;

  if (coverage.method === "sql_aggregate") {
    return (
      <div className="answer-coverage-card is-complete" role="status" aria-label="Phạm vi rà soát hồ sơ">
        <div className="answer-coverage-header">
          <span className="coverage-icon">📊</span>
          <span className="coverage-title">Đã đối soát toàn kho bằng SQL ({coverage.evaluated}/{coverage.candidateTotal} hồ sơ)</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`answer-coverage-card ${partial ? "is-optimized" : "is-complete"}`}
         role="status" aria-label="Phạm vi rà soát hồ sơ">
      <div className="answer-coverage-header">
        <div className="answer-coverage-title-row">
          <span className="coverage-icon">🎯</span>
          <strong className="coverage-title">
            {partial
              ? "Sàng lọc từ kho & Đọc sâu các hồ sơ phù hợp nhất"
              : "Đã hoàn tất rà soát toàn bộ hồ sơ"}
          </strong>
        </div>
        <div className="answer-coverage-badges">
          <span className="coverage-badge highlight" title="Số hồ sơ tiềm năng nhất được AI đọc kỹ chi tiết từng phần bằng chứng CV">
            📖 Đọc sâu {coverage.judged}/{coverage.candidateTotal} hồ sơ
          </span>
          {coverage.notRead > 0 && (
            <span className="coverage-badge muted" title="Các hồ sơ xếp hạng thấp hơn ở vòng lọc sơ bộ, được bỏ qua đọc sâu để tối ưu thời gian phản hồi">
              ⚡ {coverage.notRead} hồ sơ xếp hạng thấp hơn (bỏ qua đọc sâu để tối ưu tốc độ)
            </span>
          )}
          {coverage.unknown > 0 && (
            <span className="coverage-badge warning">
              ⚠️ {coverage.unknown} chưa đủ bằng chứng
            </span>
          )}
          {coverage.degraded && (
            <span className="coverage-badge warning">
              ⚠️ Một nhánh tìm kiếm đang suy giảm
            </span>
          )}
        </div>
      </div>
      {partial && coverage.notRead > 0 && (
        <div className="answer-coverage-explainer">
          <span>
            💡 Hệ thống đã sàng lọc toàn bộ <strong>{coverage.candidateTotal} hồ sơ</strong> trong kho theo tiêu chí tìm kiếm và chọn lọc <strong>{coverage.judged} hồ sơ tối ưu nhất</strong> để đọc sâu chi tiết. <strong>{coverage.notRead} hồ sơ còn lại</strong> có độ tương thích thấp hơn ở vòng lọc sơ bộ nên được bỏ qua nhằm tối ưu thời gian phản hồi mà vẫn đảm bảo độ chuẩn xác cao.
          </span>
        </div>
      )}
    </div>
  );
}

export function extractWorkflowModels<TPerson>(turn: AnswerTurn<TPerson>): WorkflowModelItem[] {
  const trace = turn.trace as any;
  if (Array.isArray(trace?.workflow_models) && trace.workflow_models.length > 0) {
    return trace.workflow_models
      .map((item: any) => ({
        role: item.role || item.stage || "Mô hình",
        provider: item.provider,
        model: item.model,
        icon:
          item.icon ||
          (item.stage === "plan"
            ? "🎯"
            : item.stage === "judge"
            ? "⚖️"
            : item.stage === "compose"
            ? "✍️"
            : item.stage === "action"
            ? "⚡"
            : item.stage === "chat"
            ? "💬"
            : item.stage === "assess_doc"
            ? "📄"
            : "🤖"),
      }))
      .filter((m: WorkflowModelItem) => Boolean(m.model || m.provider));
  }

  const items: WorkflowModelItem[] = [];

  // Lập kế hoạch (Plan)
  const plan = trace?.plan;
  if (plan && (plan.model || plan.provider)) {
    items.push({
      role: "Lập kế hoạch",
      provider: plan.provider,
      model: plan.model,
      icon: "🎯",
    });
  }

  // Sàng lọc & Đánh giá (Judge)
  const pass1 = trace?.pass1;
  const pass2 = trace?.pass2;
  const judge = trace?.judge;
  const judgeModel = judge?.model || pass1?.model || pass2?.model;
  const judgeProvider = judge?.provider || pass1?.provider || pass2?.provider;
  if (judgeModel || judgeProvider) {
    items.push({
      role: "Sàng lọc & Đánh giá",
      provider: judgeProvider,
      model: judgeModel,
      icon: "⚖️",
    });
  }

  // Tổng hợp & Trả lời (Compose)
  const compose = trace?.compose;
  const composeModel = compose?.model || turn.model;
  const composeProvider = compose?.provider || turn.provider;
  const isFallback = Boolean((compose as { fallback?: boolean } | undefined)?.fallback);

  if (!isFallback && (composeModel || composeProvider)) {
    const isChat = trace?.mode === "chat";
    const isAction = trace?.mode === "action";
    const isAssessDoc = trace?.mode === "assess_doc";
    const role = isChat
      ? "Hội thoại"
      : isAction
      ? "Thực thi tác vụ"
      : isAssessDoc
      ? "Đọc & Phân tích tệp"
      : "Tổng hợp & Trả lời";
    const icon = isChat ? "💬" : isAction ? "⚡" : isAssessDoc ? "📄" : "✍️";
    items.push({
      role,
      provider: composeProvider,
      model: composeModel,
      icon,
    });
  }

  if (items.length === 0 && !isFallback && (turn.model || turn.provider)) {
    items.push({
      role: "Mô hình xử lý",
      provider: turn.provider,
      model: turn.model,
      icon: "🤖",
    });
  }

  return items;
}

export default function AnswerView<TPerson = AnswerPerson>({
  turn,
  isPending,
  question,
  conversationId,
  onFollowUp,
  renderPeople,
  extraBeforePeople,
  getFollowUps,
  personLinkFrom = "talent-ai",
}: {
  turn: AnswerTurn<TPerson>;
  isPending?: boolean;
  question?: string;
  conversationId?: string;
  onFollowUp?: (query: string) => void;
  /** Ghi đè cách hiện "người" trong kết quả — mặc định là chip trích dẫn CV
   *  (`PeopleStrip`); Growth Radar truyền lưới/bảng thẻ khách hàng có điểm
   *  ưu tiên + nút "Tạo cơ hội". */
  renderPeople?: (people: TPerson[]) => ReactNode;
  /** Chỗ chèn nội dung riêng theo domain (VD: khối "Hệ thống hiểu câu hỏi của
   *  bạn là…" của Growth Radar) — hiện ngay sau văn bản trả lời, trước phần
   *  người/khách hàng. */
  extraBeforePeople?: ReactNode;
  /** Ghi đè gợi ý câu hỏi tiếp theo — mặc định dùng ngôn ngữ "ứng viên". */
  getFollowUps?: (turn: AnswerTurn<TPerson>, question?: string) => string[];
  /** `from` gắn vào link hồ sơ khi TÊN người được nhắc trong câu chữ tự thành
   *  liên kết (không phải chip cuối bài) — quyết định "← Quay lại" đúng trang
   *  trên Hồ sơ 360°. Growth Radar truyền `"rb"`. */
  personLinkFrom?: string;
}) {
  const [preview, setPreview] = useState<SourceRef | null>(null);
  const [showSources, setShowSources] = useState(false);
  const [showWebSources, setShowWebSources] = useState(false);
  const [copied, setCopied] = useState(false);
  const byNumber = new Map(turn.sources.map((source) => [source.n, source]));

  const handleCopy = () => {
    if (!turn.text) return;
    navigator.clipboard.writeText(turn.text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }).catch(() => undefined);
  };

  // Tên người trong câu chữ thành liên kết mở hồ sơ. Gom từ CẢ `people` lẫn
  // `sources`: ⑤ hay nhắc tên một người nó vừa trích CV mà không đưa vào danh
  // sách `people`, và đúng cái tên đó mới là chỗ người đọc muốn bấm.
  const linkablePeople = useMemo<LinkablePerson[]>(() => {
    const byId = new Map<number, LinkablePerson>();
    // `person_id`/`name` tồn tại trên cả AnswerPerson (Talent) lẫn
    // ProspectAnswerPerson (RB) — ép kiểu để dùng chung logic gắn liên kết.
    for (const person of turn.people as unknown as Array<{ person_id: number; name: string }>) {
      if (person?.name) byId.set(person.person_id, { personId: person.person_id, name: person.name });
    }
    for (const source of turn.sources) {
      if (source.name && !byId.has(source.person_id)) {
        byId.set(source.person_id, { personId: source.person_id, name: source.name });
      }
    }
    return [...byId.values()];
  }, [turn.people, turn.sources]);

  const openCitation = (n: number) => {
    const source = byNumber.get(n);
    if (source) setPreview(sourceRef(source));
  };

  return (
    <div className="answer-turn">
      {preview && (
        <SourcePreview
          source={preview}
          onClose={() => setPreview(null)}
          personLinkFrom={personLinkFrom}
        />
      )}

      {turn.revised && (
        // Nói rõ đã sửa. Âm thầm thay bài dưới mắt người đang đọc còn khó chịu
        // hơn là để nguyên câu sai.
        <div className="answer-revised muted small">
          ✎ Radar tự kiểm lại và đã viết lại câu trả lời cho đúng.
        </div>
      )}

      <CoverageSummary turn={turn} />

      {turn.text && (
        <FormattedMarkdown content={turn.text} onCitation={openCitation}
                           people={linkablePeople} peopleLinkFrom={personLinkFrom} />
      )}

      {extraBeforePeople}

      {renderPeople
        ? renderPeople(turn.people)
        : <TalentSmartCards
            people={turn.people as unknown as AnswerPerson[]}
            personLinkFrom={personLinkFrom}
            sources={turn.sources}
          />}

      {(turn.webSources?.length ?? 0) > 0 && (
        <div className="answer-sources">
          <button
            type="button"
            className="answer-sources-toggle"
            onClick={() => setShowWebSources((open) => !open)}
            aria-expanded={showWebSources}
          >
            {showWebSources ? "▾" : "▸"} <span>🌐 Nguồn trên internet</span> ({turn.webSources!.length})
          </button>
          {showWebSources && (
            <ol className="answer-sources-list">
              {turn.webSources!.map((source, index) => (
                <li key={`${source.url}-${index}`}>
                  <a href={source.url} target="_blank" rel="noopener noreferrer">
                    {source.title || source.url}
                  </a>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      {turn.sources.length > 0 && (
        <div className="answer-sources">
          <button
            type="button"
            className="answer-sources-toggle"
            onClick={() => setShowSources((open) => !open)}
          >
            {showSources ? "▾" : "▸"} {turn.sources.length} nguồn trích dẫn
          </button>
          {showSources && (
            <ol className="answer-sources-list">
              {turn.sources.map((source) => (
                <li key={`${source.n}-${source.document_id}-${source.ordinal}`}>
                  <button
                    type="button"
                    className="citation-link"
                    onClick={() => setPreview(sourceRef(source))}
                  >
                    <b>[{source.n}] {source.name}</b>{" "}
                    <span className="muted small">“{source.snippet}”</span>
                  </button>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      {/* Gợi ý các câu hỏi tiếp theo (Smart Follow-ups) khi đã có câu trả lời */}
      {!isPending && turn.text && onFollowUp && (
        <div className="answer-followup-section">
          <span className="answer-followup-title">💡 GỢI Ý CÂU HỎI TIẾP THEO:</span>
          <div className="answer-followup-chips">
            {(getFollowUps ? getFollowUps(turn, question) : getFollowUpSuggestions(turn, question)).map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                className="answer-followup-chip"
                onClick={() => onFollowUp(suggestion)}
              >
                <span className="followup-icon">💬</span>
                <span className="followup-text">{suggestion}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {!isPending && turn.text && (
        <div className="answer-footer-row">
          {(() => {
            const workflowModels = extractWorkflowModels(turn);
            if (!workflowModels.length) return null;
            return (
              <div className="answer-workflow-models" title="Các mô hình AI tham gia trong quy trình xử lý">
                <span className="workflow-models-title">🤖 Mô hình quy trình ({workflowModels.length}):</span>
                <div className="workflow-models-badges">
                  {workflowModels.map((item, idx) => (
                    <span
                      key={idx}
                      className="workflow-model-pill"
                      title={`${item.role}: ${item.provider ? `${item.provider}/` : ""}${item.model || "mặc định"}`}
                    >
                      <span className="workflow-model-icon">{item.icon}</span>
                      <span className="workflow-model-role">{item.role}:</span>
                      <code className="workflow-model-name">
                        {item.provider ? `${item.provider}/${item.model || "mặc định"}` : item.model}
                      </code>
                    </span>
                  ))}
                </div>
              </div>
            );
          })()}
          <div className="answer-footer-meta">
            <button
              type="button"
              className="answer-copy-btn"
              onClick={handleCopy}
              title="Sao chép nội dung câu trả lời"
            >
              {copied ? "✓ Đã chép" : "📋 Sao chép"}
            </button>
          </div>
          <Rating turn={turn} question={question} conversationId={conversationId} />
        </div>
      )}
    </div>
  );
}
