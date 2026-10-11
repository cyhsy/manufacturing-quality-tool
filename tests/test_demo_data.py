from io import BytesIO

import pytest

from modules.demo_data import DEFAULT_SAMPLE_NAME, list_sample_files, load_sample_upload


def test_list_sample_files_prioritizes_default(tmp_path):
    (tmp_path / "另一个样例.csv").write_text("a\n1\n", encoding="utf-8")
    (tmp_path / DEFAULT_SAMPLE_NAME).write_bytes(b"xlsx")
    (tmp_path / "说明.txt").write_text("ignore", encoding="utf-8")

    sample_files = list_sample_files(tmp_path)

    assert [path.name for path in sample_files] == [
        DEFAULT_SAMPLE_NAME,
        "另一个样例.csv",
    ]


def test_list_sample_files_requires_supported_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="没有可用"):
        list_sample_files(tmp_path)


def test_load_sample_upload_matches_streamlit_upload_interface(tmp_path):
    sample_path = tmp_path / "样例.xlsx"
    expected = b"sample-bytes"
    sample_path.write_bytes(expected)

    upload = load_sample_upload(sample_path)

    assert isinstance(upload, BytesIO)
    assert upload.name == "样例.xlsx"
    assert upload.getvalue() == expected
