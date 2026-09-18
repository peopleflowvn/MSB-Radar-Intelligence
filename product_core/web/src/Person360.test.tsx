import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, HuntRequestRow, PersonDetail, RBOpportunityRow, RBProfileRow, Session } from "./api";
import Person360 from "./Person360";

// `render()` không tự dọn DOM giữa các `it` khi không bật `test.globals` —
// thiếu dòng này thì hồ sơ của lượt test trước vẫn còn trên trang, và lượt
// sau tìm "Nguyễn Văn An" ra NHIỀU hơn một chỗ.
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const mockPerson = {
  id: 7,
  display_name: "Nguyễn Văn An",
  headline: "Senior Data Architect",
  primary_email: "an.nguyen@example.com",
  primary_phone: "0912345678",
  notes: "Ứng viên tiềm năng",
  created_at: "2026-08-01T08:00:00Z",
  needs_review: false,
  sources: [
    {
      id: 1,
      source: "LinkedIn",
      account: "MSB Recruiter",
      position: "Lead Data Engineer",
      applied_ts: "2026-08-10T14:30:00Z",
    },
  ],
  talent: {
    current_title: "Senior Data Architect",
    current_company: "Tech Corp",
    years_experience: 8,
    seniority: "Lead / Principal",
    education: "Đại học Bách Khoa",
    expected_salary: "60 - 80 triệu",
    location: "Hà Nội",
    skills: ["Python", "Spark", "PostgreSQL", "Kafka", "Data Modeling"],
    industries: ["Fintech", "Banking"],
    summary: "8 năm kinh nghiệm kiến trúc dữ liệu lớn và phân tích thời gian thực.",
    owner_name: "Recruiter Linh",
    owner_id: 1,
    curated_fields: ["current_title", "skills"],
    last_source_at: "2026-08-20T09:00:00Z",
    tags: [],
    derived_at: null,
  },
  pools: [
    { id: 1, name: "Data Core Talent" },
  ],
  identities: [
    { kind: "email", value: "an.nguyen@example.com", first_seen_at: "2026-08-01T08:00:00Z" },
    { kind: "phone", value: "0912345678", first_seen_at: "2026-08-01T08:00:00Z" },
  ],
  documents: [
    {
      id: 101,
      version: 1,
      filename: "CV_NguyenVanAn_2026.pdf",
      file_size: 245000,
      text_length: 3200,
      source: "TopCV",
      has_file: true,
      used_by: 1,
      created_at: "2026-08-01T08:00:00Z",
      observed_at: "2026-08-01T08:00:00Z",
      document_type: "cv",
      mime_type: "application/pdf",
      parse_status: "ok",
      text_variant_count: 1,
      content_group: "abc123",
      same_content_occurrences: 1,
      parse_provider: "edge",
      parse_model: "parser-v1",
      parse_error: "",
      parsed_at: "2026-08-01T08:00:00Z",
    },
  ],
  document_stats: {
    submission_count: 1,
    file_version_count: 1,
    distinct_text_count: 1,
    duplicate_text_count: 0,
    unparsed_count: 0,
    text_variant_count: 1,
  },
  timeline: [
    { at: "2026-08-01T08:00:00Z", action: "Đồng bộ hồ sơ từ TopCV", actor: "System", kind: "sync", detail: "" },
    { at: "2026-08-15T10:00:00Z", action: "Đã liên hệ sơ bộ qua điện thoại", actor: "Linh Recruiter", kind: "contact", detail: "" },
  ],
  active_worklists: [
    {
      hunt_id: 10,
      title: "Tuyển Dụng Data Chapter Lead Q3",
      state: "contacting",
      state_label: "Đang tiếp cận",
      priority: "high",
      assigned_to_name: "Linh Recruiter",
      next_action_at: "2026-08-31T10:00:00Z",
      updated_at: "2026-08-25T14:00:00Z",
      note: "Ứng viên hẹn trao đổi sau 17h",
      stage_color: "#6366f1",
      sla_due_at: null,
      is_overdue: false,
      assigned_to_id: 1,
    },
  ],
  signals: [
    {
      id: 1,
      domain: "talent",
      signal_type: "Thay đổi việc làm gần đây",
      confidence: 0.92,
      observed_at: "2026-08-20T00:00:00Z",
      status: "active",
    },
  ],
} as unknown as PersonDetail;

const mockRBProfile = {
  person_id: 7,
  display_name: "Nguyễn Văn An",
  headline: "Senior Data Architect",
  primary_phone: "0912345678",
  primary_email: "an.nguyen@example.com",
  occupation: "Senior Data Architect",
  employer: "Tech Corp",
  segment: "affluent",
  lead_status: "warm",
  sales_owner_name: "RM Nam",
  interest_level: 4,
  preferred_channel: "phone",
  next_action: "Tư vấn gói vay mua nhà ưu đãi",
  next_action_at: "2026-08-31T10:00:00Z",
  interaction_summary: "Khách hàng quan tâm gói vay",
  relationship_notes: "Thu nhập cao",
  do_not_contact: false,
  active_owners: [],
  interests: [
    {
      id: 1,
      product: "mortgage",
      product_label: "Vay mua nhà",
      confidence: 0.88,
      source: "AI Dò tìm",
      observed_at: "2026-08-25T10:00:00Z",
      evidence: {},
    },
  ],
  open_opportunities: [],
  created_at: "2026-08-01T08:00:00Z",
} as unknown as RBProfileRow;

describe("Person360 Component - Hồ sơ 360° Hợp Nhất (/person/:id)", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });

    vi.spyOn(api, "me").mockResolvedValue({
      authenticated: true,
      username: "admin",
      roles: ["admin", "recruiter", "rb_sales"],
      id: 1,
      full_name: "Admin User",
      role_labels: ["Quản trị viên"],
      is_superuser: true,
      modules: ["talent", "rb", "social", "reports", "edge_ops", "ai_settings", "admin_console"],
    } as unknown as Session);

    vi.spyOn(api, "person").mockResolvedValue(mockPerson);
    vi.spyOn(api, "rbProfile").mockResolvedValue(mockRBProfile);
    vi.spyOn(api, "rbOpportunities").mockResolvedValue({
      count: 1,
      results: [
        {
          id: 201,
          person: 7,
          product: "mortgage",
          product_label: "Vay mua nhà",
          status: "in_progress",
          status_label: "Đang tư vấn",
          assigned_to: 1,
          assigned_to_name: "RM Nam",
          need: "Gói vay mua nhà 2 tỷ",
          priority: "high",
          next_action_at: "2026-08-31T10:00:00Z",
          created_at: "2026-08-20T10:00:00Z",
        },
      ] as unknown as RBOpportunityRow[],
    });
    vi.spyOn(api, "rbOwners").mockResolvedValue({
      results: [{ id: 1, name: "RM Nam" }],
    });
    vi.spyOn(api, "pools").mockResolvedValue({
      results: [{ id: 1, name: "Khách hàng VIP", description: "", domain: "rb", owner_name: "RM Nam", member_count: 5, is_archived: false }],
    });

    vi.spyOn(api, "talentFacets").mockResolvedValue({
      owners: [{ id: 1, name: "Recruiter Linh" }],
      pools: [{ id: 1, name: "Data Core Talent", domain: "talent", member_count: 1 }],
      by_source: [],
      by_location: [],
      tags: [],
      relationships: [],
      products: [],
      lead_statuses: [],
    });
    vi.spyOn(api, "talentRelationship").mockResolvedValue({
      domain: "talent",
      state: "interested",
      interest_level: 4,
      owner: "Recruiter Linh",
      owner_id: 1,
      next_action: "Gửi thư mời phỏng vấn kỹ thuật",
      next_action_at: "2026-08-31T10:00:00Z",
      last_contact_at: "2026-08-25T10:00:00Z",
      preferred_channel: "phone",
      reason: "",
      notes: "Kỳ vọng mức lương 70tr net",
      do_not_contact: false,
      preferences: {
        preferred_roles: "Data Lead",
        preferred_location: "Hà Nội",
        availability: "1 tháng",
        work_mode: "Hybrid",
      },
      updated_at: "2026-08-25T10:00:00Z",
    });
    vi.spyOn(api, "hunts").mockResolvedValue({
      count: 1,
      limit: 50,
      offset: 0,
      results: [
        {
          id: 10,
          title: "Tuyển Dụng Data Chapter Lead Q3",
          hiring_need_title: "Data Lead",
          status: "in_progress",
          hiring_need: 1,
          department: "IT",
          target_count: 1,
          accepted_count: 0,
          rejected_count: 0,
          pending_count: 1,
          contacting_count: 0,
          interviewing_count: 0,
          offered_count: 0,
          onboarding_count: 0,
          created_at: "2026-08-01T08:00:00Z",
          updated_at: "2026-08-25T14:00:00Z",
          created_by_name: "Admin",
          lead_recruiter_name: "Recruiter Linh",
          lead_recruiter_id: 1,
          total_candidates: 1,
          message: "",
          priority: "high",
          due_date: null,
          is_overdue: false,
          pool: null,
          pool_name: "",
          assigned_recruiters: [],
        },
      ] as unknown as HuntRequestRow[],
    });
    vi.spyOn(api, "documentText").mockResolvedValue({
      text: "NGUYỄN VĂN AN - SENIOR DATA ARCHITECT\nKinh nghiệm: 8 năm xây dựng Data Pipeline...",
      parse_status: "ok",
      parse_error: "",
      versions: [{
        id: 1,
        text: "NGUYỄN VĂN AN - SENIOR DATA ARCHITECT\nKinh nghiệm: 8 năm xây dựng Data Pipeline...",
        text_length: 90,
        origins: ["edge"],
        provider: "edge",
        model: "parser-v1",
        quality_score: 0.8,
        created_at: "2026-08-01T08:00:00Z",
        is_primary: true,
      }],
    });
  });

  it("gộp toàn diện thông tin Ứng viên & Khách hàng và hiển thị bảng Quan hệ tương ứng theo ngữ cảnh", async () => {
    // Vào theo luồng Talent (?from=talent)
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/person/7?from=talent"]}>
          <Routes>
            <Route path="/person/:id" element={<Person360 />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    // Kiểm tra thông tin Header & Hero
    expect(await screen.findByText("Nguyễn Văn An")).toBeInTheDocument();
    expect(screen.getAllByText(/Senior Data Architect/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Tech Corp/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Lead \/ Principal/).length).toBeGreaterThan(0);

    // Cột trái: Có cả Hồ sơ Năng lực (Talent) và Cơ hội Tài chính (Growth Radar)
    expect(screen.getByText("🎓 Hồ sơ năng lực & Chuyên môn")).toBeInTheDocument();
    expect(screen.getByText("Python")).toBeInTheDocument();
    expect(screen.getByText("Spark")).toBeInTheDocument();
    expect(screen.getByText("🎯 Cơ hội tài chính & Bán chéo (Growth Radar)")).toBeInTheDocument();
    expect(await screen.findByText("Gói vay mua nhà 2 tỷ")).toBeInTheDocument();

    // Cột phải: Vào theo Talent nên mặc định hiện Quan hệ Ứng viên
    expect(screen.getByText("💼 Quan hệ Ứng viên (Talent Radar)")).toBeInTheDocument();
    expect(screen.getByText("📁 Nhóm Ứng viên & Chỉnh sửa")).toBeInTheDocument();

    // Admin có nút chuyển đổi sang Quan hệ Khách hàng
    const growthRelBtn = screen.getByRole("button", { name: /Quan hệ Khách hàng \(Growth\)/ });
    expect(growthRelBtn).toBeInTheDocument();
    fireEvent.click(growthRelBtn);

    expect(await screen.findByText("👔 Quan hệ Khách hàng (Growth Radar)")).toBeInTheDocument();
  });

  it("hiện chỉ báo đủ/thiếu chỉ mục tìm kiếm cho Admin, ẩn hoàn toàn với vai trò khác", async () => {
    vi.spyOn(api, "person").mockResolvedValue({
      ...mockPerson,
      index_health: {
        status: "missing", has_projection: false, embedding_current: false,
        chunks_total: 0, chunks_current: 0, extraction_pending: false, indexed_at: null,
      },
    } as unknown as PersonDetail);

    const { unmount } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/person/7?from=talent"]}>
          <Routes><Route path="/person/:id" element={<Person360 />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
    expect(await screen.findByText(/Thiếu chỉ mục tìm kiếm/)).toBeInTheDocument();
    unmount();

    // Trường `index_health` không tồn tại với vai trò khác admin — backend đã
    // lược bỏ (`talent/views.py::_can_view_index_health`); phía UI không được
    // tự suy ra hay hiện badge nếu thiếu trường này.
    vi.spyOn(api, "me").mockResolvedValue({
      authenticated: true, username: "rm_nam", roles: ["rb_sales"], id: 2,
      full_name: "RM Nam", role_labels: ["Chuyên viên QHKH"], is_superuser: false,
      modules: ["rb", "social"],
    } as unknown as Session);
    vi.spyOn(api, "person").mockResolvedValue(mockPerson);
    const clientForRM = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={clientForRM}>
        <MemoryRouter initialEntries={["/person/7?from=rb"]}>
          <Routes><Route path="/person/:id" element={<Person360 />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
    expect(await screen.findByText("Nguyễn Văn An")).toBeInTheDocument();
    expect(screen.queryByText(/chỉ mục tìm kiếm/)).not.toBeInTheDocument();
  });

  it("quay lại đúng bộ lọc của phân hệ Tìm kiếm, giữ nguyên góc nhìn đang dùng", async () => {
    const { unmount } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/person/7?from=search-filter-recruiter"]}>
          <Routes><Route path="/person/:id" element={<Person360 />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    const back = await screen.findByRole("link", { name: /Quay lại bộ lọc đa chiều/ });
    expect(back).toHaveAttribute("href", "/search?tab=filter&perspective=recruiter");
    unmount();

    // Vào từ góc nhìn Khách hàng: quay lại đúng góc nhìn đó, không văng sang /rb.
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/person/7?from=search-ai-prospect"]}>
          <Routes><Route path="/person/:id" element={<Person360 />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
    const backProspect = await screen.findByRole("link", { name: /Quay lại tìm kiếm AI/ });
    expect(backProspect).toHaveAttribute("href", "/search?tab=ai&perspective=prospect");
  });

  it("nhận link cũ (?from=talent-filter) và trỏ về phân hệ Tìm kiếm mới", async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/person/7?from=talent-filter"]}>
          <Routes><Route path="/person/:id" element={<Person360 />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    const back = await screen.findByRole("link", { name: /Quay lại bộ lọc đa chiều/ });
    expect(back).toHaveAttribute("href", "/search?tab=filter&perspective=recruiter");
  });

  it("cho phép Recruiter/Admin mở Kho CV và xem nội dung bóc tách", async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/person/7"]}>
          <Routes>
            <Route path="/person/:id" element={<Person360 />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(await screen.findByText("Nguyễn Văn An")).toBeInTheDocument();

    // Mở Tab Kho CV sau khi quyền hạn đã tải xong
    const cvTab = await screen.findByRole("button", { name: /Kho CV \(1 file · 1 lượt\)/ });
    expect(cvTab).not.toBeDisabled();
    fireEvent.click(cvTab);

    expect(await screen.findByText(/CV_NguyenVanAn_2026.pdf/)).toBeInTheDocument();
    expect(await screen.findByTitle("CV_NguyenVanAn_2026.pdf")).toBeInTheDocument();
    expect(screen.queryByText(/SENIOR DATA ARCHITECT/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Xem văn bản trích xuất/ }));
    expect(await screen.findByText(/SENIOR DATA ARCHITECT/)).toBeInTheDocument();
  });

  it("hỏi & đáp AI trả lời dựa trên hồ sơ, câu hỏi tiếp theo gửi kèm lịch sử", async () => {
    const ask = vi
      .spyOn(api, "personAsk")
      .mockResolvedValueOnce({
        answer: "Phù hợp vị trí Data Lead nhờ 8 năm kinh nghiệm kiến trúc dữ liệu.",
        error: "", provider: "gemini", model: "flash",
      })
      .mockResolvedValueOnce({
        answer: "Nên tiếp cận qua điện thoại vào giờ hành chính.",
        error: "", provider: "gemini", model: "flash",
      });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/person/7?from=talent"]}>
          <Routes>
            <Route path="/person/:id" element={<Person360 />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(await screen.findByText("Nguyễn Văn An")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Người này có phù hợp với vị trí đang tuyển không?"));
    expect(await screen.findByText(/Phù hợp vị trí Data Lead/)).toBeInTheDocument();
    expect(ask).toHaveBeenCalledWith(7, "Người này có phù hợp với vị trí đang tuyển không?", []);

    fireEvent.change(screen.getByPlaceholderText(/Người này có phù hợp vị trí/), {
      target: { value: "Nên tiếp cận thế nào?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Hỏi" }));

    expect(await screen.findByText(/Nên tiếp cận qua điện thoại/)).toBeInTheDocument();
    expect(ask).toHaveBeenLastCalledWith(7, "Nên tiếp cận thế nào?", [
      {
        question: "Người này có phù hợp với vị trí đang tuyển không?",
        answer: "Phù hợp vị trí Data Lead nhờ 8 năm kinh nghiệm kiến trúc dữ liệu.",
      },
    ]);
  });

  it("khóa tab Kho CV khi người dùng chỉ có vai trò RM/Sales", async () => {
    vi.spyOn(api, "me").mockResolvedValue({
      authenticated: true,
      username: "rm_nam",
      roles: ["rb_sales"],
      id: 2,
      full_name: "RM Nam",
      role_labels: ["Chuyên viên QHKH"],
      is_superuser: false,
      modules: ["rb", "social"],
    } as unknown as Session);

    const clientForRM = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    render(
      <QueryClientProvider client={clientForRM}>
        <MemoryRouter initialEntries={["/person/7?from=rb"]}>
          <Routes>
            <Route path="/person/:id" element={<Person360 />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    // Chờ session & dữ liệu tải xong và hiển thị breadcrumb Growth Radar
    expect(await screen.findByText("← Quay lại Growth Radar")).toBeInTheDocument();

    // Mặc định hiện Quan hệ Khách hàng cho RM
    expect(await screen.findByText("👔 Quan hệ Khách hàng (Growth Radar)")).toBeInTheDocument();

    // Nút Kho CV bị khóa đối với RM
    const lockedCvBtn = await screen.findByRole("button", { name: /Kho CV \(Chỉ dành cho TA\)/ });
    expect(lockedCvBtn).toBeInTheDocument();
    expect(lockedCvBtn).toBeDisabled();
  });
});
