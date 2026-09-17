#!/usr/bin/env bash
# Backup CSDL MSB Radar — dump + VERIFY + đẩy R2 + retention cục bộ.
#
# Chạy hằng giờ từ cron. Nguyên tắc: một file backup KHÔNG verify được thì coi như
# không có. Script tự kiểm bằng `pg_restore --list` và ngưỡng dung lượng trước khi
# tin; hỏng thì giữ nguyên bản trước, ghi log, exit != 0 (cron sẽ mail nếu có MTA).
#
# Cài trên VPS:
#   cp scripts/backup_radar_db.sh ~/msbradar/ && chmod +x ~/msbradar/backup_radar_db.sh
#   ( crontab -l; echo '15 * * * * bash /home/ubuntu/msbradar/backup_radar_db.sh >> /home/ubuntu/radar-backup.log 2>&1' ) | crontab -
#
# Khôi phục (xem README cuối file):
#   scripts/restore_radar_db.sh <file.dump>
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${RADAR_ENV_FILE:-${SCRIPT_DIR}/.env}"
DB_CONTAINER="${DB_CONTAINER:-msbradar-db}"
DB_USER="${DB_USER:-msbradar}"
DB_NAME="${DB_NAME:-msbradar}"
BACKUP_DIR="${BACKUP_DIR:-${SCRIPT_DIR}/backups}"
MIN_BYTES="${MIN_BYTES:-50000}"          # dump nhỏ hơn mức này = nghi hỏng
KEEP_HOURLY="${KEEP_HOURLY:-48}"
KEEP_DAILY="${KEEP_DAILY:-21}"
R2_PREFIX="${R2_PREFIX:-radar_db_backups}"

[ -f "${ENV_FILE}" ] && set -a && . "${ENV_FILE}" && set +a

mkdir -p "${BACKUP_DIR}"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
FILE="${BACKUP_DIR}/radar-${STAMP}.dump"
log() { echo "[$(date -u +%FT%TZ)] $*"; }

cleanup_fail() { rm -f "${FILE}"; }

log "=== backup ${DB_NAME}@${DB_CONTAINER} → ${FILE##*/} ==="

# -Fc: custom format, nén sẵn, pg_restore verify/parallel/selective được.
if ! docker exec "${DB_CONTAINER}" pg_dump -U "${DB_USER}" -Fc "${DB_NAME}" > "${FILE}" 2>/tmp/radar-pgdump.err; then
    log "LỖI pg_dump: $(tr -d '\n' < /tmp/radar-pgdump.err)"
    cleanup_fail; exit 1
fi

BYTES=$(stat -c%s "${FILE}" 2>/dev/null || echo 0)
if [ "${BYTES}" -lt "${MIN_BYTES}" ]; then
    log "LỖI: dump chỉ ${BYTES} byte (< ${MIN_BYTES}) — nghi hỏng, không tin."
    cleanup_fail; exit 1
fi

# VERIFY: pg_restore --list phải đọc được archive và thấy bảng dữ liệu của app.
TOC_FILE="/tmp/radar-toc-${STAMP}.txt"
if ! docker exec -i "${DB_CONTAINER}" pg_restore --list < "${FILE}" > "${TOC_FILE}" 2>/tmp/radar-pgrestore.err; then
    log "LỖI: pg_restore --list không đọc được archive: $(tr -d '\n' < /tmp/radar-pgrestore.err)"
    cleanup_fail; rm -f "${TOC_FILE}"; exit 1
fi
for want in people_person talent_talentprofile people_document ai_assistantthread; do
    grep -q "TABLE DATA .* ${want} " "${TOC_FILE}" || {
        log "LỖI: archive thiếu 'TABLE DATA ... ${want}' — dump không đầy đủ."
        cleanup_fail; rm -f "${TOC_FILE}"; exit 1
    }
done
NTABLES=$(grep -c "TABLE DATA" "${TOC_FILE}")
rm -f "${TOC_FILE}"
log "OK: ${BYTES} byte, ${NTABLES} bảng có dữ liệu, verify pg_restore --list PASS."

# Đẩy R2 (không chặn: lỗi mạng thì bản cục bộ vẫn còn).
if [ -n "${R2_ENDPOINT:-}" ] && [ -n "${R2_BUCKET:-}" ]; then
    export AWS_ACCESS_KEY_ID="${R2_ACCESS_KEY:-${AWS_ACCESS_KEY_ID:-}}"
    export AWS_SECRET_ACCESS_KEY="${R2_SECRET_KEY:-${AWS_SECRET_ACCESS_KEY:-}}"
    export AWS_DEFAULT_REGION="auto"
    if aws s3 cp "${FILE}" "s3://${R2_BUCKET}/${R2_PREFIX}/${FILE##*/}" \
            --endpoint-url "${R2_ENDPOINT}" --only-show-errors; then
        log "R2: đã đẩy ${R2_PREFIX}/${FILE##*/}"
    else
        log "CẢNH BÁO: đẩy R2 thất bại — bản cục bộ ${FILE##*/} vẫn an toàn."
    fi
else
    log "R2 chưa cấu hình (.env thiếu R2_ENDPOINT/R2_BUCKET) — chỉ lưu cục bộ."
fi

# Retention cục bộ: giữ ${KEEP_HOURLY} bản mới nhất + 1 bản/ngày cho ${KEEP_DAILY} ngày.
cd "${BACKUP_DIR}" || exit 0
mapfile -t ALL < <(ls -1t radar-*.dump 2>/dev/null)
declare -A KEEP_DAY
KEPT=0
for i in "${!ALL[@]}"; do
    f="${ALL[$i]}"
    if [ "${i}" -lt "${KEEP_HOURLY}" ]; then KEPT=$((KEPT+1)); continue; fi
    day="${f:6:8}"
    if [ -z "${KEEP_DAY[$day]:-}" ] && [ "${#KEEP_DAY[@]}" -lt "${KEEP_DAILY}" ]; then
        KEEP_DAY[$day]=1; KEPT=$((KEPT+1)); continue
    fi
    rm -f "${f}" && log "retention: xoá ${f}"
done
log "retention: giữ ${KEPT} bản cục bộ."
log "=== xong ==="
