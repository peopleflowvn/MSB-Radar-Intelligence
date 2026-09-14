// Lớp gọi API duy nhất của giao diện Hub.
//
// Đường dẫn luôn tương đối: lúc dev Vite proxy sang Django, lúc chạy thật Caddy
// phục vụ file tĩnh và chuyển tiếp /api. Không có biến base-URL nào để đặt sai.

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// Django đòi CSRF token cho mọi yêu cầu làm thay đổi dữ liệu. Đọc từ cookie chứ
// không nhúng vào trang, để bản build tĩnh không phải do Django render ra.
function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const headers: Record<string, string> = isFormData ? {} : { "Content-Type": "application/json" };
  if (method !== "GET" && method !== "HEAD") {
    headers["X-CSRFToken"] = csrfToken();
  }
  const response = await fetch(`/api/v1${path}`, {
    credentials: "same-origin",
    ...init,
    headers: {
      ...headers,
      ...((init?.headers as Record<string, string>) ?? {}),
    },
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // Phản hồi không phải JSON (ví dụ trang lỗi của Caddy). Giữ nguyên
      // thông báo theo mã trạng thái thay vì để lỗi phân tích JSON che mất.
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export interface Summary {
  edges: number;
  edges_registered: number;
  source_records: number;
  pending_resolution: number;
  by_source: Array<{ source: string; count: number }>;
}

export interface EdgeRow {
  id: number;
  label: string;
  edge_id: string;
  hostname: string;
  app_version: string;
  is_active: boolean;
  registered_at: string | null;
  last_seen_at: string | null;
  record_count: number;
}

export interface SourceRecordRow {
  id: number;
  edge_label: string;
  edge_id?: string;
  entity_key: string;
  source: string;
  account: string;
  fullname: string;
  email: string;
  phone: string;
  position: string;
  status: string;
  revision: number;
  last_seen_at: string;
}

export type IntakeRowStatus =
  | "valid"
  | "duplicate"
  | "invalid"
  | "skipped"
  | "committed"
  | "error";

export interface IntakeRow {
  id: number;
  row_number: number;
  raw: Record<string, unknown>;
  fields: Record<string, string>;
  entity_key: string;
  validation_status: IntakeRowStatus;
  errors: Record<string, string>;
  matched_person_id: number | null;
  matched_person_name: string;
  source_record_id: number | null;
  person_id: number | null;
  cv_filename: string;
  cv_sha256: string;
  ai_extracted: boolean;
}

export interface RoleModuleCell {
  role: string;
  module: string;
  enabled: boolean;
  is_default: boolean;
  changed: boolean;
  editable: boolean;
}

export interface RoleModuleMatrix {
  roles: Array<{ key: string; label: string }>;
  modules: Array<{ key: string; label: string }>;
  cells: RoleModuleCell[];
}

export interface IntakeBatch {
  id: number;
  kind: "excel" | "bulk_cv";
  source_label: string;
  original_filename: string;
  status: "draft" | "committing" | "done" | "failed";
  row_count: number;
  valid_count: number;
  duplicate_count: number;
  invalid_count: number;
  committed_count: number;
  error_count: number;
  created_by_name: string;
  created_at: string;
  updated_at: string;
  rows: IntakeRow[] | null;
  cv_result?: {
    attached: number;
    parsed: number;
    errors: Array<{ file: string; error: string }>;
  };
  commit_result?: { committed: number };
}

export interface KeyStatus {
  label: string;
  disabled: boolean;
  available: boolean;
  cooling_seconds: number;
  uses: number;
  rate_limits: number;
}

export interface ProviderRow {
  provider: string;
  label: string;
  enabled: boolean;
  priority: number;
  api_key_hint: string;
  has_api_key: boolean;
  key_readable: boolean;
  key_count: number;
  keys: KeyStatus[];
  base_url: string;
  base_url_default: string;
  model: string;
  model_default: string;
  timeout: number;
  ready: boolean;
  last_checked_at: string | null;
  last_check_ok: boolean | null;
  last_check_detail: string;
  updated_at: string;
  updated_by: string;
}

export interface ProviderPatch {
  enabled?: boolean;
  priority?: number;
  base_url?: string;
  model?: string;
  timeout?: number;
  /** Chỉ gửi khi người dùng thật sự nhập khoá mới. Không gửi = giữ khoá cũ. */
  api_key?: string;
}

export interface EffectiveTaskConfig {
  task: string;
  provider: string;
  model: string;
  config_source: string;
  emergency_key?: string;
  emergency_model_key?: string;
  model_env_override?: string;
}

export interface TaskModelRoute {
  task: string;
  provider: string;
  model: string;
  enabled: boolean;
  updated_at?: string;
  updated_by?: string;
  effective: EffectiveTaskConfig;
}

export interface UsageModelRow {
  provider: string;
  model: string;
  calls: number;
  failed: number;
  success_rate: number | null;
  avg_latency_ms: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface UsageProviderRow {
  provider: string;
  calls: number;
  failed: number;
  success_rate: number | null;
  avg_latency_ms: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  models?: UsageModelRow[];
}

export interface UsageSummary {
  window_hours?: number;
  success_rate?: number | null;
  p50_latency_ms?: number | null;
  p95_latency_ms?: number | null;
  failure_causes?: Record<string, number>;
  total_calls: number;
  failed_calls: number;
  total_prompt_tokens?: number;
  total_completion_tokens?: number;
  total_tokens?: number;
  primary_provider?: string;
  fallback_calls?: number;
  by_provider: UsageProviderRow[];
  by_model?: UsageModelRow[];
  /** Chi phí/độ trễ theo TÁC VỤ — tức theo từng chặng. `by_model` chỉ nói nhà
   *  cung cấp nào tốn; cái này nói chặng nào tốn, và đó mới là câu dẫn tới
   *  hành động. */
  by_task?: UsageTaskRow[];
}

export interface UsageTaskRow {
  task: string;
  label: string;
  group: string;
  calls: number;
  failed: number;
  tokens: number;
  /** Tỷ lệ token của chặng này trên tổng — chặng chiếm phần lớn là chặng đáng
   *  đi tối ưu, không phải chặng chạy nhiều lượt nhất. */
  token_share: number;
  avg_latency_ms: number | null;
}

export interface TalentSummary {
  current_title: string;
  current_company: string;
  years_experience: number | null;
  seniority: string;
  location: string;
  skills: string[];
  owner_name: string;
  owner_id?: number | null;
  tags: string[];
  last_source_at: string | null;
}

export interface TalentCard {
  id: number;
  display_name: string;
  primary_email: string;
  primary_phone: string;
  headline: string;
  location: string;
  needs_review: boolean;
  talent: TalentSummary | null;
  source_count: number;
  active_worklists: ActiveWorklist[];
  updated_at: string;
}

export interface ActiveWorklist {
  hunt_id: number;
  title: string;
  state: HuntCandidateState;
  state_label: string;
  stage_color: string;
  sla_due_at: string | null;
  is_overdue: boolean;
  priority: "low" | "normal" | "high" | "urgent";
  assigned_to_id: number | null;
  assigned_to_name: string;
  next_action_at: string | null;
  note: string;
  updated_at: string;
}

export interface DocumentRow {
  id: number;
  version: number;
  filename: string;
  document_type: string;
  source: string;
  file_size: number;
  mime_type: string;
  parse_status: string;
  parsed_text?: string;
  observed_at: string | null;
  created_at: string;
  has_file: boolean;
  text_length: number;
  /** Số lượt ứng tuyển dùng chung đúng file này. */
  used_by: number;
  text_variant_count: number;
  content_group: string;
  same_content_occurrences: number;
  parse_provider: string;
  parse_model: string;
  parse_error: string;
  parsed_at: string | null;
  preview_status: string;
  preview_error: string;
  has_preview: boolean;
}

export interface DocumentStats {
  submission_count: number;
  file_version_count: number;
  distinct_text_count: number;
  duplicate_text_count: number;
  unparsed_count: number;
  ai_retry_count: number;
  preview_pending_count: number;
  text_variant_count: number;
}

export interface DocumentTextResponse {
  text: string;
  parse_status: string;
  parse_error?: string;
  /** Email/SĐT trong văn bản đã bị che vì hồ sơ chưa được mở khoá liên hệ. */
  contacts_masked?: boolean;
  versions?: Array<{
    id: number;
    text: string;
    text_length: number;
    origins: string[];
    provider: string;
    model: string;
    quality_score: number;
    created_at: string;
    is_primary: boolean;
  }>;
}

export interface TimelineEvent {
  kind: "interaction" | "signal";
  at: string;
  action: string;
  actor: string;
  detail: Record<string, unknown>;
}

export interface PersonDetail extends TalentCard {
  talent:
    | (TalentSummary & {
        education: string;
        expected_salary: string;
        industries: string[];
        summary: string;
        curated_fields: string[];
        derived_at: string | null;
      })
    | null;
  identities: Array<{ kind: string; value: string; first_seen_at: string }>;
  sources: Array<{
    id: number;
    source: string;
    account: string;
    entity_key: string;
    position: string;
    applied_ts: string;
    revision: number;
    first_seen_at: string;
    last_seen_at: string;
  }>;
  documents: DocumentRow[];
  document_stats: DocumentStats;
  timeline: TimelineEvent[];
  signals: Array<{
    id: number;
    signal_type: string;
    domain: string;
    confidence: number;
    status: string;
    observed_at: string;
  }>;
  relationships: Array<{
    domain: string;
    state: string;
    owner: string;
    owner_id: number | null;
    interest_level: number;
    last_contact_at: string | null;
    next_action: string;
    next_action_at: string | null;
    preferred_channel: string;
    do_not_contact: boolean;
    reason: string;
    notes: string;
    preferences: Record<string, string | boolean | number>;
    updated_at: string;
  }>;
  pools: Array<{
    id: number;
    name: string;
    added_at: string;
    added_by: string;
  }>;
}

/** Một lượt hỏi/đáp trước đó về CÙNG một người — gửi kèm câu hỏi mới để AI
 * hỏi tiếp có ngữ cảnh, giống `HistoryTurn` của AiSearch/Prospect nhưng ở đây
 * không có "tiêu chí", chỉ có câu hỏi và câu trả lời trước. */
export interface PersonAskTurn {
  question: string;
  answer: string;
}

export interface PersonAskResponse {
  answer: string;
  error: string;
  /** Rỗng khi AI không trả lời được (xem `error`). */
  provider: string;
  model: string;
}

export interface MatchDimension {
  key: string;
  score: number;
  weight: number;
  fact: string;
  unknown: string;
}

/** Khung giải thích theo Master Plan mục 19.3: FACT / INFERENCE / UNKNOWN / NEXT ACTION. */
export interface MatchWhy {
  facts: string[];
  unknowns: string[];
  inference: string;
  summary: string;
  next_action: string;
}

export interface SourceCitation {
  document_id: number;
  ordinal: number;
  snippet: string;
}

export interface AiTalentCard extends TalentCard {
  match: {
    score: number;
    dimensions: MatchDimension[];
    /** Đoạn CV ứng viên này khớp — bấm để xem nguyên văn nguồn (kiểu NotebookLM). */
    citations?: SourceCitation[];
    why: MatchWhy;
    insights: {
      suitable_roles: Array<{ title: string; reason: string }>;
      suitable_products: Array<{ product: string; label: string; reason: string }>;
      approach_strategy: { recruiter: string; rm: string };
    };
  };
}

/** Một lượt hỏi trước đó trong cùng cuộc trò chuyện — gửi kèm câu hỏi mới để
 * AI hỏi tiếp (refine) thay vì hỏi độc lập từ đầu. Chỉ cần tiêu chí đã hiểu
 * được của lượt đó; tối đa 8 lượt gần nhất được backend giữ lại. */
export interface HistoryTurn {
  criteria: Record<string, unknown>;
  question?: string;
  answer?: string;
}

export interface AiSearchResponse {
  stage?: "quick" | "deep";
  mode?: "search" | "conversation";
  answer?: string;
  question: string;
  /** Tiêu chí AI hiểu được — hiện ra để người dùng SỬA, không phải viết lại câu hỏi. */
  criteria: Record<string, unknown>;
  provider: string;
  model: string;
  explain_provider?: string;
  explain_model?: string;
  analysis_id: number;
  cache_hit: boolean;
  analyzed_at: string | null;
  analysis_version: number;
  attachments: Array<{ name: string; size: number; characters: number }>;
  trace: Array<{ label: string; detail: string }>;
  count: number;
  results: AiTalentCard[];
  conversation_id?: string;
  conversation_summary?: string;
  reasoning_content?: string;
  thinking_trace?: string;
  /** Nguồn web khi Radar tra Google để trả lời (mode=conversation). */
  sources?: WebSource[];
  /** Trích dẫn từ CV khi Radar trả lời có dẫn chứng trên kho (mode=conversation, grounded). */
  citations?: CvCitation[];
  /** true khi câu trả lời được neo vào các đoạn CV truy hồi được (kiểu NotebookLM). */
  grounded?: boolean;
  /** Nhãn ý định server phân loại: "search" | "conversation" | "web" | "corpus". */
  intent?: string;
  /** Các tool Radar đã gọi trong lượt (khi ASSISTANT_TOOLS bật). */
  tools?: ToolCallTrace[];
}

export interface WebSource {
  title: string;
  url: string;
}

export interface CvCitation {
  n: number;
  person_id: number;
  name: string;
  document_id: number;
  snippet: string;
}

export interface EmbeddingConfig {
  mode: "greennode" | "selfhost" | "gemini" | "off";
  mode_choices: Array<{ value: string; label: string }>;
  selfhost_base_url: string;
  selfhost_model: string;
  gemini_model: string;
  greennode_model: string;
  dimensions: number;
  updated_at?: string;
  updated_by?: string;
  active: boolean;
  effective: { provider: string; model: string } | null;
  gemini_key_present: boolean;
  greennode_key_present: boolean;
  coverage: {
    projections: number;
    projections_embedded: number;
    chunks: number;
    chunks_embedded: number;
  };
  probe?: { ok: boolean; model: string; dims: number | null };
  needs_rebackfill?: boolean;
}

export interface AssistantConversationMessage {
  id: number;
  role: "user" | "assistant" | "system";
  content: string;
  metadata: Record<string, unknown>;
  provider: string;
  model: string;
  created_at: string;
}

export interface AssistantConversation {
  id: number;
  conversation_id: string;
  surface: "talent" | "prospect";
  title: string;
  archived: boolean;
  summary: string;
  state: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  last_message_at: string | null;
  messages?: AssistantConversationMessage[];
}

export interface AssistantPreference {
  gender: "" | "male" | "female" | "other" | "undisclosed";
  preferred_name: string;
  preferred_salutation: "" | "anh" | "chị" | "bạn";
  personalization_enabled: boolean;
  display_address: string;
}

export type MemoryScope = "profile" | "operational";
export type MemoryStatus = "active" | "pending_review" | "rejected";

export interface MemoryRow {
  id: number;
  scope: MemoryScope;
  kind: "preference" | "fact";
  status: MemoryStatus;
  key: string;
  value: string;
  source: string;
  version: number;
  surface: string;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MemoryListResponse {
  results: MemoryRow[];
  quota: Record<MemoryScope, number>;
  pending: number;
}

export interface HistorySearchHit {
  message_id: number;
  role: string;
  snippet: string;
  conversation_id: string;
  surface: string;
  title: string;
  created_at: string;
}

export interface IntelFact {
  id: number;
  field: string;
  status: string;
  raw_value: string;
  normalized_value: string;
  canonical_code: string;
  canonical_label: string;
  confidence: number;
  source_kind: string;
  source_record_id: number | null;
  document_id: number | null;
  evidence: string;
  extractor: string;
  model: string;
  schema_version: number;
  observed_at: string | null;
  valid_from: string | null;
  valid_to: string | null;
  is_current: boolean;
}

export interface IntelPersonFacts {
  person_id: number;
  fields: Record<string, IntelFact[]>;
  current: Record<string, IntelFact>;
}

export interface IntelRun {
  id: number;
  status: string;
  extractor: string;
  provider: string;
  model: string;
  dry_run: boolean;
  coverage: Record<string, number | boolean>;
  error: string;
  started_at: string;
  finished_at: string | null;
}

export interface IntelReviewItem {
  id: number;
  reason: string;
  detail: string;
  person_id: number | null;
  field: string;
  fact: IntelFact | null;
  alias: { id: number; namespace: string; alias_norm: string } | null;
  created_at: string;
}

export interface IntelReviewResponse {
  counts: Record<string, number>;
  results: IntelReviewItem[];
}

export interface IntelAlias {
  id: number;
  namespace: string;
  alias_norm: string;
  alias_raw: string;
  source: string;
  created_by: string;
  created_at: string;
}

export interface IntelRunsDashboard {
  totals: {
    runs: number;
    by_status: Record<string, number>;
    open_reviews: number;
    proposed_aliases: number;
    accepted_facts: number;
  };
  coverage_last_500: Record<string, number | null>;
  recent: { id: number; person_id: number; status: string; coverage: Record<string, number | boolean>; started_at: string }[];
}

export interface HiringNeedRow {
  id: number;
  title: string;
  department: string;
  jd_text: string;
  criteria: Record<string, unknown>;
  /** true = tiêu chí do dò từ khoá vì LLM bận, không phải AI đọc JD. */
  criteria_fallback: boolean;
  status: string;
  owner_name: string;
  is_calibrated: boolean;
  calibrated_at: string | null;
  learned_weights: Record<string, number>;
  counts: {
    suggested: number;
    good_fit: number;
    not_fit: number;
    shortlisted: number;
    total: number;
    open_hunts: number;
  };
  created_at: string;
  updated_at: string;
}

export interface Candidacy {
  id: number;
  state: "suggested" | "good_fit" | "not_fit" | "shortlisted";
  score_snapshot: number;
  note: string;
  marked_by_name: string;
  marked_at: string | null;
}

export interface SuggestionRow extends TalentCard {
  candidacy: Candidacy;
  match: {
    score: number;
    dimensions: MatchDimension[];
    facts: string[];
    unknowns: string[];
  };
}

export interface CalibrationResult {
  weights: Record<string, number>;
  insights: string[];
  good_count: number;
  bad_count: number;
  applied: boolean;
}

export type HuntCandidateState =
  | "pending"
  | "contacting"
  | "responded"
  | "interested"
  | "not_interested"
  | "unreachable"
  | "submitted"
  | "returned";

export interface HuntCandidateRow {
  person_id: number;
  display_name: string;
  headline: string;
  primary_email: string;
  primary_phone: string;
  state: HuntCandidateState;
  state_label: string;
  stage_color: string;
  sla_due_at: string | null;
  is_overdue: boolean;
  note: string;
  priority: "low" | "normal" | "high" | "urgent";
  next_action_at: string | null;
  assigned_to: number | null;
  assigned_to_name: string;
  status_events: Array<{
    from_state: string;
    to_state: string;
    actor_name: string;
    note: string;
    created_at: string;
  }>;
  return_reason: string;
  outreach_draft: string;
  outreach_sent_at: string | null;
  updated_at: string;
}

export interface HuntRequestRow {
  id: number;
  title: string;
  hiring_need: number | null;
  hiring_need_title: string;
  people: HuntCandidateRow[];
  progress: { total: number; closed: number; submitted: number };
  visible_count: number;
  message: string;
  status: string;
  priority: "low" | "normal" | "high" | "urgent";
  requested_by_name: string;
  assigned_to_name: string;
  decline_reason: string;
  created_at: string;
}

export interface SocialIntent {
  /** Đa nhãn: {"talent": 0.91, "rb": 0.07}. Không cần cộng lại bằng 1. */
  scores: Record<string, number>;
  reason: string;
  contacts: Record<string, string>;
  role: string;
  location: string;
  /** true = chấm bằng dò từ khoá vì không gọi được LLM. */
  fallback: boolean;
  error: string;
}

export interface AnalyzeResult {
  saved: boolean;
  intent: SocialIntent;
  matched_person: number | null;
  matched_person_name: string;
  history_note: string;
}

export interface SocialPostRow {
  id: number;
  provider: string;
  community_name: string;
  author_name: string;
  author_url: string;
  content: string;
  url: string;
  posted_at: string | null;
  intent: Record<string, number>;
  intent_reason: string;
  intent_fallback: boolean;
  contacts: Record<string, string>;
  person: number | null;
  person_name: string;
  history_note: string;
  top_domain: string | null;
  status: string;
  created_at: string;
}

export interface RBOpportunityRow {
  id: number;
  person: number;
  display_name: string;
  primary_phone: string;
  primary_email: string;
  product: string;
  product_label: string;
  /** Nhu cầu nói bằng lời của khách, không phải tên sản phẩm. */
  need: string;
  confidence: number;
  evidence: Record<string, unknown>;
  suggested_action: string;
  status: string;
  status_label: string;
  stage_color: string;
  sla_due_at: string | null;
  is_overdue: boolean;
  assigned_to: number | null;
  assigned_to_name: string;
  priority: "low" | "normal" | "high" | "urgent";
  next_action_at: string | null;
  note: string;
  status_events: Array<{
    from_status: string;
    to_status: string;
    actor_name: string;
    note: string;
    created_at: string;
  }>;
  close_reason: string;
  outreach_draft: string;
  outreach_sent_at: string | null;
  other_active_owners: string[];
  stage_entered_at: string;
  created_at: string;
}

export interface RBCustomerTaskRow {
  kind: "work" | "relationship";
  key: string;
  person_id: number;
  display_name: string;
  headline: string;
  primary_phone: string;
  primary_email: string;
  opportunity: RBOpportunityRow | null;
  other_opportunities: RBOpportunityRow[];
  relationship: {
    id: number | null;
    state: string;
    owner: string;
    owner_id: number | null;
    interest_level: number;
    next_action: string;
    next_action_at: string | null;
    do_not_contact: boolean;
  };
  due_at: string | null;
  is_overdue: boolean;
  relationship_due: boolean;
}

/** Thẻ "Cơ hội hôm nay" — Radar đề xuất, RM quyết định. */
export interface OpportunitySuggestionRow {
  id: number;
  person: number;
  person_name: string;
  occupation: string;
  product: string;
  product_label: string;
  /** Nhu cầu nói bằng lời của khách, không phải tên sản phẩm. */
  need_summary: string;
  /** VÌ SAO BÂY GIỜ — lý do tất định của cả 5 chiều điểm. */
  why: string[];
  /** Điểm khách quan. Không đổi theo người đang xem. */
  priority_score: number;
  /**
   * Điểm sau khi tính địa bàn/trọng tâm của người đang xem.
   * Bằng `priority_score` khi người dùng chưa khai báo gì.
   */
  personalized_score: number;
  personalized_why: string[];
  /** in · out · unknown — "chưa rõ khu vực" KHÁC "nằm ngoài địa bàn". */
  territory: "in" | "out" | "unknown";
  /** RM phụ trách khu vực này, khi khách nằm ngoài địa bàn. Gợi ý, không tự chuyển. */
  handoff_to: { user_id: number; name: string; region: string } | null;
  /** Nằm trong suất khám phá: ngoài khai báo nhưng điểm khách quan cao. */
  is_discovery: boolean;
  confidence: number;
  value_band: "low" | "medium" | "high" | "very_high";
  recommended_action: string;
  action_label: string;
  reasoning_summary: string;
  scores: {
    fit: number;
    need: number;
    timing: number;
    reachability: number;
    value: number;
  };
  status: string;
  status_label: string;
  snoozed_until: string | null;
  created_at: string;
  expires_at: string | null;
}

/** Nang luc thu thap va hop nhat (Master Plan muc 9). */
export interface CaptureStats {
  providers: Array<{
    source: string;
    label: string;
    records: number;
    people: number;
    new_today: number;
    pending: number;
    connected: boolean;
  }>;
  consolidation: {
    source_records: number;
    unique_people: number;
    pending: number;
    /** So nguoi da duoc chung minh la CUNG MOT NGUOI du den tu nhieu nen tang. */
    multi_source_people: number;
    max_sources_for_one_person: number;
    /** `null` khi kho con rong — khong phai 0. */
    records_per_person: number | null;
  };
  parsing: {
    documents: number;
    parsed: number;
    failed: number;
    /** `null` khi chua co tai lieu nao — khac han voi "boc tach hong". */
    success_rate: number | null;
    stored: number;
  };
}

/** Tim prospect bang ngon ngu tu nhien (Master Plan muc 16). */
/** Khoa API cua mot Edge — KHONG BAO GIO co truong khoa tho ngoai luc cap. */
export interface EdgeApiKeyRow {
  id: number;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  is_active: boolean;
}

export interface EdgeAdminRow {
  id: number;
  label: string;
  edge_id: string;
  hostname: string;
  app_version: string;
  is_active: boolean;
  registered_at: string | null;
  last_seen_at: string | null;
  created_at: string;
  api_keys: EdgeApiKeyRow[];
  record_count: number;
}

/** Chi xuat hien DUNG MOT LAN, trong chinh phan hoi cap khoa. */
export interface IssuedKeyRow extends EdgeApiKeyRow {
  api_key: string;
}

export interface ProspectCriteria {
  location: string;
  seniority: string;
  products: string[];
  segment: string;
  require_contact: boolean;
  exclude_open_opportunity: boolean;
  limit: number;
  signal_recency_days: number;
}

export interface ProspectRow {
  person_id: number;
  display_name: string;
  location: string;
  occupation: string;
  product: string;
  priority_score: number;
  scores: {
    fit: number;
    need: number;
    timing: number;
    reachability: number;
    value: number;
  };
  why: string[];
  has_open_opportunity: boolean;
}

export interface ProspectResponse {
  mode?: "search" | "conversation";
  answer?: string;
  question: string;
  criteria: ProspectCriteria;
  /** agent (chay tren AgentBase) · llm (tai Hub) · keyword (tat dinh). */
  criteria_from: "agent" | "llm" | "keyword";
  error: string;
  count: number;
  results: ProspectRow[];
  /** Rong khi criteria_from = "keyword" — khong mo hinh nao tham gia. */
  provider?: string;
  model?: string;
  conversation_id?: string;
  conversation_summary?: string;
  reasoning_content?: string;
  thinking_trace?: string;
  sources?: WebSource[];
  intent?: string;
  tools?: ToolCallTrace[];
  trace?: Array<{ label: string; detail: string }>;
}

export interface ContactUnlockResult {
  primary_email: string;
  primary_phone: string;
  /** Con lai hom nay. `null` = khong gioi han. */
  remaining: number | null;
  /** `false` khi da mo khoa nguoi nay trong ngay — khong tru them luot. */
  charged: boolean;
}

export interface ContactQuota {
  limit: number | null;
  used: number;
  remaining: number | null;
}

export interface TodaysOpportunitiesResponse {
  summary: {
    total: number;
    high_priority: number;
    strong_product_fit: number;
    call_now: number;
    reactivation: number;
    fresh_signals: number;
  };
  results: OpportunitySuggestionRow[];
}

/** Khai báo địa bàn/trọng tâm của chính người đăng nhập. */
export interface WorkProfileRow {
  id: number;
  domain: string;
  domain_label: string;
  regions: string[];
  focus_products: string[];
  focus_job_families: string[];
  target_segments: string[];
  daily_capacity: number;
  preferred_channels: string[];
  notes: string;
  active: boolean;
  updated_at: string;
  /**
   * Thứ hệ thống SUY RA từ việc đã làm, để điền sẵn vào form.
   * Tách riêng khỏi khai báo thật: người dùng phải phân biệt được
   * đâu là mình khai, đâu là máy đoán.
   */
  observed: {
    regions: string[];
    focus_products: string[];
    sample_size: number;
    confident: boolean;
  };
}

export interface OpportunityOutcomeRow {
  id: number;
  opportunity: number;
  person: number;
  channel: string;
  channel_label: string;
  action: string;
  outcome: string;
  outcome_label: string;
  note: string;
  response_at: string;
  created_by_name: string;
  created_at: string;
}

export interface RBCustomerTaskResponse {
  count: number;
  summary: { active: number; overdue: number; today: number; unassigned: number };
  results: RBCustomerTaskRow[];
}

export interface ProductSuggestion {
  product: string;
  product_label: string;
  confidence: number;
  need: string;
  matched: string[];
}

export interface Metric {
  /** null = chưa đủ dữ liệu. KHÁC 0, và giao diện phải phân biệt được hai thứ. */
  value: number | null;
  label: string;
  detail: string;
  unit: string;
}

export interface MetricsResponse {
  metrics: Record<string, Metric>;
  stale_days: number;
}

export interface RBMetricsResponse {
  metrics: Record<string, Metric>;
}

export interface OverviewResponse {
  capture: CaptureStats;
  sync: {
    edges: number;
    edges_registered: number;
    source_records: number;
    pending_resolution: number;
  };
  ai_usage: {
    total_calls: number;
    failed_calls: number;
    by_provider: Array<{ provider: string; calls: number }>;
  };
  agents: {
    total_runs: number;
    error_rate: number | null;
    median_ms: number | null;
    by_agent: Array<{ agent: string; runs: number }>;
  };
  talent: Record<string, Metric>;
  rb: Record<string, Metric>;
}

export interface SavedView {
  id: number;
  module: "talent" | "rb";
  module_label: string;
  name: string;
  filters: Record<string, unknown>;
  created_at: string;
  last_used_at: string | null;
}

export interface FilterHistoryRow {
  id: number;
  module: "talent" | "rb";
  filters: SearchFilters;
  used_at: string;
}

export interface SearchFilters {
  q?: string;
  skills?: string;
  location?: string;
  title?: string;
  company?: string;
  desired_location?: string;
  seniority?: string;
  education?: string;
  job_type?: string;
  foreign_language?: string;
  source?: string;
  relationship?: string;
  product?: string;
  lead_status?: string;
  open_opportunity?: string;
  tags?: string;
  pool?: string;
  owner?: string;
  min_years?: string;
  max_years?: string;
  has_email?: boolean;
  has_phone?: boolean;
  order?: string;
}

export interface HuntTaskRow {
  kind: "work" | "relationship";
  key: string;
  person_id: number;
  display_name: string;
  headline: string;
  hunt: { id: number; title: string; message: string; status: string } | null;
  candidate: HuntCandidateRow | null;
  relationship: {
    state: string;
    owner: string;
    owner_id: number | null;
    interest_level: number;
    next_action: string;
    next_action_at: string | null;
    do_not_contact: boolean;
  };
  other_active_worklists: Array<{
    hunt_id: number;
    title: string;
    state: string;
    state_label: string;
    assigned_to_name: string;
  }>;
  due_at: string | null;
  is_overdue: boolean;
  relationship_due: boolean;
}

export interface HuntTaskResponse {
  count: number;
  summary: {
    active: number;
    overdue: number;
    today: number;
    unassigned: number;
  };
  results: HuntTaskRow[];
}

export interface WorkflowStage {
  id: number;
  domain: "talent" | "rb";
  code: string;
  label: string;
  color: string;
  position: number;
  is_terminal: boolean;
  requires_reason: boolean;
  sla_hours: number | null;
  is_active: boolean;
  allowed_next: string[];
}

export interface RBProfileRow {
  id: number;
  person: number;
  display_name: string;
  primary_email: string;
  primary_phone: string;
  sales_owner_name: string;
  lead_status: string;
  lead_status_label: string;
  segment: string;
  occupation: string;
  employer: string;
  interaction_summary: string;
  last_contact_at: string | null;
  next_action: string;
  next_action_at: string | null;
  interests: Array<{
    id: number;
    product: string;
    product_label: string;
    confidence: number;
    evidence: Record<string, unknown>;
    source: string;
    observed_at: string;
  }>;
  open_opportunities: Array<{
    id: number;
    product: string;
    product_label: string;
    status: string;
    assigned_to_name: string;
    next_action_at: string | null;
  }>;
  active_owners: string[];
  interest_level: number;
  preferred_channel: string;
  do_not_contact: boolean;
  relationship_reason: string;
  relationship_notes: string;
  updated_at: string;
}

export interface TalentFacets {
  by_source: Array<{ source: string; count: number }>;
  by_location: Array<{ talent_profile__location: string; count: number }>;
  tags: Array<{ slug: string; name: string; count: number }>;
  pools: Array<{
    id: number;
    name: string;
    domain: "talent" | "rb";
    member_count: number;
  }>;
  owners: Array<{ id: number; name: string }>;
  relationships: Array<{ value: string; label: string }>;
  products: Array<{ value: string; label: string }>;
  lead_statuses: Array<{ value: string; label: string }>;
}

export interface UserRow {
  id: number;
  username: string;
  full_name: string;
  is_active: boolean;
  is_superuser: boolean;
  roles: string[];
  role_labels: string[];
  date_joined: string;
  last_login: string | null;
  login_type: LoginType;
}

// Backend LƯU một trong local/tntalent/msb; form CHỌN chỉ local hoặc otp
// (realm tntalent/msb do domain ở tab Email OTP quyết định).
export type LoginType = "local" | "tntalent" | "msb";
export type LoginTypeChoice = "local" | "otp";

export interface UserCreate {
  username: string;
  password: string;
  full_name?: string;
  roles?: string[];
  login_type: LoginTypeChoice;
}

export interface UserPatch {
  full_name?: string;
  is_active?: boolean;
  password?: string;
  roles?: string[];
  login_type?: LoginTypeChoice;
}

export interface UserBulkResultRow {
  row: number;
  username: string;
  full_name?: string;
  status: "created" | "rejected";
  detail?: string;
  password?: string;
  roles?: string[];
  login_type?: LoginType;
}

export interface UserBulkResult {
  created: number;
  total: number;
  results: UserBulkResultRow[];
}

export interface AccessLogRow {
  id: number;
  at: string;
  user: string;
  roles: string;
  action: string;
  module: string;
  person: number | null;
  person_name: string;
  cross_domain: boolean;
  allowed: boolean;
  exfiltration: boolean;
  path: string;
  ip: string;
  extra: Record<string, unknown>;
}

export interface AccessLogSummary {
  total: number;
  cross_domain: number;
  denied: number;
  exfiltration: number;
  by_user: Array<{ user_name: string; n: number; cross: number }>;
  by_action: Array<{ action: string; n: number }>;
}

export interface Identity {
  id: number;
  username: string;
  full_name: string;
  is_superuser: boolean;
  roles: string[];
  role_labels: string[];
  /** Module người này vào được. Chỉ để ẩn/hiện tab — chặn thật ở máy chủ. */
  modules: string[];
}

export type Session =
  { authenticated: false } | ({ authenticated: true } & Identity);

export interface LoginOptions {
  local_login_enabled: boolean;
  email_otp: { tntalent: boolean; msb: boolean };
  email_otp_domains: { tntalent: string[]; msb: string[] };
}

export interface DatabaseBackupRow {
  id: number;
  filename: string;
  storage_key: string;
  storage_backend: string;
  size_bytes: number;
  sha256: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed';
  error_message: string;
  trigger_type: 'scheduled' | 'manual';
  created_by: string;
  duration_ms: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface DatabaseBackupSummary {
  total_backups: number;
  completed_backups: number;
  total_size_bytes: number;
  storage_backend: string;
  r2_bucket: string;
  r2_configured: boolean;
  schedule: string;
  retention_days: number;
  latest_backup: DatabaseBackupRow | null;
}

export interface DatabaseBackupListResponse {
  summary: DatabaseBackupSummary;
  results: DatabaseBackupRow[];
}

export interface EmailOtpTestSendResult {
  success: boolean;
  recipient: string;
  test_code: string;
  resend_id: string;
  sender: string;
  subject: string;
  duration_ms: number;
  message: string;
}

export interface EmailOtpSettings {
  enabled: boolean;
  api_key_configured: boolean;
  from_email: string;
  from_name: string;
  reply_to: string;
  subject: string;
  otp_html_template: string;
  app_logo_url: string;
  app_icon: string;
  app_tagline: string;
  allowed_domains?: string[];
  domains?: string;
  tntalent_domains: string[];
  msb_domains: string[];
  code_ttl_seconds: number;
  resend_cooldown_seconds: number;
  max_attempts: number;
  is_ready: boolean;
  webhook_secret_configured: boolean;
  webhook_inbound_enabled: boolean;
  webhook_url: string;
  updated_at: string | null;
  updated_by: string;
}

export type AssistantStreamEventName =
  "status" | "thinking" | "answer" | "guard" | "error" | "done" | "route"
  | "sources" | "citations" | "tool";

export interface ToolCallTrace {
  name: string;
  ok: boolean;
  summary?: string;
  error?: string;
}

export interface AssistantStreamEvent {
  event: AssistantStreamEventName;
  data: Record<string, unknown>;
}

// SSE cho luồng Thinking. Dùng fetch + ReadableStream vì EventSource không POST
// được. Trả async iterator các sự kiện đã tách event/data.
export async function* assistantStream(body: {
  q: string;
  surface?: "talent" | "prospect";
  conversation_id?: string;
  client_turn_id?: string;
  history?: HistoryTurn[];
}, signal?: AbortSignal): AsyncGenerator<AssistantStreamEvent> {
  const response = await fetch("/api/v1/ai/assistant/stream/", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) {
    let detail = `HTTP ${response.status}`;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* giữ thông báo theo mã trạng thái */
    }
    throw new ApiError(response.status, detail);
  }
  yield* readSse<AssistantStreamEvent>(response);
}

/** Tách khung SSE `event:`/`data:` từ một Response đang stream. */
async function* readSse<T extends { event: string; data: Record<string, unknown> }>(
  response: Response,
): AsyncGenerator<T> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      let ev = "message";
      let dataStr = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) ev = line.slice(6).trim();
        else if (line.startsWith("data:")) dataStr += line.slice(5).trim();
      }
      if (!dataStr) continue;
      try {
        yield { event: ev, data: JSON.parse(dataStr) } as T;
      } catch {
        /* bỏ qua frame hỏng */
      }
    }
  }
}

/** Một trích dẫn đã được máy chủ ĐỐI CHIẾU với văn bản CV gốc, không phải model tự khai. */
export interface AnswerSource {
  n: number;
  person_id: number;
  name: string;
  document_id: number;
  ordinal: number;
  snippet: string;
}

/** Người được nhắc trong câu trả lời. Chỉ đủ để mở hồ sơ — KHÔNG phải thẻ ứng viên. */
export interface AnswerPerson {
  person_id: number;
  name: string;
  why: string;
  attributes: Record<string, string | number>;
  citations: number[];
}

export interface AnswerPayload {
  conversation_id: string;
  client_turn_id: string;
  answer: string;
  reasoning: string;
  citations: AnswerSource[];
  /** Liên kết ngoài khi Radar tra internet. Khác `citations` về bản chất. */
  web_sources?: Array<{ title?: string; url: string }>;
  people: AnswerPerson[];
  provider: string;
  model: string;
  trace: Record<string, unknown>;
  grounded: boolean;
}

export type AnswerStreamEventName =
  "preamble" | "step" | "stage" | "thinking" | "answer" | "revision" | "citations" | "error" | "done";

export interface AnswerStreamEvent {
  event: AnswerStreamEventName;
  data: Record<string, unknown>;
}

/** Answer Engine — đường trả lời duy nhất cho câu hỏi về Kho con người. */
export async function* talentAsk(body: {
  q: string;
  conversation_id?: string;
  client_turn_id?: string;
  history?: HistoryTurn[];
  files?: File[];
}, signal?: AbortSignal): AsyncGenerator<AnswerStreamEvent> {
  const { files, ...fields } = body;
  // Có tệp đính kèm thì gửi multipart; máy chủ bóc văn bản rồi ghép vào câu hỏi.
  let payload: BodyInit;
  const headers: Record<string, string> = { "X-CSRFToken": csrfToken() };
  if (files && files.length > 0) {
    const form = new FormData();
    Object.entries(fields).forEach(([key, value]) => {
      if (value !== undefined) {
        form.append(key, typeof value === "string" ? value : JSON.stringify(value));
      }
    });
    files.forEach((file) => form.append("files", file));
    payload = form;      // KHÔNG tự đặt Content-Type: trình duyệt phải chèn boundary
  } else {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(fields);
  }
  const response = await fetch("/api/v1/talent/ask/", {
    method: "POST",
    credentials: "same-origin",
    headers,
    body: payload,
    signal,
  });
  if (!response.ok || !response.body) {
    let detail = `HTTP ${response.status}`;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* giữ thông báo theo mã trạng thái */
    }
    throw new ApiError(response.status, detail);
  }
  yield* readSse<AnswerStreamEvent>(response);
}

/** Lấy lại kết quả một lượt theo `client_turn_id` — khi mobile rớt kết nối
 *  giữa lúc chờ. `state: "done"` kèm câu trả lời đầy đủ; `"running"` nếu máy chủ
 *  còn đang xử lý; ném lỗi (404) nếu không có gì. */
export interface TalentTurnResult {
  state: "done" | "running";
  conversation_id?: string;
  client_turn_id?: string;
  answer?: string;
  citations?: AnswerSource[];
  people?: AnswerPerson[];
  provider?: string;
  model?: string;
  trace?: Record<string, unknown>;
  duration_ms?: number;
}

export async function talentAskTurn(clientTurnId: string): Promise<TalentTurnResult> {
  const res = await fetch(`/api/v1/talent/ask/turn/${encodeURIComponent(clientTurnId)}/`, {
    credentials: "same-origin",
    headers: { "X-CSRFToken": csrfToken() },
  });
  if (res.status === 202) return { state: "running" };
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
  return (await res.json()) as TalentTurnResult;
}

export const api = {
  assistantStream,
  talentAsk,
  talentAskTurn,
  /** Đánh giá một câu trả lời. Không có tín hiệu này thì không có cách nào biết
   *  chất lượng đang lên hay xuống. */
  aiFeedback: (body: {
    rating: "up" | "down";
    conversation_id?: string;
    question?: string;
    answer?: string;
    reason?: string;
  }) => request<{ ok: boolean }>("/ai/feedback/", {
    method: "POST", body: JSON.stringify(body),
  }),
  me: () => request<Session>("/auth/me/"),
  assistantPreference: () => request<AssistantPreference>("/auth/assistant-preference/"),
  assistantPreferenceSave: (patch: Partial<AssistantPreference>) =>
    request<AssistantPreference>("/auth/assistant-preference/", {
      method: "PATCH", body: JSON.stringify(patch),
    }),
  conversations: (surface: "talent" | "prospect") =>
    request<{ results: AssistantConversation[] }>(`/ai/conversations/?surface=${surface}`),
  // surface đi kèm để phân biệt hai hội thoại talent/prospect cùng conversation_id.
  conversation: (conversationId: string, surface?: "talent" | "prospect") =>
    request<AssistantConversation>(
      `/ai/conversations/${encodeURIComponent(conversationId)}/${surface ? `?surface=${surface}` : ""}`),
  conversationCreate: (surface: "talent" | "prospect", conversationId?: string) =>
    request<AssistantConversation>("/ai/conversations/", {
      method: "POST", body: JSON.stringify({ surface, conversation_id: conversationId }),
    }),
  conversationUpdate: (conversationId: string,
    patch: { title?: string; archived?: boolean; surface?: "talent" | "prospect" }) =>
    request<AssistantConversation>(`/ai/conversations/${encodeURIComponent(conversationId)}/`, {
      method: "PATCH", body: JSON.stringify(patch),
    }),

  // --- Long-term memory (Master Plan §11.2, §15 GĐ5) ---
  memoryList: (params?: { scope?: MemoryScope; status?: MemoryStatus }) => {
    const qs = new URLSearchParams(params as Record<string, string>).toString();
    return request<MemoryListResponse>(`/ai/memory/${qs ? `?${qs}` : ""}`);
  },
  memoryCreate: (body: { scope?: MemoryScope; kind?: "preference" | "fact"; value: string; key?: string; surface?: string }) =>
    request<MemoryRow>("/ai/memory/", { method: "POST", body: JSON.stringify(body) }),
  memoryUpdate: (id: number, patch: { value?: string; key?: string; status?: "active" | "rejected" }) =>
    request<MemoryRow>(`/ai/memory/${id}/`, { method: "PATCH", body: JSON.stringify(patch) }),
  memoryDelete: (id: number) => request<void>(`/ai/memory/${id}/`, { method: "DELETE" }),
  searchHistory: (q: string, surface?: "talent" | "prospect") =>
    request<{ results: HistorySearchHit[] }>(
      `/ai/search-history/?q=${encodeURIComponent(q)}${surface ? `&surface=${surface}` : ""}`),

  // --- People Intelligence: facts / review / aliases / runs (§5, §21) ---
  intelPersonFacts: (personId: number, status?: string) =>
    request<IntelPersonFacts>(
      `/intel/people/${personId}/facts/${status ? `?status=${status}` : ""}`),
  intelPersonRuns: (personId: number) =>
    request<{ results: IntelRun[] }>(`/intel/people/${personId}/runs/`),
  intelReviewQueue: (reason?: string) =>
    request<IntelReviewResponse>(`/intel/review/${reason ? `?reason=${reason}` : ""}`),
  intelReviewResolve: (itemId: number, decision: "accept" | "reject") =>
    request<{ ok: boolean; status: string }>(`/intel/review/${itemId}/`, {
      method: "POST", body: JSON.stringify({ decision }),
    }),
  intelAliasQueue: (namespace?: string) =>
    request<{ results: IntelAlias[] }>(`/intel/aliases/${namespace ? `?namespace=${namespace}` : ""}`),
  intelAliasResolve: (aliasId: number, decision: "accept" | "reject", entryCode?: string, note?: string) =>
    request<{ ok: boolean; status: string; entry_code: string }>(`/intel/aliases/${aliasId}/`, {
      method: "POST", body: JSON.stringify({ decision, entry_code: entryCode, note }),
    }),
  intelRunsDashboard: () => request<IntelRunsDashboard>("/intel/runs/"),

  loginOptions: () => request<LoginOptions>("/auth/login-options/"),
  loginDiscovery: (identifier: string) => request<{ mode: 'local' | 'otp'; realm?: 'tntalent' | 'msb' }>("/auth/login-discovery/", {
    method: "POST", body: JSON.stringify({ identifier }),
  }),
  emailOtpRequest: (realm: "tntalent" | "msb", identifier: string) =>
    request<{ detail: string }>(`/auth/email-otp/${realm}/request/`, {
      method: "POST", body: JSON.stringify({ identifier }),
    }),
  emailOtpVerify: (realm: "tntalent" | "msb", identifier: string, code: string) =>
    request<Identity>(`/auth/email-otp/${realm}/verify/`, {
      method: "POST", body: JSON.stringify({ identifier, code }),
    }),
  localPasswordResetRequest: (identifier: string) =>
    request<{ detail: string }>("/auth/local/reset-password/request/", {
      method: "POST", body: JSON.stringify({ identifier }),
    }),
  localPasswordResetConfirm: (identifier: string, code: string, password: string) =>
    request<{ detail: string }>("/auth/local/reset-password/confirm/", {
      method: "POST", body: JSON.stringify({ identifier, code, password }),
    }),
  login: (username: string, password: string) =>
    request<Identity>("/auth/login/", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<{ ok: boolean }>("/auth/logout/", { method: "POST" }),

  /** Ma tran phan quyen module theo vai tro — Admin phu len mac dinh trong code. */
  roleModuleMatrix: () =>
    request<RoleModuleMatrix>("/auth/role-modules/"),
  roleModuleSet: (role: string, module: string, enabled: boolean) =>
    request<RoleModuleMatrix>("/auth/role-modules/", {
      method: "POST",
      body: JSON.stringify({ role, module, enabled }),
    }),

  summary: () => request<Summary>("/hub/summary/"),
  edges: () => request<{ results: EdgeRow[] }>("/hub/edges/"),

  /**
   * Mat CRUD day du cho trang "Ket noi Edge" — tach khoi \`edges()\` o tren.
   * \`hub/edges/\` la bang tom tat cho Dashboard van hanh, nhieu noi dang phu
   * thuoc dung khuon cu; doi no de nhet them khoa vao se pha man hinh cu.
   */
  edgeAdminList: () =>
    request<{ results: EdgeAdminRow[] }>("/edge-admin/edges/"),
  edgeAdminCreate: (label: string) =>
    request<EdgeAdminRow>("/edge-admin/edges/", {
      method: "POST",
      body: JSON.stringify({ label }),
    }),
  edgeAdminUpdate: (edgeId: number, patch: { label?: string; is_active?: boolean }) =>
    request<EdgeAdminRow>(`/edge-admin/edges/${edgeId}/`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  edgeAdminDelete: (edgeId: number) =>
    request<{ deleted: boolean }>(`/edge-admin/edges/${edgeId}/`, { method: "DELETE" }),
  edgeAdminIssueKey: (edgeId: number, name: string) =>
    request<IssuedKeyRow>(`/edge-admin/edges/${edgeId}/keys/`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  edgeAdminRevokeKey: (keyId: number) =>
    request<EdgeApiKeyRow>(`/edge-admin/keys/${keyId}/revoke/`, { method: "POST" }),
  sourceRecords: (search: string, limit = 50) =>
    request<{ count: number; results: SourceRecordRow[] }>(
      `/hub/source-records/?limit=${limit}&search=${encodeURIComponent(search)}`,
    ),

  /**
   * Nhap lieu ung vien thu cong — them nguon du lieu ngoai Edge. Moi lo di qua
   * bang staging roi commit sang SourceRecord qua Edge dieu rieng "hub-manual".
   */
  intakeTemplateUrl: "/api/v1/intake/template.xlsx",
  intakeExportUrl: "/api/v1/intake/export.csv",
  intakeBatches: () =>
    request<{ results: IntakeBatch[] }>("/intake/batches/"),
  intakeBatch: (id: number) => request<IntakeBatch>(`/intake/batches/${id}/`),
  intakeCreateExcelBatch: (file: File, sourceLabel: string) => {
    const body = new FormData();
    body.append("file", file);
    body.append("kind", "excel");
    body.append("source_label", sourceLabel);
    return request<IntakeBatch>("/intake/batches/", { method: "POST", body });
  },
  intakeCreateCvBatch: (sourceLabel: string) =>
    request<IntakeBatch>("/intake/batches/", {
      method: "POST",
      body: JSON.stringify({ kind: "bulk_cv", source_label: sourceLabel }),
    }),
  intakeUploadCvs: (batchId: number, files: File[]) => {
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    return request<IntakeBatch>(`/intake/batches/${batchId}/cvs/`, {
      method: "POST",
      body,
    });
  },
  intakePatchRow: (
    batchId: number,
    rowId: number,
    patch: { fields?: Record<string, string>; skip?: boolean },
  ) =>
    request<IntakeRow>(`/intake/batches/${batchId}/rows/${rowId}/`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  intakeCommit: (batchId: number, dedupStrategy: "skip" | "update") =>
    request<IntakeBatch>(`/intake/batches/${batchId}/commit/`, {
      method: "POST",
      body: JSON.stringify({ dedup_strategy: dedupStrategy }),
    }),
  intakeDeleteBatch: (batchId: number) =>
    request<{ ok: boolean }>(`/intake/batches/${batchId}/`, { method: "DELETE" }),

  talentSearch: (filters: SearchFilters, limit = 50, offset = 0) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      // Bỏ giá trị rỗng/false: gửi lên chỉ làm URL rối và không đổi kết quả.
      if (value === "" || value === false || value === undefined) continue;
      params.set(key, value === true ? "1" : String(value));
    }
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    return request<{ count: number; results: TalentCard[] }>(
      `/talent/search/?${params.toString()}`,
    );
  },
  recentlyViewed: (limit = 50) =>
    request<{ count: number; results: TalentCard[] }>(
      `/talent/recently-viewed/?limit=${limit}`,
    ),
  talentRelationshipFollowups: () =>
    request<{
      count: number;
      results: Array<
        TalentCard & {
          relationship_followup: {
            state: string;
            next_action: string;
            next_action_at: string;
            interest_level: number;
          };
        }
      >;
    }>("/talent/relationship-followups/"),
  talentFacets: () => request<TalentFacets>("/talent/facets/"),
  person: (id: number) => request<PersonDetail>(`/talent/people/${id}/`),
  personUpdate: (id: number, patch: Record<string, unknown>) =>
    request<PersonDetail>(`/talent/people/${id}/profile/`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  personRederive: (id: number) =>
    request<PersonDetail>(`/talent/people/${id}/rederive/`, { method: "POST" }),
  personAsk: (id: number, question: string, history: PersonAskTurn[] = []) =>
    request<PersonAskResponse>(`/talent/people/${id}/ask/`, {
      method: "POST",
      body: JSON.stringify({ question, ...(history.length ? { history } : {}) }),
    }),
  documentUrl: (id: number, inline = false) =>
    `/api/v1/talent/documents/${id}/download/${inline ? "?inline=1" : ""}`,
  documentPreviewUrl: (id: number) => `/api/v1/talent/documents/${id}/preview/`,
  documentText: (id: number) =>
    request<DocumentTextResponse>(
      `/talent/documents/${id}/text/`,
    ),
  createTag: (name: string) =>
    request<{ id: number; name: string; slug: string }>("/talent/tags/", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  setPersonTag: (id: number, tag: string, remove = false) =>
    request<PersonDetail>(`/talent/people/${id}/tags/`, {
      method: remove ? "DELETE" : "POST",
      body: JSON.stringify({ tag }),
    }),
  createPool: (
    name: string,
    description = "",
    domain: "talent" | "rb" = "talent",
  ) =>
    request<{ id: number; name: string; domain: "talent" | "rb" }>(
      "/talent/pools/",
      {
        method: "POST",
        body: JSON.stringify({ name, description, domain }),
      },
    ),
  pools: (domain: "talent" | "rb" = "talent") =>
    request<{
      results: Array<{
        id: number;
        name: string;
        domain: "talent" | "rb";
        description: string;
        owner_name: string;
        member_count: number;
        is_archived: boolean;
      }>;
    }>(`/talent/pools/?domain=${domain}`),
  poolUpdate: (id: number, patch: Record<string, unknown>) =>
    request<unknown>(`/talent/pools/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  poolArchive: (id: number) =>
    request<unknown>(`/talent/pools/${id}/`, { method: "DELETE" }),
  poolMembers: (poolId: number) =>
    request<{
      pool: {
        id: number;
        name: string;
        description: string;
        member_count: number;
      };
      count: number;
      results: TalentCard[];
    }>(`/talent/pools/${poolId}/members/`),
  setPoolMember: (poolId: number, personId: number, remove = false) =>
    request<unknown>(`/talent/pools/${poolId}/members/`, {
      method: remove ? "DELETE" : "POST",
      body: JSON.stringify({ person_id: personId }),
    }),

  aiProviders: () =>
    request<{
      results: ProviderRow[];
      active_order: string[];
      available: string[];
      task_routes: TaskModelRoute[];
      effective_tasks: EffectiveTaskConfig[];
      /** Mọi tác vụ dùng não AI, kèm nhãn tiếng Việt — để CHỌN, không phải gõ tay. */
      task_catalog?: AiTaskInfo[];
      task_groups?: string[];
      /** Danh mục model theo nhà cung cấp, để ô model là danh sách chọn có chú
       *  thích chứ không phải ô chữ trống. */
      models?: Record<string, AiModelInfo[]>;
      /** `kind` của tác vụ → năng lực model BẮT BUỘC phải có. */
      kind_requires?: Record<string, string>;
    }>("/ai/providers/"),
  aiProviderUpdate: (provider: string, patch: ProviderPatch) =>
    request<ProviderRow>(`/ai/providers/${provider}/`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  aiProviderTest: (provider: string) =>
    request<{
      ok: boolean;
      detail: string;
      /** Kết quả TỪNG khoá — với nhiều khoá, cần biết khoá nào hỏng. */
      keys: Array<{
        index: number;
        label: string;
        ok: boolean;
        detail: string;
      }>;
    }>(`/ai/providers/${provider}/test/`, { method: "POST" }),
  aiProviderModels: (provider: string) =>
    request<{ models: string[] }>(`/ai/providers/${provider}/models/`),
  aiTaskRouteSave: (task: string, body: { provider: string; model?: string; enabled?: boolean }) =>
    request<{ route: TaskModelRoute; effective: TaskModelRoute['effective'] }>(`/ai/providers/routes/${task}/`, {
      method: "PUT", body: JSON.stringify(body),
    }),
  aiTaskRouteDelete: (task: string) => request<void>(`/ai/providers/routes/${task}/`, { method: "DELETE" }),
  aiUsage: () => request<UsageSummary>("/ai/usage/"),

  embeddingConfig: (probe = false) =>
    request<EmbeddingConfig>(`/talent/embedding-config/${probe ? "?probe=1" : ""}`),
  embeddingConfigSave: (body: Partial<Pick<EmbeddingConfig,
    "mode" | "selfhost_base_url" | "selfhost_model" | "gemini_model" | "greennode_model" | "dimensions">>) =>
    request<EmbeddingConfig>("/talent/embedding-config/", {
      method: "PUT", body: JSON.stringify(body),
    }),

  hiringNeeds: (mine = false) =>
    request<{ results: HiringNeedRow[] }>(
      `/hiring/needs/${mine ? "?mine=1" : ""}`,
    ),
  hiringNeedCreate: (body: {
    title?: string;
    department?: string;
    jd_text?: string;
  }) =>
    request<HiringNeedRow>("/hiring/needs/", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  hiringNeed: (id: number) => request<HiringNeedRow>(`/hiring/needs/${id}/`),
  hiringNeedUpdate: (id: number, patch: Record<string, unknown>) =>
    request<HiringNeedRow>(`/hiring/needs/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  hiringNeedDelete: (id: number) =>
    fetch(`/api/v1/hiring/needs/${id}/`, {
      method: "DELETE",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken() },
    }).then(() => undefined),
  hiringParseJd: (id: number) =>
    request<HiringNeedRow & { parse_error: string }>(
      `/hiring/needs/${id}/parse-jd/`,
      {
        method: "POST",
      },
    ),

  hiringSuggestions: (id: number, limit = 20) =>
    request<{
      hiring_need: HiringNeedRow;
      count: number;
      /** Số người khớp ĐỦ tiêu chí; phần còn lại là người được nới vào. */
      strict_count: number;
      results: SuggestionRow[];
    }>(`/hiring/needs/${id}/suggestions/?limit=${limit}`),
  hiringMark: (
    id: number,
    personId: number,
    state: Candidacy["state"],
    note = "",
  ) =>
    request<Candidacy>(`/hiring/needs/${id}/mark/`, {
      method: "POST",
      body: JSON.stringify({ person_id: personId, state, note }),
    }),
  hiringCalibrate: (id: number) =>
    request<CalibrationResult>(`/hiring/needs/${id}/calibrate/`, {
      method: "POST",
    }),
  hiringCalibrateReset: (id: number) =>
    request<HiringNeedRow>(`/hiring/needs/${id}/calibrate/reset/`, {
      method: "POST",
    }),

  hiringRequestHunt: (
    id: number,
    body: { person_ids?: number[]; message?: string },
  ) =>
    request<HuntRequestRow>(`/hiring/needs/${id}/hunt/`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  hiringMetrics: () => request<MetricsResponse>("/hiring/metrics/"),
  hunts: (
    params: {
      mine?: boolean;
      open?: boolean;
      status?: string;
      pool?: number;
      scope?: "mine" | "followup" | "unassigned" | "completed";
      limit?: number;
      offset?: number;
    } = {},
  ) => {
    const query = new URLSearchParams();
    if (params.mine) query.set("mine", "1");
    if (params.open) query.set("open", "1");
    if (params.status) query.set("status", params.status);
    if (params.scope) query.set("scope", params.scope);
    if (params.pool) query.set("pool", String(params.pool));
    if (params.limit) query.set("limit", String(params.limit));
    if (params.offset) query.set("offset", String(params.offset));
    return request<{ count: number; limit: number; offset: number; results: HuntRequestRow[] }>(
      `/hiring/hunts/?${query.toString()}`,
    );
  },
  huntTasks: (
    params: {
      scope?: "all" | "overdue" | "today" | "unassigned" | "completed";
      q?: string;
      pool?: number;
      limit?: number;
      offset?: number;
    } = {},
  ) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== "") query.set(key, String(value));
    });
    return request<HuntTaskResponse>(
      `/hiring/hunts/tasks/?${query.toString()}`,
    );
  },
  createShortlist: (body: {
    title: string;
    person_ids: number[];
    message?: string;
    priority?: string;
  }) =>
    request<HuntRequestRow>("/hiring/hunts/", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  talentRelationship: (personId: number) =>
    request<PersonDetail["relationships"][number]>(
      `/talent/people/${personId}/relationship/`,
    ),
  talentRelationshipUpdate: (
    personId: number,
    patch: Record<string, unknown>,
  ) =>
    request<PersonDetail["relationships"][number]>(
      `/talent/people/${personId}/relationship/`,
      {
        method: "PATCH",
        body: JSON.stringify(patch),
      },
    ),
  huntUpdate: (id: number, patch: Record<string, unknown>) =>
    request<HuntRequestRow>(`/hiring/hunts/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  huntCandidateUpdate: (
    huntId: number,
    personId: number,
    patch: {
      state?: HuntCandidateState;
      note?: string;
      return_reason?: string;
      outreach_draft?: string;
      priority?: "low" | "normal" | "high" | "urgent";
      next_action_at?: string | null;
      assigned_to_id?: number | null;
      claim?: boolean;
    },
  ) =>
    request<HuntCandidateRow>(`/hiring/hunts/${huntId}/people/${personId}/`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  huntCandidatesBulk: (
    items: Array<{ hunt_id: number; person_id: number }>,
    patch: { state?: HuntCandidateState; assigned_to_id?: number | null },
  ) =>
    request<{ updated: number }>("/hiring/hunts/candidates/bulk/", {
      method: "POST",
      body: JSON.stringify({ items, patch }),
    }),
  outreachDraft: (
    huntId: number,
    personId: number,
    channel: "email" | "message",
  ) =>
    request<{ draft: string; channel: string; error: string }>(
      `/hiring/hunts/${huntId}/people/${personId}/draft/`,
      { method: "POST", body: JSON.stringify({ channel }) },
    ),
  socialAnalyze: (
    content: string,
    options: { author_name?: string; save?: boolean } = {},
  ) =>
    request<AnalyzeResult>("/social/analyze/", {
      method: "POST",
      body: JSON.stringify({ content, ...options }),
    }),
  socialPosts: (params: { domain?: string; linked?: boolean } = {}) => {
    const query = new URLSearchParams();
    if (params.domain) query.set("domain", params.domain);
    if (params.linked) query.set("linked", "1");
    return request<{ count: number; results: SocialPostRow[] }>(
      `/social/posts/?${query.toString()}`,
    );
  },

  rbOpportunities: (
    params: {
      open?: boolean;
      mine?: boolean;
      scope?: string;
      person?: number;
      pool?: number;
      limit?: number;
      offset?: number;
    } = {},
  ) => {
    const query = new URLSearchParams();
    if (params.open) query.set("open", "1");
    if (params.mine) query.set("mine", "1");
    if (params.scope) query.set("scope", params.scope);
    if (params.person) query.set("person", String(params.person));
    if (params.pool) query.set("pool", String(params.pool));
    if (params.limit) query.set("limit", String(params.limit));
    if (params.offset) query.set("offset", String(params.offset));
    return request<{ count: number; results: RBOpportunityRow[] }>(
      `/rb/opportunities/?${query.toString()}`,
    );
  },
  rbOpportunityCreate: (payload: {
    person_id: number;
    product: string;
    need?: string;
    priority?: string;
  }) =>
    request<RBOpportunityRow>("/rb/opportunities/", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  rbCustomerTasks: (params: {
    scope?: "all" | "overdue" | "today" | "unassigned" | "completed";
    q?: string;
    pool?: number;
    limit?: number;
    offset?: number;
  } = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== "" && value != null) query.set(key, String(value));
    });
    return request<RBCustomerTaskResponse>(`/rb/tasks/?${query.toString()}`);
  },
  rbOpportunitiesBulk: (opportunityIds: number[], patch: Record<string, unknown>) =>
    request<{ updated: number }>("/rb/opportunities/bulk/", {
      method: "POST",
      body: JSON.stringify({ opportunity_ids: opportunityIds, patch }),
    }),
  rbOwners: () =>
    request<{ results: Array<{ id: number; name: string }> }>("/rb/owners/"),

  /**
   * Cua DUY NHAT tra ve lien he day du. Moi API danh sach deu che vo dieu kien,
   * nen khong co duong vong nao lay duoc lien he hang loat ma khong di qua day —
   * noi co dem han muc va co ghi vet.
   */
  contactUnlock: (personId: number, domain?: "talent" | "rb") =>
    request<ContactUnlockResult>(`/auth/contact-unlock/${personId}/`, {
      method: "POST",
      body: JSON.stringify({ domain: domain ?? "" }),
    }),
  contactQuota: () => request<ContactQuota>("/auth/contact-unlock/quota/"),
  captureStats: () => request<CaptureStats>("/hub/capture/"),

  rbToday: (params: { scope?: string; product?: string; limit?: number } = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== "" && value != null) query.set(key, String(value));
    });
    return request<TodaysOpportunitiesResponse>(`/rb/today/?${query.toString()}`);
  },
  rbSuggestionAction: (
    suggestionId: number,
    payload:
      | { action: "accept"; priority?: string }
      | { action: "snooze"; days?: number }
      | { action: "dismiss"; reason: string },
  ) =>
    request<{
      opportunity?: RBOpportunityRow;
      created?: boolean;
      suggestion?: OpportunitySuggestionRow;
    }>(`/rb/suggestions/${suggestionId}/action/`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  rbProspects: (question: string, history: HistoryTurn[] = [], conversationId = "",
    clientTurnId = "") =>
    request<ProspectResponse>("/rb/prospects/", {
      method: "POST",
      body: JSON.stringify({
        q: question,
        ...(history.length ? { history } : {}),
        ...(conversationId ? { conversation_id: conversationId } : {}),
        ...(clientTurnId ? { client_turn_id: clientTurnId } : {}),
      }),
    }),
  rbWorkProfile: () => request<WorkProfileRow>("/rb/work-profile/"),
  rbWorkProfileSave: (patch: Record<string, unknown>) =>
    request<WorkProfileRow>("/rb/work-profile/", {
      method: "PUT",
      body: JSON.stringify(patch),
    }),
  rbOutcomes: (opportunityId: number) =>
    request<{ results: OpportunityOutcomeRow[] }>(
      `/rb/opportunities/${opportunityId}/outcomes/`,
    ),
  rbOutcomeCreate: (
    opportunityId: number,
    payload: { outcome: string; channel?: string; note?: string; action?: string },
  ) =>
    request<OpportunityOutcomeRow>(
      `/rb/opportunities/${opportunityId}/outcomes/`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  rbProfile: (personId: number) =>
    request<RBProfileRow>(`/rb/people/${personId}/`),
  rbProfileUpdate: (personId: number, patch: Record<string, unknown>) =>
    request<RBProfileRow>(`/rb/people/${personId}/profile/`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  rbCustomers: (params: Record<string, string | number | boolean> = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== "" && value !== false && value != null)
        query.set(key, value === true ? "1" : String(value));
    });
    return request<{ count: number; results: RBProfileRow[] }>(
      `/rb/people/?${query.toString()}`,
    );
  },
  rbRecentlyViewed: () =>
    request<{ count: number; results: RBProfileRow[] }>("/rb/recently-viewed/"),
  rbRelationshipFollowups: () =>
    request<{ count: number; results: RBProfileRow[] }>(
      "/rb/relationship-followups/",
    ),
  rbOpportunityUpdate: (id: number, patch: Record<string, unknown>) =>
    request<RBOpportunityRow>(`/rb/opportunities/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  rbSuggest: (text: string) =>
    request<{ results: ProductSuggestion[] }>("/rb/suggest/", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  rbOutreachDraft: (
    opportunityId: number,
    channel: "call_script" | "message",
  ) =>
    request<{ draft: string; channel: string; error: string }>(
      `/rb/opportunities/${opportunityId}/draft/`,
      { method: "POST", body: JSON.stringify({ channel }) },
    ),
  rbOutreachSent: (opportunityId: number, channel: string, draft: string) =>
    request<RBOpportunityRow>(`/rb/opportunities/${opportunityId}/sent/`, {
      method: "POST",
      body: JSON.stringify({ channel, draft }),
    }),

  outreachSent: (
    huntId: number,
    personId: number,
    channel: string,
    draft: string,
  ) =>
    request<HuntCandidateRow>(
      `/hiring/hunts/${huntId}/people/${personId}/sent/`,
      {
        method: "POST",
        body: JSON.stringify({ channel, draft }),
      },
    ),
  rbMetrics: () => request<RBMetricsResponse>("/rb/metrics/"),
  workflowStages: () =>
    request<{ results: WorkflowStage[] }>("/workflows/stages/"),
  workflowCatalog: () =>
    request<{ results: WorkflowStage[] }>("/workflows/catalog/"),
  workflowStageUpdate: (id: number, patch: Partial<WorkflowStage>) =>
    request<{ results: WorkflowStage[] }>("/workflows/stages/", {
      method: "PATCH",
      body: JSON.stringify({ id, ...patch }),
    }),

  // --- Vận hành & báo cáo (Phase 15) ---
  reportsOverview: () => request<OverviewResponse>("/reports/overview/"),
  savedViews: (module?: "talent" | "rb") =>
    request<{ results: SavedView[] }>(
      `/reports/saved-views/${module ? `?module=${module}` : ""}`,
    ),
  saveView: (
    module: "talent" | "rb",
    name: string,
    filters: Record<string, unknown>,
  ) =>
    request<SavedView>("/reports/saved-views/", {
      method: "POST",
      body: JSON.stringify({ module, name, filters }),
    }),
  reopenSavedView: (id: number) =>
    request<SavedView>(`/reports/saved-views/${id}/`, { method: "POST" }),
  deleteSavedView: (id: number) =>
    fetch(`/api/v1/reports/saved-views/${id}/`, {
      method: "DELETE",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken() },
    }).then(() => undefined),
  filterHistory: (module: "talent" | "rb") =>
    request<{ results: FilterHistoryRow[] }>(`/reports/filter-history/?module=${module}`),
  recordFilterHistory: (module: "talent" | "rb", filters: SearchFilters) =>
    request<FilterHistoryRow>("/reports/filter-history/", {
      method: "POST",
      body: JSON.stringify({ module, filters }),
    }),
  clearFilterHistory: (module: "talent" | "rb") =>
    fetch(`/api/v1/reports/filter-history/?module=${module}`, {
      method: "DELETE",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken() },
    }).then(() => undefined),

  /** URL xuất CSV — dùng trong `<a href>`, không phải `fetch()`: tải file thật
   * cần trình duyệt tự xử lý Content-Disposition, `fetch` thì không. */
  talentExportUrl: (filters: SearchFilters) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value === "" || value === false || value === undefined) continue;
      params.set(key, value === true ? "1" : String(value));
    }
    return `/api/v1/talent/search/export/?${params.toString()}`;
  },
  rbOpportunitiesExportUrl: (
    params: { open?: boolean; mine?: boolean; scope?: string } = {},
  ) => {
    const query = new URLSearchParams();
    if (params.open) query.set("open", "1");
    if (params.mine) query.set("mine", "1");
    if (params.scope) query.set("scope", params.scope);
    return `/api/v1/rb/opportunities/export/?${query.toString()}`;
  },

  // --- Quản trị: người dùng & nhật ký hệ thống ---
  users: () => request<{ results: UserRow[] }>("/auth/users/"),
  userCreate: (body: UserCreate) =>
    request<UserRow>("/auth/users/", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  userUpdate: (id: number, patch: UserPatch) =>
    request<UserRow>(`/auth/users/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  userBulkTemplateUrl: () => "/api/v1/auth/users/bulk-template/",
  userBulkCreate: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<UserBulkResult>("/auth/users/bulk-create/", {
      method: "POST",
      body: form,
    });
  },
  publicSettings: () => request<PublicSettings>("/auth/public-settings/"),
  publicSettingsSave: (patch: Partial<PublicSettings>) =>
    request<PublicSettings>("/auth/public-settings/", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  uploadOgImage: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ url: string; width: number; height: number; bytes: number }>(
      "/auth/branding/upload-og-image/",
      {
        method: "POST",
        body: form,
      }
    );
  },
  uploadRadarAvatar: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ url: string; width: number; height: number; bytes: number }>(
      "/auth/branding/upload-og-image/",
      {
        method: "POST",
        body: form,
      }
    );
  },
  emailOtpSettings: () => request<EmailOtpSettings>("/auth/email-otp/settings/"),
  emailOtpTestSend: (recipient?: string, template?: string) =>
    request<EmailOtpTestSendResult>("/auth/email-otp/test-send/", {
      method: "POST",
      body: JSON.stringify({ recipient, template }),
    }),
  emailOtpSettingsSave: (body: Partial<Omit<EmailOtpSettings, 'tntalent_domains' | 'msb_domains'>> & {
    api_key?: string; webhook_secret?: string; tntalent_domains?: string; msb_domains?: string;
  }) =>
    request<EmailOtpSettings>("/auth/email-otp/settings/", {
      method: "PATCH", body: JSON.stringify(body),
    }),
  resendInbox: () => request<{ results: ResendInboxRow[] }>("/auth/resend/inbox/"),
  resendEvents: () => request<{ results: ResendWebhookEventRow[] }>("/auth/resend/events/"),

  backupList: () => request<DatabaseBackupListResponse>("/backups/"),
  backupTrigger: () =>
    request<DatabaseBackupRow>("/backups/trigger/", {
      method: "POST",
    }),
  backupDownloadUrl: (id: number) => `/api/v1/backups/${id}/download/`,
  backupDelete: (id: number) =>
    request<{ success: boolean; message: string }>(`/backups/${id}/`, {
      method: "DELETE",
    }),
  accessLog: (params: Record<string, string> = {}) => {
    const query = new URLSearchParams(params);
    return request<{ count: number; results: AccessLogRow[] }>(
      `/auth/access-log/?${query.toString()}`,
    );
  },
  accessLogSummary: () =>
    request<AccessLogSummary>("/auth/access-log/summary/"),
};

export interface ResendInboxRow {
  id: number; email_id: string; sender: string; recipients: string[]; subject: string;
  text_body: string; attachments: Array<{ filename?: string; content_type?: string }>;
  received_at: string | null;
}
export interface ResendWebhookEventRow {
  id: number; event_type: string; email_id: string; occurred_at: string | null; received_at: string;
  svix_id?: string;
}

export interface AiTaskInfo {
  name: string;
  label: string;
  description: string;
  group: string;
  /** json = cần nhanh/JSON chuẩn · viet = cần hành văn · doc = đọc dài mà rẻ
   *  · embedding = sinh vector, không phải sinh văn · vision = phải đọc được ảnh.
   *
   *  Hai giá trị cuối là YÊU CẦU, không phải gợi ý: chọn sai không báo lỗi, chỉ
   *  trả rác. `kind_requires` cho biết cái nào cần chặn. */
  kind: string;
  /** Model hợp nhất theo đo đạc, điền sẵn khi chọn tác vụ. */
  default_provider: string;
  default_model: string;
}

/** Một model trong danh mục của nhà cung cấp. */
export interface AiModelInfo {
  id: string;
  label: string;
  note: string;
  /** "chat" | "vision" | "embedding". Rỗng khi mã này dò được từ nhà cung cấp
   *  mà chưa ai xác nhận nó làm được gì. */
  capabilities: string[];
  /** true = dò từ `/models`, chưa xác nhận năng lực → không cho gán vào tác vụ
   *  đòi năng lực đặc biệt. */
  discovered: boolean;
}

export interface PublicSettings {
  app_name: string;
  app_tagline: string;
  app_icon: string;
  app_logo_url: string;
  color_preset: string;
  custom_color: string;
  gradient_from?: string;
  gradient_to?: string;
  gradient_via?: string;
  gradient_angle?: string;
  radar_avatar_url?: string;
  radar_avatar_emoji?: string;
  theme_mode: string;
  table_density: string;
  mask_sensitive_data: boolean;
  min_match_score: number;
  items_per_page: number;
  sound_alerts: boolean;

  // Thumbnail / xem trước liên kết. Để trống = suy ra từ tên + tagline.
  og_image_url?: string;
  og_image_alt?: string;
  og_image_width?: number;
  og_image_height?: number;
  og_title?: string;
  og_description?: string;
  og_site_name?: string;
  meta_keywords?: string;
  meta_robots?: string;
  pwa_short_name?: string;
  pwa_background_color?: string;
  /** Bản ĐÃ suy ra — dùng cho ô xem trước, khớp với thứ crawler thật sự nhận. */
  link_preview?: {
    title: string;
    description: string;
    site_name: string;
    image: string;
    image_alt: string;
    image_width: number;
    image_height: number;
    keywords: string;
    robots: string;
  };
}
