from io import BytesIO
from pathlib import Path


SUPPORTED_DATA_SUFFIXES = {".csv", ".xlsx", ".xls"}
DEFAULT_SAMPLE_NAME = "质量异常记录样本.xlsx"


def list_sample_files(sample_dir):
    """Return supported sample files with the primary demo file first."""
    sample_dir = Path(sample_dir)
    sample_files = sorted(
        (
            path
            for path in sample_dir.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_DATA_SUFFIXES
        ),
        key=lambda path: (path.name != DEFAULT_SAMPLE_NAME, path.name),
    )
    if not sample_files:
        raise FileNotFoundError("sample_data 目录中没有可用的示例数据文件。")
    return sample_files


def load_sample_upload(sample_path):
    """Expose a packaged sample file through the same interface as an upload."""
    sample_path = Path(sample_path)
    sample_upload = BytesIO(sample_path.read_bytes())
    sample_upload.name = sample_path.name
    return sample_upload
