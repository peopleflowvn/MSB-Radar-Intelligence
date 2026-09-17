#!/usr/bin/env bash
# Khôi phục CSDL MSB Radar từ một file .dump (định dạng custom của pg_dump -Fc).
#
#   scripts/restore_radar_db.sh radar-20260902T150000Z.dump          # khôi phục THẬT (hỏi xác nhận)
#   scripts/restore_radar_db.sh radar-...dump --into msbradar_check  # thử vào DB nháp, không đụng prod
#   scripts/restore_radar_db.sh --latest --into msbradar_check       # lấy bản mới nhất
#   scripts/restore_radar_db.sh --from-r2 radar-...dump              # tải từ R2 trước
#
# Mặc định KHÔNG ghi đè prod: phải gõ đúng tên DB để xác nhận.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${RADAR_ENV_FILE:-${SCRIPT_DIR}/.env}"
DB_CONTAINER="${DB_CONTAINER:-msbradar-db}"
DB_USER="${DB_USER:-msbradar}"
PROD_DB="${DB_NAME:-msbradar}"
BACKUP_DIR="${BACKUP_DIR:-${SCRIPT_DIR}/backups}"
[ -f "${ENV_FILE}" ] && set -a && . "${ENV_FILE}" && set +a

TARGET_DB="${PROD_DB}"
SRC=""
FROM_R2=0
while [ $# -gt 0 ]; do
    case "$1" in
        --into) TARGET_DB="$2"; shift 2;;
        --latest) SRC="$(ls -1t "${BACKUP_DIR}"/radar-*.dump 2>/dev/null | head -1)"; shift;;
        --from-r2) FROM_R2=1; shift;;
        *) SRC="$1"; shift;;
    esac
done
[ -n "${SRC}" ] || { echo "Thiếu file .dump (hoặc --latest)."; exit 1; }

if [ "${FROM_R2}" = 1 ]; then
    export AWS_ACCESS_KEY_ID="${R2_ACCESS_KEY:-}" AWS_SECRET_ACCESS_KEY="${R2_SECRET_KEY:-}" AWS_DEFAULT_REGION=auto
    aws s3 cp "s3://${R2_BUCKET}/radar_db_backups/$(basename "${SRC}")" "${BACKUP_DIR}/$(basename "${SRC}")" \
        --endpoint-url "${R2_ENDPOINT}" || { echo "Tải R2 thất bại."; exit 1; }
    SRC="${BACKUP_DIR}/$(basename "${SRC}")"
fi
[ -f "${SRC}" ] || { echo "Không thấy ${SRC}"; exit 1; }

echo "File   : ${SRC} ($(du -h "${SRC}" | cut -f1))"
echo "Archive: $(docker exec -i "${DB_CONTAINER}" pg_restore --list < "${SRC}" 2>/dev/null | grep -c 'TABLE DATA') bảng có dữ liệu"
echo "Đích   : DB '${TARGET_DB}' trên ${DB_CONTAINER}"

if [ "${TARGET_DB}" = "${PROD_DB}" ]; then
    echo ""
    echo "⚠️  Đây là DB PRODUCTION. Toàn bộ dữ liệu hiện tại sẽ bị thay thế."
    read -r -p "Gõ đúng '${PROD_DB}' để xác nhận: " ans
    [ "${ans}" = "${PROD_DB}" ] || { echo "Huỷ."; exit 1; }
    docker exec "${DB_CONTAINER}" psql -U "${DB_USER}" -d postgres -c \
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${PROD_DB}' AND pid<>pg_backend_pid();" >/dev/null
    docker exec "${DB_CONTAINER}" psql -U "${DB_USER}" -d postgres -c "DROP DATABASE IF EXISTS ${PROD_DB};" >/dev/null
    docker exec "${DB_CONTAINER}" psql -U "${DB_USER}" -d postgres -c "CREATE DATABASE ${PROD_DB} OWNER ${DB_USER};" >/dev/null
else
    docker exec "${DB_CONTAINER}" psql -U "${DB_USER}" -d postgres -c "DROP DATABASE IF EXISTS ${TARGET_DB};" >/dev/null
    docker exec "${DB_CONTAINER}" psql -U "${DB_USER}" -d postgres -c "CREATE DATABASE ${TARGET_DB} OWNER ${DB_USER};" >/dev/null
fi

echo "Đang khôi phục…"
docker exec -i "${DB_CONTAINER}" pg_restore -U "${DB_USER}" -d "${TARGET_DB}" --no-owner --clean --if-exists < "${SRC}" \
    2> >(grep -vE "already exists|does not exist, skipping" >&2) || true

echo ""
echo "Kiểm tra nhanh (${TARGET_DB}):"
docker exec -i "${DB_CONTAINER}" psql -U "${DB_USER}" -d "${TARGET_DB}" -tA -c "
  SELECT 'people_person='||count(*) FROM people_person
  UNION ALL SELECT 'people_document='||count(*) FROM people_document
  UNION ALL SELECT 'talent_talentprofile='||count(*) FROM talent_talentprofile
  UNION ALL SELECT 'ai_assistantmessage='||count(*) FROM ai_assistantmessage
  UNION ALL SELECT 'talent_cvchunk='||count(*) FROM talent_cvchunk;"
[ "${TARGET_DB}" != "${PROD_DB}" ] && echo "(DB nháp — xoá bằng: docker exec ${DB_CONTAINER} psql -U ${DB_USER} -d postgres -c 'DROP DATABASE ${TARGET_DB};')"
echo "Xong."
