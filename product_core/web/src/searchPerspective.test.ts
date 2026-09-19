import { beforeEach, describe, expect, it } from "vitest";
import {
  PERSPECTIVE_STORAGE_KEY,
  perspectiveAccess,
  personLinkFrom,
  resolvePerspective,
} from "./searchPerspective";

const set = (...values: string[]) => new Set(values);

beforeEach(() => {
  localStorage.clear();
});

describe("perspectiveAccess — quyền mở góc nhìn bám theo modules", () => {
  it("chỉ có module talent thì không mở được góc nhìn Khách hàng", () => {
    expect(perspectiveAccess(set("talent"), set("recruiter"))).toEqual({
      canRecruiter: true, canProspect: false, canSwitch: false,
    });
  });

  it("có cả hai module mới hiện thanh chuyển góc nhìn", () => {
    expect(perspectiveAccess(set("talent", "rb"), set("admin")).canSwitch).toBe(true);
  });

  it("RM thuần bị khoá ở góc nhìn Khách hàng dù vẫn có module talent", () => {
    // `rb_sales` có module `talent` (đọc chéo hồ sơ, quyết định 19/08) nhưng
    // backend chặn đọc nội dung CV (`corpus_qa.can_read_cv`) nên engine Tuyển
    // dụng luôn trả 403 — hiện nút chuyển sẽ là một nút chết.
    expect(perspectiveAccess(set("talent", "rb"), set("rb_sales"))).toEqual({
      canRecruiter: false, canProspect: true, canSwitch: false,
    });
  });

  it("RM kiêm tuyển dụng thì mở lại được góc nhìn Tuyển dụng", () => {
    expect(perspectiveAccess(set("talent", "rb"), set("rb_sales", "recruiter")).canSwitch).toBe(true);
    expect(perspectiveAccess(set("talent", "rb"), set("rb_sales", "manager")).canSwitch).toBe(true);
  });

  it("Admin cấp thêm module rb cho Recruiter là có hiệu lực ngay, không cần đổi vai trò", () => {
    // `modules` đã tính cả phủ quyền trong trang Quản trị (RoleModuleAccess),
    // nên đây chính là lý do không bám theo `roles`.
    const perspective = resolvePerspective({
      modules: set("talent", "rb"),
      roles: set("recruiter"),
      param: "prospect",
    });
    expect(perspective).toBe("prospect");
  });
});

describe("resolvePerspective — thứ tự ưu tiên", () => {
  it("không được ép sang góc nhìn mà người dùng không có quyền", () => {
    expect(resolvePerspective({
      modules: set("talent"), roles: set("recruiter"), param: "prospect",
    })).toBe("recruiter");

    expect(resolvePerspective({
      modules: set("rb"), roles: set("rb_sales"), param: "recruiter",
    })).toBe("prospect");
  });

  it("chỉ một quyền thì khoá cứng ở góc nhìn đó", () => {
    expect(resolvePerspective({ modules: set("rb"), roles: set("rb_sales") })).toBe("prospect");
    expect(resolvePerspective({ modules: set("talent"), roles: set("recruiter") })).toBe("recruiter");
  });

  it("có cả hai quyền thì khôi phục lựa chọn gần nhất", () => {
    localStorage.setItem(PERSPECTIVE_STORAGE_KEY, "prospect");
    expect(resolvePerspective({
      modules: set("talent", "rb"), roles: set("admin"),
    })).toBe("prospect");
  });

  it("chưa có lựa chọn nào thì RM kiêm nhiệm mở thẳng góc nhìn Khách hàng", () => {
    expect(resolvePerspective({
      modules: set("talent", "rb"), roles: set("rb_sales"),
    })).toBe("prospect");

    expect(resolvePerspective({
      modules: set("talent", "rb"), roles: set("rb_sales", "recruiter"),
    })).toBe("recruiter");
  });

  it("tham số URL thắng lựa chọn đã lưu", () => {
    localStorage.setItem(PERSPECTIVE_STORAGE_KEY, "prospect");
    expect(resolvePerspective({
      modules: set("talent", "rb"), roles: set("manager"), param: "recruiter",
    })).toBe("recruiter");
  });
});

describe("personLinkFrom — ngữ cảnh quay lại của Hồ sơ 360°", () => {
  it("mã hoá đủ cả tab lẫn góc nhìn để quay lại đúng chỗ vừa đứng", () => {
    expect(personLinkFrom("prospect", "ai")).toBe("search-ai-prospect");
    expect(personLinkFrom("recruiter", "filter")).toBe("search-filter-recruiter");
  });
});

describe("cờ can_read_cv từ máy chủ", () => {
  it("máy chủ nói được đọc CV thì mở góc nhìn Tuyển dụng, bất kể suy từ vai trò", () => {
    expect(perspectiveAccess(set("talent", "rb"), set("rb_sales"), true).canRecruiter).toBe(true);
  });

  it("máy chủ nói không được đọc CV thì khoá góc nhìn Tuyển dụng dù là recruiter", () => {
    expect(perspectiveAccess(set("talent", "rb"), set("recruiter"), false)).toEqual({
      canRecruiter: false, canProspect: true, canSwitch: false,
    });
    expect(resolvePerspective({
      modules: set("talent", "rb"), roles: set("recruiter"), param: "recruiter", canReadCv: false,
    })).toBe("prospect");
  });
});
