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

describe("bảng biểu trong câu trả lời (Markdown Table)", () => {
  it("hiển thị cấu trúc table, thead, tbody, th, td đúng số cột", () => {
    const tableMd = `
| Ứng viên | Vị trí hiện tại | Kinh nghiệm |
| :--- | :---: | ---: |
| **Nguyễn An** | Chuyên viên QHKH | 5 năm |
| **Trần Thị Lan Anh** | Trưởng nhóm Thẻ | 7 năm |
`.trim();

    show(tableMd);

    const table = screen.getByRole("table");
    expect(table).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Ứng viên" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Vị trí hiện tại" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Kinh nghiệm" })).toBeInTheDocument();

    const cells = screen.getAllByRole("cell");
    expect(cells.length).toBe(6);
    expect(screen.getByText("Chuyên viên QHKH")).toBeInTheDocument();
    expect(screen.getByText("7 năm")).toBeInTheDocument();
  });

  it("tên ứng viên và trích dẫn trong ô của bảng vẫn giữ tương tác liên kết và nút", () => {
    const tableWithLinksAndCite = `
| Ứng viên | Ghi chú |
| --- | --- |
| **Nguyễn An** [1] | Phù hợp vị trí QHKH |
| **Trần Thị Lan Anh** [2] | Cần phỏng vấn thêm |
`.trim();

    render(
      <MemoryRouter>
        <FormattedMarkdown
          content={tableWithLinksAndCite}
          people={PEOPLE}
          onCitation={() => undefined}
        />
      </MemoryRouter>,
    );

    // Kiểm tra tên Nguyễn An thành link tới /person/7
    const link1 = screen.getByRole("link", { name: "Nguyễn An" });
    expect(link1).toHaveAttribute("href", "/person/7?from=talent-ai");

    // Kiểm tra citation [1] thành nút bấm
    const cite1 = screen.getByRole("button", { name: "1" });
    expect(cite1).toBeInTheDocument();

    // Kiểm tra tên Trần Thị Lan Anh thành link tới /person/9
    const link2 = screen.getByRole("link", { name: "Trần Thị Lan Anh" });
    expect(link2).toHaveAttribute("href", "/person/9?from=talent-ai");

    // Kiểm tra citation [2] thành nút bấm
    const cite2 = screen.getByRole("button", { name: "2" });
    expect(cite2).toBeInTheDocument();
  });
});

