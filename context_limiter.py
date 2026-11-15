"""
context_limiter.py - Smart Semantic Context Limiter & Chunking System
Specifically designed for the Researcher subsystem to accelerate LLM generation on CPU.

Breaks large textual contexts (~4k-6k words) into manageable semantic chunks:
- Base size: ~1,000 words (~1,300 tokens)
- Smart lookahead window: up to +500 words (max 1,500 words total)
- Smart cutoff boundaries:
    1. Main topic/section headings (#, ##, ###)
    2. Paragraph breaks (\\n\\n)
    3. Proper sentence completions (., !, ?)
- Fenced block protection (no mid-code or mid-LaTeX cuts)
- Prevents data loss and eliminates CPU prompt evaluation bottlenecks.
"""

import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

try:
    from .logger import get_logger
    logger = get_logger(__name__)
except (ImportError, ValueError):
    try:
        from logger import get_logger
        logger = get_logger(__name__)
    except Exception:
        import logging
        logger = logging.getLogger(__name__)


@dataclass
class SemanticChunk:
    """Represents a single semantically complete text chunk."""
    chunk_id: int
    text: str
    word_count: int
    source_title: str = ""
    source_url: str = ""
    detected_heading: str = ""
    is_last: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


class SmartSemanticChunker:
    """
    Splits long research documents into semantically coherent segments
    bounded by 1,000 base words (~1,333 tokens) + up to 400 words lookahead (~533 tokens).
    """

    def __init__(
        self, 
        base_words: int = 1000, 
        max_lookahead: int = 400, 
        base_tokens: Optional[int] = None, 
        max_lookahead_tokens: Optional[int] = None
    ):
        if base_tokens is not None:
            self.base_words = max(50, int(base_tokens * 0.75))
        else:
            self.base_words = base_words

        if max_lookahead_tokens is not None:
            self.max_lookahead = max(50, int(max_lookahead_tokens * 0.75))
        else:
            self.max_lookahead = max_lookahead

        self.max_total_words = self.base_words + self.max_lookahead

    def _is_inside_fence(self, text: str, char_pos: int) -> bool:
        """Determines if a character position lies inside a code fence or math block."""
        prefix = text[:char_pos]
        # Count ``` code fences
        code_fence_count = len(re.findall(r'```', prefix))
        if code_fence_count % 2 == 1:
            return True
        # Count $$ display math fences
        math_fence_count = len(re.findall(r'\$\$', prefix))
        if math_fence_count % 2 == 1:
            return True
        return False

    def chunk_text(
        self,
        text: str,
        source_title: str = "",
        source_url: str = ""
    ) -> List[SemanticChunk]:
        """
        Chunks text into semantic slices respecting headings, paragraphs, and sentence boundaries.
        Guarantees no mid-sentence cuts and protects fenced blocks.
        """
        if not text or not text.strip():
            return []

        clean_text = text.strip()
        words = clean_text.split()
        total_words = len(words)

        if total_words <= self.max_total_words:
            # Whole text fits within the safe window
            return [
                SemanticChunk(
                    chunk_id=1,
                    text=clean_text,
                    word_count=total_words,
                    source_title=source_title,
                    source_url=source_url,
                    is_last=True
                )
            ]

        chunks: List[SemanticChunk] = []
        current_char_start = 0
        chunk_index = 1

        while current_char_start < len(clean_text):
            remaining_text = clean_text[current_char_start:].lstrip()
            if not remaining_text:
                break

            remaining_words = remaining_text.split()
            if len(remaining_words) <= self.max_total_words:
                chunks.append(
                    SemanticChunk(
                        chunk_id=chunk_index,
                        text=remaining_text,
                        word_count=len(remaining_words),
                        source_title=source_title,
                        source_url=source_url,
                        is_last=True
                    )
                )
                break

            # Estimate base char boundary (approx 6 chars per word)
            base_word_slice = remaining_words[:self.base_words]
            base_char_approx = len(" ".join(base_word_slice))

            lookahead_slice = remaining_words[self.base_words:self.max_total_words]
            lookahead_char_approx = len(" ".join(lookahead_slice))
            max_char_boundary = min(len(remaining_text), base_char_approx + lookahead_char_approx + 200)

            search_window = remaining_text[base_char_approx:max_char_boundary]

            cutoff_relative_pos = -1
            detected_heading = ""

            # 1. PRIORITY 1: Markdown Heading Boundary within lookahead
            # If a new section starts within the next 500 words, cut right before it
            heading_match = re.search(r'\n(#{1,4}\s+[^\n]+)', search_window)
            if heading_match:
                cand_pos = base_char_approx + heading_match.start()
                if not self._is_inside_fence(remaining_text, cand_pos):
                    cutoff_relative_pos = cand_pos
                    detected_heading = heading_match.group(1).strip()

            # 2. PRIORITY 2: Paragraph break (\n\n) within lookahead
            if cutoff_relative_pos == -1:
                # Look for the last paragraph break within the lookahead window
                para_matches = [m for m in re.finditer(r'\n\s*\n', search_window)]
                for pm in reversed(para_matches):
                    cand_pos = base_char_approx + pm.end()
                    if not self._is_inside_fence(remaining_text, cand_pos):
                        cutoff_relative_pos = cand_pos
                        break

            # 3. PRIORITY 3: Sentence Completion Boundary (. , ! , ?)
            if cutoff_relative_pos == -1:
                sent_matches = [m for m in re.finditer(r'([.!?])(?:\s+|\n|$)', search_window)]
                for sm in reversed(sent_matches):
                    cand_pos = base_char_approx + sm.end()
                    if not self._is_inside_fence(remaining_text, cand_pos):
                        cutoff_relative_pos = cand_pos
                        break

            # Fallback if no clean punctuation in search window: check after base words for nearest sentence
            safe_char_limit = len(" ".join(remaining_words[:self.max_total_words]))
            if cutoff_relative_pos == -1:
                next_sentence = re.search(r'([.!?])(?:\s+|\n|$)', remaining_text[base_char_approx:])
                if next_sentence:
                    cand_pos = base_char_approx + next_sentence.end()
                    if cand_pos <= safe_char_limit and not self._is_inside_fence(remaining_text, cand_pos):
                        cutoff_relative_pos = cand_pos

            # Absolute safety fallback: cut at last space before max words or clamp if exceeded
            if cutoff_relative_pos == -1 or cutoff_relative_pos > safe_char_limit:
                cutoff_relative_pos = safe_char_limit

            chunk_content = remaining_text[:cutoff_relative_pos].strip()
            chunk_word_count = len(chunk_content.split())

            chunks.append(
                SemanticChunk(
                    chunk_id=chunk_index,
                    text=chunk_content,
                    word_count=chunk_word_count,
                    source_title=source_title,
                    source_url=source_url,
                    detected_heading=detected_heading,
                    is_last=False
                )
            )

            current_char_start += (len(clean_text[current_char_start:]) - len(remaining_text)) + cutoff_relative_pos
            chunk_index += 1

        if chunks:
            chunks[-1].is_last = True

        logger.info(
            f"SmartSemanticChunker partitioned document '{source_title}' "
            f"({total_words} words) into {len(chunks)} chunks (avg {total_words // max(1, len(chunks))} words/chunk)."
        )
        return chunks


def calculate_dynamic_context_budget(
    query_tokens: int,
    chunk_tokens: int,
    buffer_tokens: int = 500
) -> int:
    """
    Calculates dynamic context length rule:
    context_length = 1000 + query_length_tokens (+ chunk & output buffer)
    """
    return max(4096, 1000 + query_tokens + chunk_tokens + buffer_tokens)

