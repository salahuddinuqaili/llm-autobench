"""Offline pass/fail coverage for M1 python-exec scoring. No Ollama / judge."""
import os
import sys
import textwrap

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import code_exec  # noqa: E402
import run_bench  # noqa: E402

REPO = os.path.join(os.path.dirname(__file__), "..")


def _task():
    with open(os.path.join(REPO, "tasks", "code_generation.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


CORRECT = textwrap.dedent(
    '''\
    ```python
    import re

    def chunk_text(text: str, max_chars: int) -> list[str]:
        """Split text into chunks of at most max_chars.

        Prefers sentence boundaries; never cuts a word. A word longer than
        max_chars is emitted whole (chunk may exceed max_chars).
        """
        if text == "":
            return []
        sentences = re.findall(r"[^.!?]*[.!?]|[^.!?]+$", text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        def split_long(s: str) -> list[str]:
            words = s.split()
            out, cur, cur_len = [], [], 0
            for w in words:
                need = len(w) + (1 if cur else 0)
                if cur and cur_len + need > max_chars:
                    out.append(" ".join(cur))
                    cur, cur_len = [], 0
                    need = len(w)
                if not cur and len(w) > max_chars:
                    out.append(w)
                    continue
                cur.append(w)
                cur_len += need
            if cur:
                out.append(" ".join(cur))
            return out

        chunks, cur = [], ""
        for sent in sentences:
            if not cur:
                if len(sent) <= max_chars:
                    cur = sent
                else:
                    chunks.extend(split_long(sent))
                continue
            candidate = cur + " " + sent
            if len(candidate) <= max_chars:
                cur = candidate
            else:
                chunks.append(cur)
                if len(sent) <= max_chars:
                    cur = sent
                else:
                    chunks.extend(split_long(sent))
                    cur = ""
        if cur:
            chunks.append(cur)
        return chunks

    assert chunk_text("Hi.", 10) == ["Hi."]
    ```
    '''
)

WRONG_SLICE = textwrap.dedent(
    '''\
    ```python
    def chunk_text(text: str, max_chars: int) -> list[str]:
        """Looks fluent but cuts mid-word."""
        if not text:
            return []
        return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]

    assert chunk_text("abcd", 2) == ["ab", "cd"]
    ```
    '''
)

PROSE_ONLY = "Sure! Here is a careful design for chunk_text without any code."

SYNTAX_BAD = textwrap.dedent(
    '''\
    ```python
    def chunk_text(text: str, max_chars: int) -> list[str]
        return []
    ```
    '''
)


def test_task_is_python_exec():
    task = _task()
    assert task["scoring"]["method"] == "python-exec"
    assert task["scoring"]["function"] == "chunk_text"
    assert len(task["scoring"]["checks"]) >= 4


def test_correct_scores_one():
    task = _task()
    assert code_exec.score_python_exec(task, CORRECT) == 1.0
    assert run_bench.score(task, CORRECT) == 1.0


def test_wrong_but_fluent_scores_zero():
    task = _task()
    assert code_exec.score_python_exec(task, WRONG_SLICE) == 0.0
    assert run_bench.score(task, WRONG_SLICE) == 0.0


def test_unparseable_stays_null():
    task = _task()
    assert code_exec.score_python_exec(task, PROSE_ONLY) is None
    assert code_exec.score_python_exec(task, SYNTAX_BAD) is None
    assert code_exec.score_python_exec(task, "") is None
    assert run_bench.score(task, PROSE_ONLY) is None


def test_extract_prefers_def_fence():
    mixed = "Intro\n```\nprint(1)\n```\n```python\ndef foo():\n    return 1\n```\n"
    src = code_exec.extract_python(mixed)
    assert src is not None and "def foo" in src


if __name__ == "__main__":
    test_task_is_python_exec()
    test_correct_scores_one()
    test_wrong_but_fluent_scores_zero()
    test_unparseable_stays_null()
    test_extract_prefers_def_fence()
    print("ok")