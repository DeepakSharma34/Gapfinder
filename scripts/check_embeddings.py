"""Manual semantic smoke check; the first run downloads model weights."""
from dataclasses import replace
from tempfile import TemporaryDirectory
from pathlib import Path

from gapfinder.config import Settings
from gapfinder.retrieval import Retrieval


def main():
    with TemporaryDirectory() as directory:
        base = Settings.from_env()
        settings = replace(base, embedding_backend="fastembed", qdrant_url="", qdrant_key="",
                           data_dir=Path(directory))
        retrieval = Retrieval(settings)
        try:
            chunks = [
                {"id":"00000000-0000-0000-0000-000000000001", "user_id":"student-a", "topic_id":"cells",
                 "text":"Mitochondria produce ATP through aerobic respiration.", "kind":"notes"},
                {"id":"00000000-0000-0000-0000-000000000002", "user_id":"student-a", "topic_id":"genetics",
                 "text":"DNA carries hereditary information through its nucleotide sequence.", "kind":"notes"},
                {"id":"00000000-0000-0000-0000-000000000003", "user_id":"student-b", "topic_id":"cells",
                 "text":"Cells obtain usable energy from mitochondria.", "kind":"notes"},
            ]
            retrieval.index(chunks)
            result = retrieval.search("student-a", "Which organelle supplies cellular energy?", limit=2)
            assert result[0]["topic_id"] == "cells", result
            assert all(c["user_id"] == "student-a" for c in result)
            print("PASS: FastEmbed semantic retrieval and user filtering")
        finally:
            retrieval.close()


if __name__ == "__main__":
    main()
