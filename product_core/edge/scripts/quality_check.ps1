$ErrorActionPreference = "Stop"
python -m compileall -q app tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check app tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m coverage run -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m coverage report
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
# Hai bản sửa cuối yêu cầu Python>=3.10. Ứng dụng hiện còn hỗ trợ Python 3.9;
# giữ ngoại lệ có tên, mọi CVE khác vẫn làm fail build.
python -m pip_audit -r requirements.txt `
  --ignore-vuln PYSEC-2026-2275 `
  --ignore-vuln PYSEC-2026-141 --ignore-vuln PYSEC-2026-142
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
