import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import FormattedMarkdown, { LinkablePerson } from "./FormattedMarkdown";

afterEach(cleanup);

const PEOPLE: LinkablePerson[] = [
  { personId: 7, name: "Nguyễn An" },
  { personId: 9, name: "Trần Thị Lan Anh" },
];

function show(content: string, people: LinkablePerson[] = PEOPLE) {
  return render(
    <MemoryRouter>
      <FormattedMarkdown content={content} people={people} />
    </MemoryRouter>,
  );
}

describe("tên ứng viên trong câu trả lời", () => {
  it("thành liên kết mở hồ sơ, cùng đích với chip Hồ sơ được nhắc tới", () => {
    show("Nguyễn An làm quan hệ khách hàng cá nhân tại ACB.");
    expect(screen.getByRole("link", { name: "Nguyễn An" }))
      .toHaveAttribute("href", "/person/7?from=talent-ai");
  });

  it("tên nằm trong chữ in đậm vẫn được gắn liên kết", () => {
    // ⑤ gần như luôn bôi đậm tên người — bỏ qua nhánh này thì đúng chỗ người
    // đọc muốn bấm nhất lại không bấm được.
    show("**Nguyễn An** có 5 năm kinh nghiệm.");
    const link = screen.getByRole("link", { name: "Nguyễn An" });
    expect(link).toHaveAttribute("href", "/person/7?from=talent-ai");
    expect(link.closest("strong")).not.toBeNull();
  });

  it("tên dài không bị tên ngắn hơn cắt mất phần đuôi", () => {
    show("Trần Thị Lan Anh phụ trách mảng thẻ.");
    expect(screen.getByRole("link", { name: "Trần Thị Lan Anh" }))
      .toHaveAttribute("href", "/person/9?from=talent-ai");
  });

  it("không khớp khi tên nằm giữa chừng một từ khác", () => {
    show("Công ty Nguyễn Ang không liên quan.", [{ personId: 7, name: "Nguyễn An" }]);
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("không có ai để gắn thì văn bản giữ nguyên", () => {
    show("Kho chưa có hồ sơ nào phù hợp.", []);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText(/Kho chưa có hồ sơ nào phù hợp/)).toBeInTheDocument();
  });

  it("giữ nguyên trích dẫn [n] bên cạnh tên được gắn liên kết", () => {
    render(
      <MemoryRouter>
        <FormattedMarkdown
          content="Nguyễn An phù hợp nhất [1]."
          people={PEOPLE}
          onCitation={() => undefined}
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Nguyễn An" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1" })).toBeInTheDocument();
  });
});
