# -*- coding: utf-8 -*-
"""Nhánh CÂU LỆNH của Growth — "soạn tin cho 3 khách đầu", "tạo cơ hội cho cả danh sách".

## Vì sao không dùng vòng lặp agent như Talent

`talent/answer/act.py` đưa câu lệnh vào `ai/agent.py`: model tự chọn tool nào,
gọi mấy lần, cho ai. Ở Growth điều đó đi ngược đúng nguyên tắc mà cả gói
`rb/answer/` đứng trên — *chọn hành động là chuyện nghiệp vụ, không phải chuyện
ngôn ngữ*. Hơn nữa tool `draft_outreach` hiện có đòi quyền module Talent và đọc
dữ kiện tuyển dụng: RM thuần không gọi được, và gọi được thì viết sai giọng.

Nên ở đây mọi thứ quyết định bằng CODE:

    động từ     nhận bằng quy tắc từ khoá — một tập đóng, liệt kê được, test được
    đối tượng   đúng những khách ở lượt trước, theo đúng thứ tự đã hiển thị
    thực thi    `rb/outreach.draft` (cùng hàm nút "Soạn tin" đang dùng) và cùng
                luật tạo cơ hội của `rb/views.py::opportunity_list`

LLM chỉ còn ở một chỗ: viết lời trong bản nháp, qua đúng `rb/outreach.draft`.

## Ranh giới

* **Soạn** chỉ tạo BẢN NHÁP. Không có đường nào ở đây nhắn cho khách — "AI soạn,
  người bấm gửi", cùng ranh giới với `rb/outreach.py`.
* **Tạo cơ hội** là ghi dữ liệu nội bộ, tương đương RM bấm nút "Tạo cơ hội" trên
  từng thẻ — nút đó cũng không hỏi lại. Nhưng có ba chốt mà nút tay không cần vì
  người bấm nhìn thấy từng khách: không tạo trùng cơ hội đang mở, không tạo cho
  khách `do_not_contact`, và giới hạn số lượng một lần.
* **Không đoán đối tượng.** Không có danh sách lượt trước, hoặc số thứ tự vượt
  quá danh sách, thì HỎI LẠI. Soạn tin cho nhầm người là lỗi không rút lại được
  một khi RM đã bấm gửi.
"""
from __future__ import annotations

import logging
import re

from django.db import IntegrityError, transaction

log = logging.getLogger(__name__)

VERB_MESSAGE = "draft_message"
VERB_CALL_SCRIPT = "draft_call_script"
VERB_CREATE = "create_opportunity"
VERB_SUGGEST_PRODUCT = "suggest_product"

#: Số khách tối đa mỗi câu lệnh. Soạn nháp là một lượt gọi model mỗi khách;
#: tạo cơ hội hàng loạt quá lớn từ một câu chat thì RM không kịp soát.
MAX_DRAFTS = 5
MAX_CREATE = 10

SUPPORTED_TEXT = ("Mình làm được: **soạn tin nhắn**, **soạn kịch bản gọi**, **tạo "
                  "cơ hội** (trên nhóm khách vừa tìm được), và **gợi ý sản phẩm** "
                  "từ một câu mô tả nhu cầu. Ví dụ: \"soạn tin cho 3 khách đầu\", "
                  "\"tạo cơ hội cho cả danh sách\", \"khách bảo đang tính mua ô tô "
                  "trả góp thì gợi ý sản phẩm gì\".")


def _fold(text):
    from people.normalize import normalize_name
    return normalize_name(text or "")


def detect_verb(question):
    """Động từ của câu lệnh, hoặc None. Tập đóng, quyết định bằng quy tắc.

    Thứ tự kiểm tra có chủ ý: "gợi ý sản phẩm" trước tất cả — cụm từ của nó
    không đụng ba động từ kia nên thứ tự không quan trọng, đặt đầu cho dễ đọc;
    "tạo cơ hội" trước, vì "soạn" có thể xuất hiện trong ghi chú ("tạo cơ hội
    rồi soạn sau"); "kịch bản gọi" trước "tin nhắn", vì "soạn kịch bản gọi"
    cũng chứa chữ "soạn".
    """
    text = _fold(question)
    if (re.search(r"\b(goi y|tu van)\b.*\bsan pham\b", text)
            or re.search(r"\bsan pham nao (?:thi )?(?:phu hop|nen chao)\b", text)
            or re.search(r"\bnen chao (?:san pham )?gi\b", text)):
        return VERB_SUGGEST_PRODUCT
    if re.search(r"\b(tao|mo|lap)\s+(\w+\s+)?co hoi\b", text):
        return VERB_CREATE
    if re.search(r"\bkich ban\b", text) or re.search(r"\b(soan|viet)\b.*\bgoi\b", text):
        return VERB_CALL_SCRIPT
    if re.search(r"\b(soan|viet|nhap)\b", text) and re.search(
            r"\b(tin|tin nhan|thu|loi chao|zalo|sms|email|noi dung)\b", text):
        return VERB_MESSAGE
    return None


_NUMBERS = {"mot": 1, "hai": 2, "ba": 3, "bon": 4, "tu": 4, "nam": 5, "sau": 6,
            "bay": 7, "tam": 8, "chin": 9, "muoi": 10}
_WHO = r"(?:khach hang|khach|nguoi|ho so)"


def _number(token):
    return int(token) if token.isdigit() else _NUMBERS.get(token)


def last_result_items(projection):
    """`[{id, name, product, why}]` của lượt trước, đúng thứ tự đã hiển thị."""
    if projection is None:
        return []
    last = dict(getattr(projection, "last_result", None) or {})
    out = []
    for item in (last.get("items") or last.get("people") or []):
        pid = item.get("id") or item.get("person_id")
        if pid:
            out.append({"id": int(pid), "name": str(item.get("name") or ""),
                        "product": str(item.get("product") or ""),
                        "why": str(item.get("why") or "")})
    return out


def resolve_targets(items, question):
    """Chọn khách trong `items` theo câu lệnh.

    Trả `list` (có thể rỗng khi số thứ tự vượt danh sách) hoặc `None` khi câu
    lệnh KHÔNG chỉ rõ ai — người gọi phải hỏi lại chứ không được tự chọn.
    """
    text = _fold(question)
    tok = r"(\d+|mot|hai|ba|bon|tu|nam|sau|bay|tam|chin|muoi)"

    # "khách thứ 2", "khách số 3"
    match = re.search(_WHO + r"\s+(?:thu|so)\s+" + tok + r"\b", text)
    if match:
        n = _number(match.group(1))
        return items[n - 1:n] if n and 1 <= n <= len(items) else []

    # "3 khách đầu", "ba người đầu tiên", "5 khách trên cùng"
    match = re.search(tok + r"\s+" + _WHO + r"\s+(?:dau|tren|dung dau)", text)
    if match:
        n = _number(match.group(1))
        return items[:n] if n and 1 <= n <= len(items) else []

    # "khách đầu tiên", "người đầu"
    if re.search(_WHO + r"\s+dau(?:\s+tien)?\b", text):
        return items[:1]

    # "cả danh sách", "tất cả", "những khách trên", "nhóm này"
    if re.search(r"\b(?:ca danh sach|tat ca|toan bo|ca nhom|nhom (?:nay|do|tren)"
                 r"|danh sach (?:tren|nay|vua roi))\b", text) or re.search(
                     r"\bnhung " + _WHO + r"\s+(?:tren|nay|do)\b", text):
        return list(items)

    # Gọi đích danh theo tên có trong danh sách.
    named = [item for item in items
             if item["name"] and _fold(item["name"]) in text]
    if named:
        return named
    return None


def _blocked_ids(person_ids):
    from people.models import Relationship, Signal
    return set(Relationship.objects.filter(
        person_id__in=person_ids, domain=Signal.DOMAIN_RB,
        do_not_contact=True).values_list("person_id", flat=True))


def _product_for(person, preferred):
    """Sản phẩm để soạn/tạo. Ưu tiên cái ④ đã chọn ở lượt trước.

    Không có thì lấy quan tâm tin cậy cao nhất. Không có nốt thì trả "" và người
    gọi BỎ QUA khách đó — soạn tin mời vay cho người chưa từng có dấu hiệu gì là
    đúng kiểu "nhắc tới khoản vay khách chưa hề đề cập" mà `rb/outreach.py` cấm.
    """
    from ..models import PRODUCT_CHOICES
    valid = {code for code, _ in PRODUCT_CHOICES}
    if preferred in valid:
        return preferred
    profile = getattr(person, "rb_profile", None)
    if profile is not None:
        best = profile.interests.order_by("-confidence").first()
        if best is not None:
            return best.product
    return ""


def _draft_one(person, product, why, channel):
    from .. import outreach
    from ..models import RBOpportunity

    opportunity = (RBOpportunity.objects
                   .filter(person=person, product=product,
                           status__in=RBOpportunity.OPEN_STATUSES)
                   .order_by("-created_at").first())
    if opportunity is None:
        # KHÔNG lưu. Soạn nháp không được lặng lẽ sinh ra một cơ hội trong Hộp
        # thư của RM — đó là việc của câu lệnh "tạo cơ hội", có chốt riêng.
        opportunity = RBOpportunity(person=person, product=product, need=why[:300])
    text, error = outreach.draft(opportunity, channel=channel)
    return text, error, opportunity.pk


def _create_one(person, product, why, user, question):
    from ..models import RBOpportunity

    existing = RBOpportunity.objects.filter(
        person=person, product=product, status__in=RBOpportunity.OPEN_STATUSES).first()
    if existing is not None:
        return None, existing.pk
    try:
        with transaction.atomic():
            row = RBOpportunity.objects.create(
                person=person, product=product, need=why[:300],
                assigned_to=user if getattr(user, "pk", None) else None,
                assigned_to_name=(str(user)[:150] if getattr(user, "pk", None) else ""),
                evidence={"source": "growth_answer_command", "command": question[:300]})
    except IntegrityError:
        existing = RBOpportunity.objects.filter(
            person=person, product=product,
            status__in=RBOpportunity.OPEN_STATUSES).first()
        return None, getattr(existing, "pk", None)
    return row.pk, None


def run(question, *, envelope=None, user=None):
    """Thực thi câu lệnh. Trả dict: `text`, `people`, `actions`, `mode`."""
    from people.models import Person
    from ..models import PRODUCT_LABELS
    from .. import outreach

    verb = detect_verb(question)
    if verb is None:
        return {"mode": "action_unsupported", "text": SUPPORTED_TEXT,
                "people": [], "actions": []}
    if verb == VERB_SUGGEST_PRODUCT:
        # Không cần danh sách khách của lượt trước — đây là suy đoán từ một câu
        # mô tả nhu cầu tự do (RM chép lại lời khách vừa nói), không phải hành
        # động trên người đã tìm được.
        return _suggest_product(question)

    projection = getattr(envelope, "projection", None)
    items = last_result_items(projection)
    if not items:
        return {"mode": "action_needs_list", "people": [], "actions": [],
                "text": ("Mình chưa có nhóm khách nào để làm việc này. Anh/chị tìm "
                         "khách trước (ví dụ \"khách nào cần vay mua xe\"), rồi bảo "
                         "mình soạn tin hay tạo cơ hội cho những khách trong kết quả.")}

    targets = resolve_targets(items, question)
    if targets is None:
        names = ", ".join(f"{i}. {item['name']}" for i, item in enumerate(items[:10], 1))
        return {"mode": "action_needs_target", "people": [], "actions": [],
                "text": ("Anh/chị muốn làm cho khách nào ạ? Danh sách vừa rồi: "
                         f"{names}. Ví dụ: \"cho 3 khách đầu\" hoặc \"cho cả danh sách\".")}
    if not targets:
        return {"mode": "action_needs_target", "people": [], "actions": [],
                "text": (f"Danh sách vừa rồi chỉ có {len(items)} khách, không có vị trí "
                         "đó. Anh/chị chọn lại giúp mình.")}

    cap = MAX_CREATE if verb == VERB_CREATE else MAX_DRAFTS
    over_cap = max(0, len(targets) - cap)
    targets = targets[:cap]

    ids = [t["id"] for t in targets]
    blocked = _blocked_ids(ids)
    persons = {p.pk: p for p in Person.objects.filter(pk__in=ids, merged_into__isnull=True)
               .select_related("rb_profile")}

    actions, lines, people = [], [], []
    for target in targets:
        person = persons.get(target["id"])
        name = target["name"] or (person.display_name if person else f"#{target['id']}")
        base = {"person_id": target["id"], "name": name}
        if person is None:
            actions.append({**base, "status": "missing"})
            lines.append(f"- **{name}**: không còn tìm thấy hồ sơ, bỏ qua.")
            continue
        if person.pk in blocked:
            # Kể cả câu lệnh đích danh. Ràng buộc tuân thủ, không phải bộ lọc.
            actions.append({**base, "status": "do_not_contact"})
            lines.append(f"- **{name}**: khách đã yêu cầu không liên hệ — bỏ qua.")
            continue
        product = _product_for(person, target["product"])
        if not product:
            actions.append({**base, "status": "no_product"})
            lines.append(f"- **{name}**: chưa rõ sản phẩm phù hợp, bỏ qua để không "
                         "nhắc tới nhu cầu khách chưa hề đề cập.")
            continue
        label = PRODUCT_LABELS.get(product, product)
        people.append({**base, "product": product, "why": target["why"]})

        if verb == VERB_CREATE:
            created, existing = _create_one(person, product, target["why"], user, question)
            if created:
                actions.append({**base, "status": "created", "product": product,
                                "opportunity_id": created})
                lines.append(f"- **{name}** — {label}: đã tạo cơ hội #{created}.")
            else:
                actions.append({**base, "status": "exists", "product": product,
                                "opportunity_id": existing})
                lines.append(f"- **{name}** — {label}: đã có cơ hội đang mở"
                             f"{f' #{existing}' if existing else ''}, không tạo trùng.")
            continue

        channel = (outreach.CHANNEL_CALL_SCRIPT if verb == VERB_CALL_SCRIPT
                   else outreach.CHANNEL_MESSAGE)
        text, error, opportunity_id = _draft_one(person, product, target["why"], channel)
        actions.append({**base, "status": "drafted", "product": product, "channel": channel,
                        "draft": text, "error": error, "opportunity_id": opportunity_id})
        note = " *(mô hình bận — đây là khung để anh/chị viết tiếp)*" if error else ""
        quoted = "\n".join(f"> {row}" if row else ">" for row in text.splitlines())
        lines.append(f"**{name}** — {label}{note}\n\n{quoted}")

    if verb == VERB_CREATE:
        created = sum(1 for a in actions if a["status"] == "created")
        head = f"Đã tạo {created} cơ hội, giao cho anh/chị phụ trách:"
        body = "\n".join(lines)
    else:
        kind = "kịch bản gọi" if verb == VERB_CALL_SCRIPT else "tin nhắn"
        drafted = sum(1 for a in actions if a["status"] == "drafted")
        head = (f"Đã soạn {drafted} bản nháp {kind}. **Chưa gửi cho ai** — anh/chị "
                "đọc, sửa rồi tự gửi:")
        body = "\n\n".join(lines)
    tail = (f"\n\n*Mỗi lần làm tối đa {cap} khách; còn {over_cap} khách chưa làm — "
            "anh/chị bảo tiếp cho nhóm sau.*" if over_cap else "")
    return {"mode": verb, "text": f"{head}\n\n{body}{tail}", "people": people,
            "actions": actions}


def _suggest_product(question):
    """Gợi ý nhóm sản phẩm từ MỘT câu mô tả nhu cầu tự do. Tất định, không LLM.

    Dùng đúng `rb.routing.suggest_products` — thuật toán dò cụm từ mà
    `rb/agent.py` đã dùng để tự gắn `ProductInterest` khi có tín hiệu mới. Ở
    đây là bản RM tự gõ ngay trong chat một câu khách vừa nói ("khách bảo đang
    tính mua ô tô trả góp") để biết ngay nên chào gì, không phải đợi tín hiệu
    tự động sinh ra rồi mới thấy trong hồ sơ.

    Không cần danh sách khách của lượt trước, và không tạo/sửa gì — gợi ý
    xong là hết việc, khác hẳn `create_opportunity`.
    """
    from .. import routing
    from ..models import PRODUCT_LABELS

    suggestions = routing.suggest_products(question)
    if not suggestions:
        text = ("Chưa thấy cụm từ nào để gợi ý sản phẩm. Anh/chị mô tả cụ thể nhu "
                "cầu khách vừa nói giúp mình (ví dụ \"khách bảo đang tính mua ô tô "
                "trả góp\") ạ.")
    else:
        lines = [f"- **{PRODUCT_LABELS.get(s.product, s.product)}** — {s.need} "
                 f"(khớp: {', '.join(s.matched)}; tin cậy {s.confidence:.0%})"
                 for s in suggestions]
        text = ("Gợi ý sản phẩm dựa trên câu vừa mô tả (dò cụm từ tất định, KHÔNG "
                "phải đánh giá tín dụng hay cam kết lãi suất):\n\n" + "\n".join(lines))
    return {"mode": VERB_SUGGEST_PRODUCT, "text": text, "people": [], "actions": []}
