import React from "react";
import { Link } from "react-router-dom";

/** Một người trong kho mà câu trả lời có thể nhắc tới. */
export interface LinkablePerson {
  personId: number;
  name: string;
}

interface Props {
  content: string;
  className?: string;
  /**
   * Tên những người này, hễ xuất hiện trong câu chữ, thành liên kết mở thẳng hồ
   * sơ — cùng đích với chip ở "Hồ sơ được nhắc tới". Trước đây muốn mở hồ sơ
   * người vừa đọc tên trong câu, người dùng phải rà xuống cuối bài tìm lại chip.
   */
  people?: LinkablePerson[];
  /**
   * Có hàm này thì `[n]` trong văn bản thành nút bấm được, mở đúng đoạn CV gốc.
   * Trích dẫn phải nằm NGAY trong câu chữ chứ không chỉ ở danh sách nguồn cuối
   * bài — người đọc kiểm chứng ngay tại chỗ họ đang nghi ngờ.
   */
  onCitation?: (n: number) => void;
}

/** Hàm mở nguồn, luồn xuống các hàm render inline (không phải component nên
 *  không dùng được hook/context ở đó). */
type CiteHandler = ((n: number) => void) | undefined;

/** Bộ dò tên đã dựng sẵn, luồn xuống các hàm render inline như `CiteHandler`. */
type NameMatcher = { regex: RegExp; byName: Map<string, number> } | undefined;

/** Ký tự chữ (có dấu tiếng Việt) — dùng để chặn khớp giữa chừng một từ. */
const LETTER = /\p{L}/u;

/**
 * Dựng MỘT regex cho mọi tên cần gắn liên kết.
 *
 * Tên dài xếp trước để "Nguyễn Văn An" không bị "Nguyễn Văn" nuốt mất phần đuôi
 * — `RegExp` chọn nhánh khớp đầu tiên chứ không chọn nhánh dài nhất.
 */
function buildNameMatcher(people?: LinkablePerson[]): NameMatcher {
  const byName = new Map<string, number>();
  for (const person of people ?? []) {
    const name = String(person?.name ?? "").trim();
    if (name.length >= 3 && Number.isFinite(person?.personId)) {
      byName.set(name.toLowerCase(), person.personId);
    }
  }
  if (byName.size === 0) return undefined;
  const names = [...byName.keys()].sort((a, b) => b.length - a.length);
  const escaped = names.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return { regex: new RegExp(`(${escaped.join("|")})`, "giu"), byName };
}

/**
 * Cắt một đoạn chữ thuần thành các mảnh, tên người thành `<Link>`.
 *
 * Chỉ khớp khi hai đầu KHÔNG phải chữ cái: "An" trong "Ánh" hay "Lan Anh" không
 * được biến thành liên kết tới một người khác.
 */
function linkNames(text: string, matcher: NameMatcher, keyBase: string): React.ReactNode {
  if (!matcher || !text) return text;
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  matcher.regex.lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = matcher.regex.exec(text)) !== null) {
    const before = text[match.index - 1];
    const after = text[match.index + match[0].length];
    if ((before && LETTER.test(before)) || (after && LETTER.test(after))) continue;

    const personId = matcher.byName.get(match[0].toLowerCase());
    if (personId === undefined) continue;

    if (match.index > lastIndex) {
      parts.push(
        <React.Fragment key={`${keyBase}-txt-${match.index}`}>
          {text.slice(lastIndex, match.index)}
        </React.Fragment>
      );
    }
    parts.push(
      <Link
        key={`${keyBase}-name-${match.index}`}
        to={`/person/${personId}?from=talent-ai`}
        className="chat-person-link"
        title="Mở hồ sơ"
      >
        {match[0]}
      </Link>
    );
    lastIndex = match.index + match[0].length;
  }

  if (parts.length === 0) return text;
  if (lastIndex < text.length) {
    parts.push(
      <React.Fragment key={`${keyBase}-txt-tail`}>
        {text.slice(lastIndex)}
      </React.Fragment>
    );
  }
  return <>{parts}</>;
}

/**
 * Trình render Markdown & Rich Text chuyên dụng cho AI Chatbot Radar.
 * Phân tích và hiển thị đẹp mắt: xuống dòng, danh sách gạch đầu dòng, chữ in đậm,
 * tiêu đề, khối mã (code block), trích dẫn và bảng biểu.
 */
export default function FormattedMarkdown({ content, className = "", people, onCitation }: Props) {
  // Đặt TRƯỚC `if (!content)`: hook không được đứng sau một nhánh return.
  const matcher = React.useMemo(() => buildNameMatcher(people), [people]);
  if (!content) return null;

  const rawText = String(content || "");

  // Phân tích khối mã ```code``` trước
  const parts = splitCodeBlocks(rawText);

  return (
    <div className={`formatted-markdown ${className}`}>
      {parts.map((part, pIdx) => {
        if (part.type === "code") {
          return (
            <div key={`block-${pIdx}`} className="chat-code-block-wrapper">
              {part.lang && <div className="chat-code-lang">{part.lang}</div>}
              <pre className="chat-code-block">
                <code>{part.content}</code>
              </pre>
            </div>
          );
        }

        // Tách các đoạn văn theo 2 dấu xuống dòng hoặc các khối danh sách/tiêu đề
        const sections = parseTextSections(part.content);

        return (
          <React.Fragment key={`text-part-${pIdx}`}>
            {sections.map((sec, sIdx) => {
              if (sec.type === "heading") {
                const Tag = `h${sec.level}` as keyof JSX.IntrinsicElements;
                return (
                  <Tag key={`sec-${sIdx}`} className={`chat-heading chat-h${sec.level}`}>
                    {renderInline(sec.text, onCitation, matcher)}
                  </Tag>
                );
              }

              if (sec.type === "blockquote") {
                return (
                  <blockquote key={`sec-${sIdx}`} className="chat-blockquote">
                    {renderInline(sec.text, onCitation, matcher)}
                  </blockquote>
                );
              }

              if (sec.type === "list") {
                return (
                  <ul key={`sec-${sIdx}`} className="chat-list">
                    {sec.items.map((item, iIdx) => (
                      <li key={`item-${iIdx}`} className="chat-list-item">
                        {renderInline(item, onCitation, matcher)}
                      </li>
                    ))}
                  </ul>
                );
              }

              if (sec.type === "ordered-list") {
                return (
                  <ol key={`sec-${sIdx}`} className="chat-ordered-list">
                    {sec.items.map((item, iIdx) => (
                      <li key={`item-${iIdx}`} className="chat-list-item">
                        {renderInline(item, onCitation, matcher)}
                      </li>
                    ))}
                  </ol>
                );
              }

              if (sec.type === "table") {
                return (
                  <div key={`sec-${sIdx}`} className="chat-table-container">
                    <table className="chat-table">
                      <thead>
                        <tr>
                          {sec.headers.map((head, hIdx) => (
                            <th
                              key={`th-${hIdx}`}
                              style={{ textAlign: sec.alignments[hIdx] || "left" }}
                            >
                              {renderInline(head, onCitation, matcher)}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {sec.rows.map((row, rIdx) => (
                          <tr key={`tr-${rIdx}`}>
                            {row.map((cell, cIdx) => (
                              <td
                                key={`td-${cIdx}`}
                                style={{ textAlign: sec.alignments[cIdx] || "left" }}
                              >
                                {renderInline(cell, onCitation, matcher)}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                );
              }

              // Đoạn văn thông thường
              return (
                <p key={`sec-${sIdx}`} className="chat-paragraph">
                  {renderInlineWithLineBreaks(sec.text, onCitation, matcher)}
                </p>
              );
            })}
          </React.Fragment>
        );
      })}
    </div>
  );
}

// ---------------- Helper Functions ----------------

interface CodePart {
  type: "code" | "text";
  content: string;
  lang?: string;
}

function splitCodeBlocks(text: string): CodePart[] {
  const parts: CodePart[] = [];
  const regex = /```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: "text", content: text.slice(lastIndex, match.index) });
    }
    parts.push({
      type: "code",
      lang: match[1] || "",
      content: match[2].trimEnd(),
    });
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push({ type: "text", content: text.slice(lastIndex) });
  }

  return parts;
}

interface TableSection {
  type: "table";
  text: string;
  items: string[];
  headers: string[];
  alignments: ("left" | "center" | "right")[];
  rows: string[][];
}

type Section =
  | {
      type: "paragraph" | "heading" | "list" | "ordered-list" | "blockquote";
      text: string;
      level?: number;
      items: string[];
    }
  | TableSection;

function splitTableRow(line: string): string[] {
  let trimmed = line.trim();
  if (trimmed.startsWith("|")) trimmed = trimmed.slice(1);
  if (trimmed.endsWith("|")) trimmed = trimmed.slice(0, -1);
  const cells: string[] = [];
  let current = "";
  let escaped = false;
  for (let i = 0; i < trimmed.length; i++) {
    const char = trimmed[i];
    if (char === "\\" && !escaped) {
      escaped = true;
      current += char;
    } else if (char === "|" && !escaped) {
      cells.push(current.trim());
      current = "";
    } else {
      current += char;
      escaped = false;
    }
  }
  cells.push(current.trim());
  return cells;
}

function parseAlignment(cell: string): "left" | "center" | "right" {
  const trimmed = cell.trim();
  const left = trimmed.startsWith(":");
  const right = trimmed.endsWith(":");
  if (left && right) return "center";
  if (right) return "right";
  return "left";
}

function isTableSeparator(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed.includes("-") || !trimmed.includes("|")) return false;
  let inner = trimmed;
  if (inner.startsWith("|")) inner = inner.slice(1);
  if (inner.endsWith("|")) inner = inner.slice(0, -1);
  const parts = inner.split("|");
  if (parts.length === 0) return false;
  return parts.every((part) => /^\s*:?-+:?\s*$/.test(part));
}

function parseTextSections(raw: string): Section[] {
  const lines = raw.split("\n");
  const sections: Section[] = [];
  let currentParagraph: string[] = [];
  let currentList: { type: "list" | "ordered-list"; items: string[] } | null = null;

  const flushParagraph = () => {
    if (currentParagraph.length > 0) {
      const text = currentParagraph.join("\n").trim();
      if (text) {
        sections.push({ type: "paragraph", text, items: [] });
      }
      currentParagraph = [];
    }
  };

  const flushList = () => {
    if (currentList && currentList.items.length > 0) {
      sections.push({
        type: currentList.type,
        text: "",
        items: currentList.items,
      });
      currentList = null;
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // Dòng trống -> kết thúc đoạn văn hoặc danh sách hiện tại
    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }

    // Bảng biểu: dòng hiện tại chứa | và dòng kế tiếp là đường phân cách (| --- | --- |)
    if (trimmed.includes("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      flushParagraph();
      flushList();

      const headers = splitTableRow(lines[i]);
      const alignRow = splitTableRow(lines[i + 1]);
      const alignments = headers.map((_, idx) =>
        alignRow[idx] ? parseAlignment(alignRow[idx]) : "left",
      );

      const rows: string[][] = [];
      i += 2;
      while (i < lines.length) {
        const rowLine = lines[i];
        const rowTrimmed = rowLine.trim();
        if (!rowTrimmed || !rowTrimmed.includes("|")) {
          i--;
          break;
        }
        const rawCells = splitTableRow(rowLine);
        const row = headers.map((_, idx) => (rawCells[idx] !== undefined ? rawCells[idx] : ""));
        rows.push(row);
        i++;
      }

      sections.push({
        type: "table",
        text: "",
        items: [],
        headers,
        alignments,
        rows,
      });
      continue;
    }

    // Tiêu đề: # Heading, ## Heading, ### Heading
    const headingMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      sections.push({
        type: "heading",
        level: headingMatch[1].length,
        text: headingMatch[2],
        items: [],
      });
      continue;
    }

    // Trích dẫn: > Quote
    const quoteMatch = trimmed.match(/^>\s*(.+)$/);
    if (quoteMatch) {
      flushParagraph();
      flushList();
      sections.push({
        type: "blockquote",
        text: quoteMatch[1],
        items: [],
      });
      continue;
    }

    // Gạch đầu dòng: - item, * item, • item
    const bulletMatch = trimmed.match(/^[-*•]\s+(.+)$/);
    if (bulletMatch) {
      flushParagraph();
      if (!currentList || currentList.type !== "list") {
        flushList();
        currentList = { type: "list", items: [] };
      }
      currentList.items.push(bulletMatch[1]);
      continue;
    }

    // Danh sách đánh số: 1. item, 2. item
    const orderedMatch = trimmed.match(/^\d+\.\s+(.+)$/);
    if (orderedMatch) {
      flushParagraph();
      if (!currentList || currentList.type !== "ordered-list") {
        flushList();
        currentList = { type: "ordered-list", items: [] };
      }
      currentList.items.push(orderedMatch[1]);
      continue;
    }

    // Dòng văn bản thông thường
    if (currentList) {
      // Nếu dòng thụt lề tiếp tục của list item trước
      if (line.startsWith("  ") || line.startsWith("\t")) {
        const lastIdx = currentList.items.length - 1;
        if (lastIdx >= 0) {
          currentList.items[lastIdx] += " " + trimmed;
          continue;
        }
      }
      flushList();
    }

    currentParagraph.push(trimmed);
  }

  flushParagraph();
  flushList();

  return sections;
}

function renderInlineWithLineBreaks(text: string, onCitation?: CiteHandler,
                                    matcher?: NameMatcher): React.ReactNode {
  const lines = text.split("\n");
  if (lines.length <= 1) {
    return renderInline(text, onCitation, matcher);
  }
  return (
    <>
      {lines.map((line, idx) => (
        <React.Fragment key={idx}>
          {renderInline(line, onCitation, matcher)}
          {idx < lines.length - 1 && <br />}
        </React.Fragment>
      ))}
    </>
  );
}

/**
 * Phân tích các định dạng inline: **in đậm**, *in nghiêng*, `code`, [link](url),
 * và trích dẫn [n] khi có `onCitation`.
 */
function renderInline(text: string, onCitation?: CiteHandler,
                      matcher?: NameMatcher): React.ReactNode {
  if (!text) return "";

  // Regex bắt token: **bold**, `code`, [link](url), trích dẫn, *italic*.
  //
  // Trích dẫn nhận cả dạng đơn `[3]` lẫn dạng GỘP `[1,2]` / `[7, 8]` — model
  // viết gộp rất thường xuyên, và nếu chỉ bắt `[n]` thì người đọc thấy `[1,2]`
  // là chữ thường, bấm không được.
  // Nhánh này phải đứng SAU [link](url) và có `(?!\()` để không nuốt mất phần
  // mở đầu của một liên kết markdown.
  const tokenRegex = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|\[\d{1,2}(?:\s*,\s*\d{1,2})*\](?!\()|\*[^*]+\*)/g;
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = tokenRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(
        <React.Fragment key={`plain-${match.index}`}>
          {linkNames(text.slice(lastIndex, match.index), matcher, `plain-${match.index}`)}
        </React.Fragment>
      );
    }

    const token = match[0];
    const key = `inline-${match.index}`;

    if (token.startsWith("**") && token.endsWith("**")) {
      parts.push(
        <strong key={key} className="chat-bold">
          {linkNames(token.slice(2, -2), matcher, `${key}-b`)}
        </strong>
      );
    } else if (token.startsWith("`") && token.endsWith("`")) {
      parts.push(
        <code key={key} className="chat-inline-code">
          {token.slice(1, -1)}
        </code>
      );
    } else if (/^\[\d{1,2}(?:\s*,\s*\d{1,2})*\]$/.test(token)) {
      // `[1,2]` thành HAI nút riêng: mỗi số là một nguồn khác nhau, gộp chúng
      // vào một nút thì người đọc chỉ mở được nguồn đầu.
      const numbers = token.slice(1, -1).split(",").map((n) => Number(n.trim()));
      parts.push(
        onCitation ? (
          <span key={key} className="inline-citation-group">
            {numbers.map((number, i) => (
              <button
                key={`${key}-${i}`}
                type="button"
                className="inline-citation"
                title="Xem đoạn CV gốc"
                onClick={() => onCitation(number)}
              >
                {number}
              </button>
            ))}
          </span>
        ) : (
          <React.Fragment key={key}>{token}</React.Fragment>
        )
      );
    } else if (token.startsWith("[") && token.includes("](")) {
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (linkMatch) {
        parts.push(
          <a
            key={key}
            href={linkMatch[2]}
            target="_blank"
            rel="noopener noreferrer"
            className="chat-link"
          >
            {linkMatch[1]}
          </a>
        );
      } else {
        parts.push(<React.Fragment key={key}>{token}</React.Fragment>);
      }
    } else if (token.startsWith("*") && token.endsWith("*")) {
      parts.push(
        <em key={key} className="chat-italic">
          {linkNames(token.slice(1, -1), matcher, `${key}-i`)}
        </em>
      );
    } else {
      parts.push(<React.Fragment key={key}>{token}</React.Fragment>);
    }

    lastIndex = tokenRegex.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(
      <React.Fragment key={`plain-${lastIndex}`}>
        {linkNames(text.slice(lastIndex), matcher, `plain-${lastIndex}`)}
      </React.Fragment>
    );
  }

  return parts.length === 1 ? parts[0] : parts;
}
