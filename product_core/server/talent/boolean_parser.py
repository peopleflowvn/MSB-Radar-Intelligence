# -*- coding: utf-8 -*-
"""Bộ phân tích cú pháp Boolean Search cho Tuyển dụng (Master Plan mục 19.3, 43).

Hỗ trợ:
- Toán tử logic: AND, OR, NOT (hoặc tiền tố -)
- Cụm từ chính xác: "Senior Developer", "Tech Lead"
- Nhóm ưu tiên dấu ngoặc đơn: (Python OR Java) AND (Backend OR "Full Stack") NOT Intern
"""
import re
from typing import List, Union
from django.db.models import Q


class BooleanQueryParser:
    """Chuyển đổi chuỗi truy vấn Boolean Search thành Django Q object."""

    TOKEN_RE = re.compile(
        r'(\band\b|\bor\b|\bnot\b|[()"]|-[^\s()]+|[^\s()"]+)',
        re.IGNORECASE
    )

    @classmethod
    def tokenize(cls, query_str: str) -> List[str]:
        tokens = []
        in_quotes = False
        current_phrase = []

        raw_tokens = cls.TOKEN_RE.findall(query_str.strip())
        for token in raw_tokens:
            if token == '"':
                if in_quotes:
                    # Đóng ngoặc kép
                    if current_phrase:
                        tokens.append('"' + " ".join(current_phrase) + '"')
                        current_phrase = []
                    in_quotes = False
                else:
                    # Mở ngoặc kép
                    in_quotes = True
            elif in_quotes:
                current_phrase.append(token)
            else:
                tokens.append(token)

        if in_quotes and current_phrase:
            tokens.append('"' + " ".join(current_phrase) + '"')

        return tokens

    @classmethod
    def has_syntax(cls, query_str: str) -> bool:
        return bool(re.search(r'\b(?:AND|OR|NOT)\b|[()"]|(?:^|\s)-\S', query_str,
                              re.IGNORECASE))

    @classmethod
    def parse_to_q(cls, query_str: str, target_fields: Union[str, List[str]],
                   whole_words: bool = False) -> Q:
        """Phân tích cú pháp và trả về Django Q object cho các trường target_fields."""
        if not query_str or not query_str.strip():
            return Q()

        depth = 0
        for char in query_str:
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
            if depth < 0:
                return Q(pk__isnull=True)
        if depth or query_str.count('"') % 2:
            return Q(pk__isnull=True)

        if isinstance(target_fields, str):
            fields = [target_fields]
        else:
            fields = list(target_fields)

        tokens = cls.tokenize(query_str)
        if not tokens:
            return Q()

        def make_field_q(term: str) -> Q:
            # Bỏ ngoặc kép nếu có
            is_exact = False
            clean_term = term.strip()
            if clean_term.startswith('"') and clean_term.endswith('"') and len(clean_term) >= 2:
                clean_term = clean_term[1:-1].strip()
                is_exact = True

            if not clean_term:
                return Q()

            field_q = Q()
            for f in fields:
                if whole_words and not is_exact:
                    pattern = r"\b" + re.escape(clean_term) + r"\b"
                    field_q |= Q(**{f"{f}__iregex": pattern})
                else:
                    field_q |= Q(**{f"{f}__icontains": clean_term})
            return field_q

        # Shunting-yard algorithm để phân tích biểu thức logic sang RPN (Reverse Polish Notation)
        precedence = {'NOT': 3, 'AND': 2, 'OR': 1}
        output_queue = []
        operator_stack = []

        # Chuẩn hoá và chèn toán tử AND ngầm định nếu hai token liền kề không có toán tử
        processed_tokens = []
        for i, tok in enumerate(tokens):
            upper_tok = tok.upper()
            if tok.startswith('-') and len(tok) > 1 and not upper_tok.startswith('-NOT'):
                # -term chuyển thành NOT term
                processed_tokens.append('NOT')
                processed_tokens.append(tok[1:])
            else:
                if upper_tok in ('AND', 'OR', 'NOT'):
                    processed_tokens.append(upper_tok)
                elif tok in ('(', ')'):
                    processed_tokens.append(tok)
                else:
                    processed_tokens.append(tok)

        # Chèn AND ngầm định
        implicit_tokens = []
        for i, tok in enumerate(processed_tokens):
            if i > 0:
                prev = processed_tokens[i - 1]
                # Nếu prev là term/ngoặc đóng và curr là term/ngoặc mở/NOT -> chèn AND
                if (prev not in ('AND', 'OR', 'NOT', '(')) and (tok not in ('AND', 'OR', ')')):
                    implicit_tokens.append('AND')
            implicit_tokens.append(tok)

        for tok in implicit_tokens:
            if tok in ('AND', 'OR', 'NOT'):
                while (operator_stack and operator_stack[-1] != '(' and
                       precedence.get(operator_stack[-1], 0) >= precedence[tok]):
                    output_queue.append(operator_stack.pop())
                operator_stack.append(tok)
            elif tok == '(':
                operator_stack.append(tok)
            elif tok == ')':
                while operator_stack and operator_stack[-1] != '(':
                    output_queue.append(operator_stack.pop())
                if operator_stack and operator_stack[-1] == '(':
                    operator_stack.pop()
            else:
                output_queue.append(tok)

        while operator_stack:
            op = operator_stack.pop()
            if op not in ('(', ')'):
                output_queue.append(op)

        # Tính toán cây Q object từ RPN
        eval_stack = []
        for item in output_queue:
            if item == 'NOT':
                if eval_stack:
                    top = eval_stack.pop()
                    eval_stack.append(~top)
            elif item == 'AND':
                if len(eval_stack) >= 2:
                    b = eval_stack.pop()
                    a = eval_stack.pop()
                    eval_stack.append(a & b)
                elif len(eval_stack) == 1:
                    pass
            elif item == 'OR':
                if len(eval_stack) >= 2:
                    b = eval_stack.pop()
                    a = eval_stack.pop()
                    eval_stack.append(a | b)
                elif len(eval_stack) == 1:
                    pass
            else:
                eval_stack.append(make_field_q(item))

        if eval_stack:
            result = eval_stack[0]
            for rest in eval_stack[1:]:
                result = result & rest
            return result

        return Q(pk__isnull=True)
