// MSB Radar Edge Brand Controller (v3.0 - High Performance & Custom Column Viewer)

// --- Khoá localStorage: chuyển tiền tố gensync_ cũ sang msb_radar_ ---
// Chạy một lần lúc nạp trang, trước khi bất kỳ đoạn nào đọc cấu hình, để người
// dùng không mất lựa chọn cột hiển thị / theme / trạng thái sidebar khi nâng cấp
// từ GenSync Radar. Đọc/ghi đều đi qua LS.* nên chỉ còn một chỗ biết tiền tố.
const LS = (() => {
  const PREFIX = 'msb_radar_';
  const LEGACY_PREFIX = 'gensync_';
  const key = name => PREFIX + name;
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const old = localStorage.key(i);
      if (!old || !old.startsWith(LEGACY_PREFIX)) continue;
      const renamed = PREFIX + old.slice(LEGACY_PREFIX.length);
      if (localStorage.getItem(renamed) === null) {
        localStorage.setItem(renamed, localStorage.getItem(old));
      }
    }
  } catch (e) { /* chế độ riêng tư / hết dung lượng: bỏ qua, dùng mặc định */ }
  return {
    get: name => { try { return localStorage.getItem(key(name)); } catch (e) { return null; } },
    set: (name, value) => { try { localStorage.setItem(key(name), value); } catch (e) { /* bỏ qua */ } },
  };
})();

const PRESET_PALETTES = {
  amber_gold: {
    primary: '#F59E0B',
    primaryDark: '#E65C00',
    primaryLight: '#FBBF24',
    orange: '#FF8A33',
    orangeDark: '#E65C00',
    orangeLight: '#F59E0B'
  },
  ocean_blue: {
    primary: '#0284c7',
    primaryDark: '#0369a1',
    primaryLight: '#38bdf8',
    orange: '#0ea5e9',
    orangeDark: '#0284c7',
    orangeLight: '#38bdf8'
  },
  crimson_red: {
    primary: '#dc2626',
    primaryDark: '#b91c1c',
    primaryLight: '#ef4444',
    orange: '#f87171',
    orangeDark: '#dc2626',
    orangeLight: '#ef4444'
  },
  emerald_green: {
    primary: '#059669',
    primaryDark: '#047857',
    primaryLight: '#34d399',
    orange: '#10b981',
    orangeDark: '#059669',
    orangeLight: '#34d399'
  },
  royal_purple: {
    primary: '#7c3aed',
    primaryDark: '#6d28d9',
    primaryLight: '#a78bfa',
    orange: '#8b5cf6',
    orangeDark: '#7c3aed',
    orangeLight: '#a78bfa'
  },
  cyber_cyan: {
    primary: '#0891b2',
    primaryDark: '#0e7490',
    primaryLight: '#22d3ee',
    orange: '#06b6d4',
    orangeDark: '#0891b2',
    orangeLight: '#22d3ee'
  },
  custom: {
    primary: '#F59E0B',
    primaryDark: '#E65C00',
    primaryLight: '#FBBF24',
    orange: '#FF8A33',
    orangeDark: '#E65C00',
    orangeLight: '#F59E0B'
  }
};

class App {
  constructor() {
    this.api = null;
    this.currentTab = 'tab-download';
    this._currentThemeMode = 'dark';
    this._currentColorPreset = 'amber_gold';
    this._currentCustomColor = '#F59E0B';
    this._currentAppIcon = '⚡';
    this._currentLogoUrl = '';
    this.downloadMode = null;
    this.downloadBaseStats = null;
    this.page = 1;
    this.limit = 50;
    this.totalCandidates = 0;
    this.candidateRequestId = 0;
    this.checkpointRequestId = 0;
    this.sortBy = 'applied_ts';
    this.sortDir = 'DESC';
    this.reportLoaded = false;
    this.reportFiltersDirty = false;
    this.candidateFilterOptions = { accounts: [], accounts_by_source: {} };
    this.liveCandidates = [];
    this.liveNewTotal = 0;
    this.sidebarBaseTotal = 0;
    this.liveCandidateTimer = null;
    this.selectedCandidates = new Map();
    this.parsingEventSeq = 0;
    this.parsingStatusTimer = null;
    this.parsingPage = 1;
    this.parsingPageSize = 15;
    this.parsingStatusFilter = '';
    this.parsingSearchQuery = '';

    // Định nghĩa tất cả các cột dữ liệu có thể hiển thị (STT, Nguồn, Tình trạng, Họ tên, File CV xếp ngoài cùng bên trái)
    this.allColumns = [
      { key: 'stt', label: 'STT', default: true },
      { key: 'source', label: 'Nguồn', default: true },
      { key: 'dl_status', label: 'Tình trạng tải', default: true },
      { key: 'parse_status', label: 'Parsing CV', default: true },
      { key: 'parse_method', label: 'Parsing · Phương thức', default: false },
      { key: 'parse_file_format', label: 'Parsing · Định dạng', default: false },
      { key: 'parse_version', label: 'Parsing · Phiên bản bộ đọc', default: false },
      { key: 'parse_text_length', label: 'Parsing · Số ký tự', default: false },
      { key: 'parse_quality', label: 'Parsing · Chất lượng', default: false },
      { key: 'parse_needs_ocr', label: 'Parsing · Cần OCR', default: false },
      { key: 'parse_attempts', label: 'Parsing · Số lần thử', default: false },
      { key: 'parse_at', label: 'Parsing · Hoàn tất lúc', default: false },
      { key: 'parse_emails', label: 'Parsing · Email tìm thấy', default: false },
      { key: 'parse_phones', label: 'Parsing · SĐT tìm thấy', default: false },
      { key: 'parse_urls', label: 'Parsing · Liên kết tìm thấy', default: false },
      { key: 'parse_error', label: 'Parsing · Lỗi / lưu ý', default: false },
      { key: 'alerts', label: 'Cảnh báo', default: true },
      { key: 'fullname', label: 'Họ và tên', default: true },
      { key: 'filename', label: 'File CV / Thao tác', default: true },
      { key: 'email', label: 'Email', default: true },
      { key: 'phone', label: 'Số điện thoại', default: true },
      { key: 'position', label: 'Vị trí ứng tuyển', default: true },
      { key: 'applied_at', label: 'Ngày ứng tuyển', default: true },
      { key: 'status', label: 'Trạng thái', default: true },
      { key: 'account', label: 'Tài khoản tải', default: false },
      { key: 'cv_emails', label: 'Email khác trong CV', default: false },
      { key: 'cv_phones', label: 'SĐT khác trong CV', default: false },
      { key: 'cv_id', label: 'Mã CV', default: false },
      { key: 'campaign_id', label: 'Mã tin', default: false },
      { key: 'apply_source', label: 'Loại hồ sơ / Nguồn chi tiết', default: false },
      { key: 'gender', label: 'Giới tính', default: false },
      { key: 'birth_year', label: 'Năm sinh', default: false },
      { key: 'marital_status', label: 'Tình trạng hôn nhân', default: false },
      { key: 'experience', label: 'Kinh nghiệm', default: false },
      { key: 'years_experience', label: 'Số năm kinh nghiệm', default: false },
      { key: 'address', label: 'Địa chỉ', default: false },
      { key: 'city', label: 'Tỉnh/Thành phố', default: false },
      { key: 'district', label: 'Quận/Huyện', default: false },
      { key: 'desired_location', label: 'Nơi làm việc mong muốn', default: false },
      { key: 'current_title', label: 'Chức danh gần nhất', default: false },
      { key: 'job_level', label: 'Cấp bậc', default: false },
      { key: 'desired_level', label: 'Cấp bậc mong muốn', default: false },
      { key: 'desired_position', label: 'Ngành nghề/Vị trí mong muốn', default: false },
      { key: 'job_type', label: 'Hình thức làm việc mong muốn', default: false },
      { key: 'education', label: 'Học vấn', default: false },
      { key: 'foreign_language', label: 'Ngoại ngữ', default: false },
      { key: 'expected_salary', label: 'Lương mong muốn', default: false },
      { key: 'current_salary', label: 'Lương hiện tại', default: false },
      { key: 'skills', label: 'Kỹ năng', default: false },
      { key: 'last_company', label: 'Công ty gần nhất', default: false },
      { key: 'labels', label: 'Nhãn CV', default: false },
      { key: 'note', label: 'Ghi chú', default: false },
      { key: 'candidate_id', label: 'Mã ứng viên', default: false },
      { key: 'resume_id', label: 'Mã hồ sơ', default: false },
      { key: 'profile_type', label: 'Loại hồ sơ', default: false },
      { key: 'attachment_name', label: 'Tên file gốc', default: false },
      { key: 'attachment_mime', label: 'Định dạng file', default: false },
      { key: 'is_viewed', label: 'Đã xem', default: false },
      { key: 'cv_url', label: 'Link xem CV', default: false },
      { key: 'first_seen', label: 'Lần đầu ghi nhận', default: false },
      { key: 'updated_at', label: 'Cập nhật lúc', default: false }
    ];

    this.visibleColumns = this.loadSavedColumns();
    this.init();
  }

  loadSavedColumns() {
    const saved = LS.get('visible_columns_v5');
    if (saved) {
      try {
        const columns = JSON.parse(saved).filter(key => this.allColumns.some(col => col.key === key));
        if (!columns.includes('alerts')) columns.push('alerts');
        if (!columns.includes('parse_status')) {
          const afterDownload = columns.indexOf('dl_status') + 1;
          columns.splice(Math.max(0, afterDownload), 0, 'parse_status');
        }
        return columns;
      } catch (e) { }
    }
    return this.allColumns.filter(c => c.default).map(c => c.key);
  }

  saveColumns(cols) {
    this.visibleColumns = cols;
    LS.set('visible_columns_v5', JSON.stringify(cols));
  }

  selectedValues(id) {
    const select = document.getElementById(id);
    return select ? Array.from(select.selectedOptions).map(option => option.value).filter(Boolean) : [];
  }

  setupMultiCheckFilters() {
    document.querySelectorAll('.multi-check-filter').forEach(wrapper => {
      const selectId = wrapper.dataset.selectId;
      const trigger = wrapper.querySelector('.multi-check-trigger');
      trigger?.addEventListener('click', (event) => {
        event.stopPropagation();
        document.querySelectorAll('.multi-check-menu').forEach(menu => {
          if (menu !== wrapper.querySelector('.multi-check-menu')) {
            menu.classList.add('hidden');
            menu.closest('.multi-check-filter')?.querySelector('.multi-check-trigger')?.setAttribute('aria-expanded', 'false');
          }
        });
        const menu = wrapper.querySelector('.multi-check-menu');
        menu.classList.toggle('hidden');
        trigger.setAttribute('aria-expanded', String(!menu.classList.contains('hidden')));
      });
      wrapper.querySelector('.multi-check-clear')?.addEventListener('click', () => {
        const select = document.getElementById(selectId);
        Array.from(select?.options || []).forEach(option => option.selected = false);
        select?.dispatchEvent(new Event('change', { bubbles: true }));
        this.renderMultiCheckFilter(selectId);
      });
      wrapper.addEventListener('click', event => event.stopPropagation());
      wrapper.querySelector('.multi-check-search')?.addEventListener('input', () =>
        this.renderMultiCheckFilter(selectId));
      this.renderMultiCheckFilter(selectId);
    });
    document.addEventListener('click', () => document.querySelectorAll('.multi-check-menu').forEach(menu => {
      menu.classList.add('hidden');
      menu.closest('.multi-check-filter')?.querySelector('.multi-check-trigger')?.setAttribute('aria-expanded', 'false');
    }));
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') document.body.click();
    });
    document.getElementById('btn-clear-candidate-selection')?.addEventListener('click', () => {
      this.selectedCandidates.clear();
      this.updateCandidateSelectionUI();
      this.loadCandidates();
    });
  }

  renderMultiCheckFilter(selectId) {
    const select = document.getElementById(selectId);
    const wrapper = document.querySelector(`.multi-check-filter[data-select-id="${selectId}"]`);
    if (!select || !wrapper) return;
    const options = Array.from(select.options);
    const selected = options.filter(option => option.selected);
    const isSource = selectId.endsWith('source');
    const isPosition = selectId.endsWith('position');
    const noun = isSource ? 'nguồn' : (isPosition ? 'vị trí' : 'tài khoản');
    const allLabel = isSource ? 'Tất cả nguồn' : (isPosition ? 'Tất cả vị trí' : 'Tất cả tài khoản');
    const label = selected.length === 0 ? allLabel :
      (selected.length === 1 ? selected[0].textContent : `${selected.length} ${noun} đã chọn`);
    wrapper.querySelector('.multi-check-trigger span:first-child').textContent = label;
    const target = wrapper.querySelector('.multi-check-options');
    const query = String(wrapper.querySelector('.multi-check-search')?.value || '').toLowerCase()
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    const visibleOptions = options.map((option, index) => ({ option, index })).filter(({ option }) =>
      !query || option.textContent.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').includes(query));
    target.innerHTML = visibleOptions.length ? visibleOptions.map(({ option, index }) =>
      `<label class="multi-check-option"><input type="checkbox" data-index="${index}" ${option.selected ? 'checked' : ''}><span>${this.escapeHtml(option.textContent)}</span></label>`
    ).join('') : `<div class="text-muted" style="padding:9px">Không có ${noun} phù hợp</div>`;
    target.querySelectorAll('input').forEach(input => input.addEventListener('change', () => {
      options[Number(input.dataset.index)].selected = input.checked;
      select.dispatchEvent(new Event('change', { bubbles: true }));
      this.renderMultiCheckFilter(selectId);
    }));
  }

  async init() {
    this.setupSidebar();
    this.setupTabs();
    this.setupAccountManager();
    this.setupEventListeners();
    this.setupUIEnhancements();
    this.setupMultiCheckFilters();
    this.setupColumnModal();
    this.setupCvModal();
    this.setupLogHistoryModal();
    this.setupCandidateDetailModal();
    this.setupDateFilter();
    this.setupTopScrollbar();
    this.setupHelpHub();
    this.setupReportHub();
    this.setupParsingHub();
    this.setupSyncHub();
    this.setupThemeAndBranding();

    if (window.pywebview) {
      this.onPyWebviewReady();
    } else {
      window.addEventListener('pywebviewready', () => this.onPyWebviewReady());
    }
  }

  setupSidebar() {
    const sidebar = document.getElementById('app-sidebar');
    const button = document.getElementById('btn-toggle-sidebar');
    const icon = document.getElementById('sidebar-toggle-icon');
    if (!sidebar || !button) return;

    const apply = (collapsed) => {
      sidebar.classList.toggle('collapsed', collapsed);
      button.setAttribute('aria-expanded', String(!collapsed));
      button.setAttribute('aria-label', collapsed ? 'Mở rộng thanh menu' : 'Thu gọn thanh menu');
      button.title = collapsed ? 'Mở rộng thanh menu' : 'Thu gọn thanh menu';
      if (icon) icon.textContent = collapsed ? '›' : '‹';
      sidebar.querySelectorAll('.nav-btn').forEach(item => {
        if (item.classList.contains('nav-locked')) return;
        const label = item.querySelector('span')?.textContent?.trim();
        if (collapsed && label) item.title = label;
        else item.removeAttribute('title');
      });
      LS.set('sidebar_collapsed', collapsed ? '1' : '0');
    };

    apply(LS.get('sidebar_collapsed') === '1');
    button.addEventListener('click', () => apply(!sidebar.classList.contains('collapsed')));
  }

  async onPyWebviewReady() {
    this.api = window.pywebview.api;
    console.log("pywebview API ready!");
    let startupResults = [];

    try {
      const appInfo = await this.api.get_app_info();
      const versionText = `v${appInfo.version}`;
      document.title = appInfo.display_name;
      document.querySelectorAll('.version-badge').forEach(node => { node.textContent = versionText; });
      document.querySelectorAll('.version-tag-sub').forEach(node => {
        node.textContent = `Phiên bản ${versionText} Enterprise`;
      });
      // Chỉ chờ các API nhẹ trước khi bỏ splash. Database có thể nằm trên Google Drive
      // và cần phục hồi journal/nâng cấp chỉ mục trong lần mở đầu tiên; nếu chờ stats,
      // candidates và filter ở đây thì toàn bộ ứng dụng trông như bị treo dù backend
      // vẫn đang làm việc bình thường.
      startupResults = await Promise.all([
        this.loadProviders().catch(e => console.error("loadProviders err:", e)),
        this.loadConfig(false).catch(e => console.error("loadConfig err:", e)),
        this.api.maybe_autostart_schedule().catch(e => console.error("maybe_autostart_schedule err:", e)),
        this.loadRecentLogs().catch(e => console.error("loadRecentLogs err:", e)),
        // Lần mở bình thường dùng kết quả kiểm tra hợp lệ đã lưu; chỉ lần đầu,
        // phiên bản mới hoặc kết quả cũ có lỗi mới chạy lại các tiến trình runtime.
        this.loadRuntimeReadiness().catch(e => console.error("runtime readiness err:", e))
      ]);
      // loadConfig() ở trên đã tự đồng bộ trạng thái hẹn giờ, nhưng có thể chạy TRƯỚC khi
      // maybe_autostart_schedule() kịp bật luồng nền (cả 2 chạy song song) - đồng bộ lại
      // lần cuối cho chắc, để công tắc hẹn giờ không hiện sai trạng thái lúc mới mở app.
      this.refreshScheduleStatus().catch(e => console.error("refreshScheduleStatus err:", e));
      // Màn hình Hub phải có dữ liệu ngay khi mở, không đợi người dùng bấm gì.
      this.hubRefresh().catch(e => console.error("hubRefresh err:", e));

      let needsSetup = false;
      try {
        needsSetup = await this.api.needs_setup();
      } catch (e) {
        console.error("needs_setup err:", e);
      }

      this.applySetupLock(needsSetup);
    } catch (err) {
      console.error("onPyWebviewReady error:", err);
    } finally {
      const splash = document.getElementById('splash-screen');
      if (splash) {
        splash.classList.add('fade-out');
        setTimeout(() => splash.remove(), 300);
      }

      // Nạp tuần tự sau khi splash đã bắt đầu biến mất. Post-build probe chỉ được
      // xác nhận sau khi SQLite thật sự mở và danh sách ứng viên tải thành công.
      const initialDataReady = await this.loadInitialData();
      await this.api.report_packaged_startup_ready(startupResults?.[4], initialDataReady);
    }
  }

  async loadInitialData() {
    try {
      // Bảng đầu tiên là nội dung người dùng cần nhìn thấy; các KPI và lựa chọn bộ
      // lọc có thể điền sau mà không giữ màn hình ứng viên ở trạng thái loading.
      await this.loadCandidates();
      await this.updateStats();
      await this.loadCandidateFilterOptions();
      await this.refreshParsingStatus();
      return true;
    } catch (e) {
      console.error("loadInitialData err:", e);
      this.showAppToast('Dữ liệu đang được chuẩn bị',
        'Giao diện đã sẵn sàng. Hãy đợi ổ đĩa đám mây hoàn tất đồng bộ rồi thử tải lại dữ liệu.',
        'error', 9000);
      return false;
    }
  }

  /**
   * Khoá phần mềm ở tab Cấu hình cho tới khi khai báo xong tài khoản.
   *
   * Trước đây chỉ hiện một dòng cảnh báo "hãy cấu hình để mở khoá" nhưng KHÔNG khoá gì
   * thật - người dùng mới vẫn bấm sang tab Tải CV được rồi gặp lỗi khó hiểu vì chưa có
   * tài khoản. Đặc biệt quan trọng khi gửi phần mềm cho đồng nghiệp/khách hàng: máy họ
   * hoàn toàn trắng, phải đi qua bước khai báo tài khoản của CHÍNH HỌ trước đã.
   */
  applySetupLock(locked) {
    this.setupLocked = !!locked;
    document.body.classList.toggle('setup-locked', this.setupLocked);

    document.querySelectorAll('.nav-btn').forEach(b => {
      const isConfig = b.dataset.tab === 'tab-config';
      const isSystemCheck = b.dataset.action === 'runtime-check';
      if (this.setupLocked && !isConfig && !isSystemCheck) {
        b.classList.add('nav-locked');
        b.setAttribute('title', 'Hãy hoàn tất Cấu hình trước khi dùng phần này');
      } else {
        b.classList.remove('nav-locked');
        if (isSystemCheck) return; // Giữ tooltip kết quả/lần kiểm tra gần nhất.
        const label = b.querySelector('span')?.textContent?.trim();
        if (document.getElementById('app-sidebar')?.classList.contains('collapsed') && label) {
          b.title = label;
        } else {
          b.removeAttribute('title');
        }
      }
    });

    const banner = document.getElementById('setup-required-alert');
    if (banner) banner.classList.toggle('hidden', !this.setupLocked);
    if (this.setupLocked) this.switchTab('tab-config');
  }

  switchTab(tabId) {
    // Chưa cấu hình xong thì không cho rời tab Cấu hình.
    if (this.setupLocked && tabId !== 'tab-config') {
      const banner = document.getElementById('setup-required-alert');
      if (banner) {
        banner.classList.remove('hidden');
        banner.classList.remove('shake');
        void banner.offsetWidth;          // ép trình duyệt vẽ lại để chạy lại hiệu ứng
        banner.classList.add('shake');
        banner.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      return;
    }

    const btns = document.querySelectorAll('.nav-btn');
    btns.forEach(b => {
      if (b.dataset.tab === tabId) b.classList.add('active');
      else b.classList.remove('active');
    });
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    const targetPane = document.getElementById(tabId);
    if (targetPane) targetPane.classList.add('active');
    this.currentTab = tabId;
  }

  setupTabs() {
    const btns = document.querySelectorAll('.nav-btn');
    btns.forEach(btn => {
      btn.addEventListener('click', () => {
        const tabId = btn.dataset.tab;
        if (!tabId) return;
        this.switchTab(tabId);

        if (tabId === 'tab-candidates') {
          this.loadCandidates();
        } else if (tabId === 'tab-config') {
          this.loadConfig();
        } else if (tabId === 'tab-report') {
          if (!this.reportLoaded) this.loadReport();
        } else if (tabId === 'tab-parsing') {
          this.refreshParsingStatus(true);
          this.loadParsingResults();
        }
      });
    });
  }

  setupEventListeners() {
    document.getElementById('btn-menu-runtime-check')?.addEventListener('click', () => {
      this.loadRuntimeReadiness(true).catch(e => {
        console.error('runtime readiness err:', e);
        this.showAppToast('Không kiểm tra được hệ thống', String(e?.message || e), 'error');
      });
    });
    document.getElementById('btn-download-new')?.addEventListener('click', () => this.startDownload('moi'));
    document.getElementById('btn-download-all')?.addEventListener('click', () => this.startDownload('tatca'));
    document.getElementById('btn-retry-failed')?.addEventListener('click', () => this.startDownload('loi'));
    document.getElementById('btn-stop-download')?.addEventListener('click', () => this.stopDownload());

    const toggleOptBtn = document.getElementById('btn-toggle-page-options');
    const optCard = document.getElementById('page-options-card');
    toggleOptBtn?.addEventListener('click', () => {
      optCard?.classList.toggle('hidden');
      toggleOptBtn.setAttribute('aria-expanded', String(!optCard?.classList.contains('hidden')));
      if (optCard && !optCard.classList.contains('hidden')) {
        this.loadCheckpoint();
      }
    });

    document.getElementById('download-provider-select')?.addEventListener('change', () => {
      this.updateProviderBadge();
      // Hủy hiệu lực request của kênh cũ. Chỉ đọc SQLite khi khung nâng cao đang mở,
      // tránh một truy vấn checkpoint vô hình rồi lại truy vấn lần nữa khi người dùng mở khung.
      this.checkpointRequestId += 1;
      if (optCard && !optCard.classList.contains('hidden')) this.loadCheckpoint();
    });

    document.getElementById('btn-refresh-checkpoint')?.addEventListener('click', () => {
      this.loadCheckpoint();
    });

    document.getElementById('btn-resume-checkpoint')?.addEventListener('click', () => {
      // Backend tự đọc checkpoint mới nhất trong cùng một lệnh; không phụ thuộc text
      // trên giao diện nên chỉ cần bấm MỘT lần và không thể dùng nhầm giá trị cũ.
      this.startDownload('resume');
    });

    document.getElementById('btn-start-custom-download')?.addEventListener('click', () => {
      this.startDownload('custom');
    });

    document.getElementById('btn-copy-log')?.addEventListener('click', () => {
      const consoleEl = document.getElementById('log-console');
      if (!consoleEl) return;
      const text = consoleEl.innerText || consoleEl.textContent || '';
      if (!text.trim()) {
        this.showAppToast('Nhật ký trống', 'Chưa có nội dung nhật ký để sao chép.', 'info');
        return;
      }
      if (navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(text).then(() => {
          this.showAppToast('Đã sao chép nhật ký', 'Toàn bộ nội dung nhật ký đã được sao chép vào clipboard.', 'success');
        }).catch(() => this._fallbackCopyText(text, 'Đã sao chép nhật ký'));
      } else {
        this._fallbackCopyText(text, 'Đã sao chép nhật ký');
      }
    });

    document.getElementById('btn-clear-log')?.addEventListener('click', () => {
      document.getElementById('log-console').innerHTML = '';
    });

    document.getElementById('btn-apply-filter')?.addEventListener('click', () => {
      this.page = 1;
      this.loadCandidates();
    });
    const quickSearch = () => {
      this.page = 1;
      this.loadCandidates();
    };
    document.getElementById('btn-quick-search')?.addEventListener('click', quickSearch);
    document.getElementById('filter-search')?.addEventListener('keyup', (e) => {
      if (e.key === 'Enter') quickSearch();
    });
    document.getElementById('filter-source')?.addEventListener('change', () => {
      this.refreshCandidateAccountOptions();
    });
    document.getElementById('btn-reset-filter')?.addEventListener('click', () => {
      document.getElementById('filter-search').value = '';
      Array.from(document.getElementById('filter-source')?.options || []).forEach(o => o.selected = false);
      Array.from(document.getElementById('filter-account')?.options || []).forEach(o => o.selected = false);
      this.renderMultiCheckFilter('filter-source');
      this.refreshCandidateAccountOptions();
      document.getElementById('filter-status').value = '';
      const quickDate = document.getElementById('filter-quick-date');
      if (quickDate) quickDate.value = '';
      const dFrom = document.getElementById('filter-date-from');
      if (dFrom) dFrom.value = '';
      const dTo = document.getElementById('filter-date-to');
      if (dTo) dTo.value = '';
      document.getElementById('date-range-inputs')?.classList.add('hidden');
      this.page = 1;
      this.loadCandidates();
    });

    document.getElementById('page-size-select')?.addEventListener('change', (e) => {
      this.limit = Math.min(200, Math.max(20, parseInt(e.target.value) || 50));
      this.page = 1;
      this.loadCandidates();
    });

    document.getElementById('btn-first-page')?.addEventListener('click', () => {
      this.page = 1;
      this.loadCandidates();
    });

    document.getElementById('btn-prev-page')?.addEventListener('click', () => {
      if (this.page > 1) {
        this.page--;
        this.loadCandidates();
      }
    });

    document.getElementById('btn-next-page')?.addEventListener('click', () => {
      const totalPages = Math.max(1, Math.ceil(this.totalCandidates / this.limit));
      if (this.page < totalPages) {
        this.page++;
        this.loadCandidates();
      }
    });

    document.getElementById('btn-last-page')?.addEventListener('click', () => {
      const totalPages = Math.max(1, Math.ceil(this.totalCandidates / this.limit));
      this.page = totalPages;
      this.loadCandidates();
    });

    const jumpAction = () => {
      const totalPages = Math.max(1, Math.ceil(this.totalCandidates / this.limit));
      const target = parseInt(document.getElementById('page-jump-input')?.value || '1');
      this.page = Math.max(1, Math.min(totalPages, isNaN(target) ? 1 : target));
      this.loadCandidates();
    };

    document.getElementById('btn-jump-page')?.addEventListener('click', jumpAction);
    document.getElementById('page-jump-input')?.addEventListener('keyup', (e) => {
      if (e.key === 'Enter') jumpAction();
    });

    const markReportDirty = () => {
      this.reportFiltersDirty = true;
      const status = document.getElementById('report-filter-status');
      if (status) {
        status.textContent = 'Bộ lọc đã thay đổi · bấm Áp dụng để cập nhật';
        status.classList.remove('applied');
        status.classList.add('dirty');
      }
    };
    document.getElementById('report-source')?.addEventListener('change', () => {
      this.refreshReportAccountOptions();
      markReportDirty();
    });
    document.getElementById('report-account')?.addEventListener('change', markReportDirty);
    document.getElementById('report-position')?.addEventListener('change', markReportDirty);
    document.getElementById('report-time-range')?.addEventListener('change', (event) => {
      const custom = event.target.value === 'custom';
      document.getElementById('report-custom-dates')?.classList.toggle('hidden', !custom);
      const errorEl = document.getElementById('report-error');
      errorEl?.classList.add('hidden');
      markReportDirty();
    });
    ['report-date-from', 'report-date-to'].forEach(id => {
      document.getElementById(id)?.addEventListener('change', markReportDirty);
    });
    document.getElementById('btn-apply-report')?.addEventListener('click', () => this.loadReport());
    document.getElementById('btn-reset-report')?.addEventListener('click', () => {
      ['report-source', 'report-account', 'report-position'].forEach(id => {
        Array.from(document.getElementById(id)?.options || []).forEach(option => option.selected = false);
        this.renderMultiCheckFilter(id);
      });
      this.refreshReportAccountOptions();
      const defaults = { 'report-time-range': 'all',
        'report-date-from': '', 'report-date-to': '' };
      Object.entries(defaults).forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
      });
      document.getElementById('report-custom-dates')?.classList.add('hidden');
      this.loadReport();
    });

    document.getElementById('btn-export-excel')?.addEventListener('click', () => this.exportData('xlsx'));
    document.getElementById('btn-export-csv')?.addEventListener('click', () => this.exportData('csv'));
    document.getElementById('btn-export-zip')?.addEventListener('click', () => this.exportData('zip'));
    document.getElementById('btn-add-schedule-job')?.addEventListener('click', () => this.openScheduleEditor());
    document.getElementById('btn-parsing-backfill')?.addEventListener('click', async () => {
      const result = await this.api.start_cv_parsing(true, false, false, this.parsingFilters());
      this.showAppToast(result.ok ? 'Đã bắt đầu parsing' : 'Không thể bắt đầu', result.error || 'Các CV cũ chưa parse đã được xếp hàng.', result.ok ? 'success' : 'error');
      this.refreshParsingStatus();
    });
    document.getElementById('btn-parsing-continue')?.addEventListener('click', async () => {
      const result = await this.api.start_cv_parsing(false, false, false, this.parsingFilters());
      this.showAppToast(result.ok ? 'Đã tiếp tục parsing' : 'Không thể tiếp tục', result.error || 'Đang xử lý hàng đợi hiện có.', result.ok ? 'success' : 'error');
      this.refreshParsingStatus(true);
    });
    document.getElementById('btn-parsing-retry')?.addEventListener('click', async () => {
      const result = await this.api.start_cv_parsing(false, false, true, this.parsingFilters());
      this.showAppToast(result.ok ? 'Đã xếp lại CV lỗi' : 'Không thể thử lại', result.error || 'Chỉ các CV parsing chưa thành công được chạy lại.', result.ok ? 'success' : 'error');
      this.refreshParsingStatus(true);
    });
    document.getElementById('btn-parsing-stop')?.addEventListener('click', async () => {
      const result = await this.api.stop_cv_parsing();
      this.showAppToast('Đang dừng parsing', result.message || 'Sẽ dừng sau file hiện tại.', 'info');
      this.refreshParsingStatus(true);
    });
    document.getElementById('parsing-source')?.addEventListener('change', () => this.refreshParsingFilterOptions());
    document.getElementById('btn-reset-parsing-filter')?.addEventListener('click', () => {
      ['parsing-source', 'parsing-account', 'parsing-position'].forEach(id => {
        Array.from(document.getElementById(id)?.options || []).forEach(option => option.selected = false);
        this.renderMultiCheckFilter(id);
      });
      ['parsing-date-from', 'parsing-date-to'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
      this.refreshParsingFilterOptions();
      this.updateParsingFilterSummary();
    });
    ['parsing-account', 'parsing-position', 'parsing-date-from', 'parsing-date-to'].forEach(id =>
      document.getElementById(id)?.addEventListener('change', () => this.updateParsingFilterSummary()));
    document.getElementById('btn-copy-parsing-log')?.addEventListener('click', () => {
      const consoleEl = document.getElementById('parsing-log-console');
      if (!consoleEl) return;
      const text = consoleEl.innerText || consoleEl.textContent || '';
      if (!text.trim()) {
        this.showAppToast('Nhật ký trống', 'Chưa có nội dung nhật ký parsing để sao chép.', 'info');
        return;
      }
      if (navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(text).then(() => {
          this.showAppToast('Đã sao chép nhật ký parsing', 'Toàn bộ nội dung nhật ký parsing đã được sao chép vào clipboard.', 'success');
        }).catch(() => this._fallbackCopyText(text, 'Đã sao chép nhật ký parsing'));
      } else {
        this._fallbackCopyText(text, 'Đã sao chép nhật ký parsing');
      }
    });

    document.getElementById('btn-clear-parsing-log')?.addEventListener('click', () => {
      const consoleEl = document.getElementById('parsing-log-console');
      if (consoleEl) consoleEl.innerHTML = '<div class="log-line info">Đã xóa phần hiển thị. Nhật ký mới sẽ tiếp tục xuất hiện…</div>';
    });
    document.getElementById('btn-cancel-schedule-job')?.addEventListener('click', () => document.getElementById('schedule-job-editor')?.classList.add('hidden'));
    document.getElementById('btn-save-schedule-job')?.addEventListener('click', () => this.saveScheduleJob());
    document.getElementById('btn-close-schedule-job')?.addEventListener('click', () => document.getElementById('schedule-job-editor')?.classList.add('hidden'));
    document.getElementById('schedule-editor-sources')?.addEventListener('change', () => this.renderScheduleAccountOptions());
    document.querySelectorAll('.schedule-presets button').forEach(button => button.addEventListener('click', () => {
      document.getElementById('schedule-editor-interval').value = button.dataset.minutes;
    }));
    document.getElementById('cfg-schedule-enabled')?.addEventListener('change', async event => {
      event.target.disabled = true;
      const result = event.target.checked ? await this.api.start_schedule() : await this.api.stop_schedule();
      event.target.disabled = false;
      if (!result.ok && event.target.checked) {
        event.target.checked = false;
        this.showAppToast('Không thể bật hẹn giờ', result.error, 'error');
      }
      await this.refreshScheduleStatus();
    });

    document.getElementById('btn-browse-cv-folder')?.addEventListener('click', async () => {
      if (!this.api) return;
      try {
        const folder = await this.api.select_cv_folder();
        if (folder) document.getElementById('cfg-cv-folder').value = folder;
      } catch (e) {
        console.error("select_cv_folder err:", e);
        alert("Không thể mở hộp thoại chọn thư mục: " + (e && e.message || e));
      }
    });
    document.getElementById('btn-browse-db-path')?.addEventListener('click', async () => {
      if (!this.api) return;
      try {
        const dbPath = await this.api.select_db_path();
        if (dbPath) document.getElementById('cfg-db-path').value = dbPath;
      } catch (e) {
        console.error("select_db_path err:", e);
        alert("Không thể mở hộp thoại chọn nơi lưu cơ sở dữ liệu: " + (e && e.message || e));
      }
    });
    const wireBrowseFile = (btnId, purpose, inputId) => {
      document.getElementById(btnId)?.addEventListener('click', async () => {
        if (!this.api) return;
        try {
          const picked = await this.api.select_open_file(purpose);
          if (picked) document.getElementById(inputId).value = picked;
        } catch (e) {
          console.error(`select_open_file(${purpose}) err:`, e);
        }
      });
    };
    wireBrowseFile('btn-browse-ca-bundle', 'ca_bundle', 'cfg-ssl-ca-bundle');
    wireBrowseFile('btn-browse-chromedriver', 'chromedriver', 'cfg-chromedriver-path');
    document.getElementById('btn-save-config')?.addEventListener('click', () => this.saveConfig());
    document.getElementById('btn-check-health')?.addEventListener('click', () => this.checkSystemHealth());
    document.getElementById('btn-backup-db')?.addEventListener('click', () => this.backupDatabase());
    document.getElementById('btn-delete-data')?.addEventListener('click', () => this.deleteCandidateData());
    document.getElementById('btn-open-provider-browser')?.addEventListener('click', () => {
      const source = document.getElementById('config-browser-provider')?.value || 'topcv';
      this.openProviderBrowser(source, document.getElementById('btn-open-provider-browser'));
    });
    document.getElementById('btn-clear-provider-password')?.addEventListener('click', async () => {
      const source = document.getElementById('config-browser-provider')?.value || 'topcv';
      if (!window.confirm(`Xóa mật khẩu đã lưu của ${source}?`)) return;
      const result = await this.api.clear_provider_password(source);
      this.showAppToast(result.ok ? 'Đã xóa mật khẩu' : 'Không thể xóa',
        result.ok ? 'Tài khoản vẫn được giữ nguyên.' : result.error,
        result.ok ? 'success' : 'error');
      if (result.ok) this.loadConfig();
    });

    document.getElementById('btn-test-notifier')?.addEventListener('click', async () => {
      if (!this.api) return;
      const btn = document.getElementById('btn-test-notifier');
      if (btn) btn.disabled = true;
      try {
        const res = await this.api.test_notification();
        if (res.ok) this.showAppToast('Kiểm tra thông báo',
          'Đã gửi thông báo thử nghiệm tới Windows.', 'success');
        else this.showAppToast('Thông báo Windows đang bị chặn', res.error, 'error', 7000);
      } catch (e) {
        console.error("test_notification err:", e);
        this.showAppToast('Không thể gửi thông báo', e && e.message || String(e), 'error', 7000);
      } finally {
        if (btn) btn.disabled = false;
      }
    });

    document.querySelectorAll('.external-link').forEach(link => {
      link.addEventListener('click', async (e) => {
        e.preventDefault();
        const url = link.dataset.url || link.href;
        try {
          if (this.api && this.api.open_external_url) {
            await this.api.open_external_url(url);
          } else {
            window.open(url, '_blank');
          }
        } catch (err) {
          console.error("open_external_url err:", err);
          window.open(url, '_blank');
        }
      });
    });
  }

  setupAccountManager() {
    document.getElementById('btn-add-provider-account')?.addEventListener('click', () => this.openAccountEditor());
    document.getElementById('btn-cancel-provider-account')?.addEventListener('click', () => {
      document.getElementById('provider-account-editor')?.classList.add('hidden');
      const error = document.getElementById('account-editor-error');
      if (error) { error.textContent = ''; error.classList.add('hidden'); }
    });
    document.getElementById('btn-save-provider-account')?.addEventListener('click', () => this.saveProviderAccount());
    document.getElementById('provider-account-editor')?.addEventListener('keydown', event => {
      if (event.key === 'Enter' && event.target?.tagName !== 'BUTTON') {
        event.preventDefault();
        this.saveProviderAccount();
      }
    });
  }

  setupUIEnhancements() {
    // Theme do màn Cấu hình quản lý duy nhất (radio cfg-theme-mode -> applyThemeFromConfig).
    // Không còn nút bật/tắt ở sidebar và không còn seed từ localStorage 'theme'.
    document.querySelectorAll('.password-toggle-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const wrapper = btn.closest('.password-input-wrapper');
        const passInput = wrapper ? wrapper.querySelector('input') : null;
        if (passInput) {
          const type = passInput.getAttribute('type') === 'password' ? 'text' : 'password';
          passInput.setAttribute('type', type);
          btn.textContent = type === 'password' ? '👁' : '🙈';
        }
      });
    });

    document.querySelectorAll('.pattern-tag').forEach(tag => {
      tag.addEventListener('click', () => {
        const patternInput = document.getElementById('cfg-pattern');
        if (patternInput) {
          patternInput.value += tag.dataset.tag;
        }
      });
    });

  }

  /* ================= HẸN GIỜ (SCHEDULER) ================= */
  updateTimerUI(nextRunAt) {
    const timerSwitch = document.getElementById('cfg-schedule-enabled');
    const timerBanner = document.getElementById('timer-banner-card');
    const timerTitle = document.getElementById('timer-status-title');
    const timerDesc = document.getElementById('timer-status-desc');
    const timerIcon = document.getElementById('timer-status-icon');
    const isOn = !!(timerSwitch && timerSwitch.checked);
    const smart = document.getElementById('schedule-smart-status');
    smart?.classList.toggle('is-off', !isOn);
    const smartTitle = smart?.querySelector('strong');
    const smartText = smart?.querySelector('small');
    if (smartTitle) smartTitle.textContent = isOn ? 'Bộ hẹn giờ đang hoạt động' : 'Bộ hẹn giờ đang tắt';
    if (smartText) smartText.textContent = isOn
      ? (nextRunAt ? `Tác vụ kế tiếp lúc ${this._fmtFullDateTime(nextRunAt)}.` : 'Đang chờ lịch hợp lệ tiếp theo.')
      : 'Các lịch được giữ nguyên nhưng sẽ không tự chạy.';
    const smartNext = document.getElementById('schedule-next-run');
    if (smartNext) smartNext.textContent = isOn && nextRunAt ? this._fmtFullDateTime(nextRunAt) : '—';

    if (isOn) {
      timerBanner?.classList.add('active-banner');
      if (timerTitle) timerTitle.textContent = "Chế Độ Hẹn Giờ Đang Hoạt Động";
      if (timerDesc) {
        timerDesc.textContent = nextRunAt
          ? `Lần chạy kế tiếp: ${this._fmtFullDateTime(nextRunAt)}`
          : "Hệ thống đang tự động cào CV mới ngầm theo chu kỳ cài đặt";
      }
      if (timerIcon) timerIcon.textContent = "🔥";
    } else {
      timerBanner?.classList.remove('active-banner');
      if (timerTitle) timerTitle.textContent = "Chế Độ Hẹn Giờ Đang Tắt";
      if (timerDesc) timerDesc.textContent = "Kích hoạt nút bật/tắt bên dưới để tự động cào CV mới hằng giờ";
      if (timerIcon) timerIcon.textContent = "⏱";
    }
  }

  async refreshScheduleStatus() {
    if (!this.api) return;
    try {
      const st = await this.api.get_schedule_status();
      const timerSwitch = document.getElementById('cfg-schedule-enabled');
      if (timerSwitch) timerSwitch.checked = st.running;
      this.updateTimerUI(st.next_run_at);
      this.scheduleJobs = st.jobs || this.scheduleJobs || [];
      const enabledCount = document.getElementById('schedule-enabled-count');
      if (enabledCount) enabledCount.textContent = Number(st.enabled_count || 0).toLocaleString();
      this.renderScheduleJobs();
    } catch (e) {
      console.error("get_schedule_status err:", e);
    }
  }

  /** Gọi từ Python (web_api.py) mỗi khi hẹn giờ tính lại lần chạy kế tiếp. */
  onScheduleNextRun(nextRunAt) {
    this.updateTimerUI(nextRunAt);
    this.refreshScheduleStatus();
  }

  _fmtFullDateTime(sqlDateTime) {
    // "YYYY-MM-DD HH:MM:SS" -> "dd/MM/yyyy HH:mm"
    const [datePart, timePart] = String(sqlDateTime).split(' ');
    const [y, m, d] = (datePart || '').split('-');
    const hm = (timePart || '').slice(0, 5);
    return `${d}/${m}/${y} ${hm}`;
  }

  /* MODAL TÙY CHỈNH CỘT DỮ LIỆU */
  setupColumnModal() {
    const modal = document.getElementById('column-modal');
    const btnOpen = document.getElementById('btn-toggle-columns');
    const btnClose = document.getElementById('btn-close-column-modal');
    const btnSave = document.getElementById('btn-save-columns');
    const btnSelectAll = document.getElementById('btn-select-all-columns');
    const btnReset = document.getElementById('btn-reset-columns');
    const grid = document.getElementById('column-checkboxes-grid');

    const renderCheckboxes = () => {
      grid.innerHTML = '';
      this.allColumns.forEach(col => {
        const isChecked = this.visibleColumns.includes(col.key);
        const item = document.createElement('label');
        item.className = 'column-checkbox-item';
        item.innerHTML = `
          <input type="checkbox" value="${col.key}" ${isChecked ? 'checked' : ''}>
          <span>${col.label}</span>
        `;
        grid.appendChild(item);
      });
    };

    btnOpen?.addEventListener('click', () => {
      renderCheckboxes();
      modal.classList.remove('hidden');
    });

    btnClose?.addEventListener('click', () => modal.classList.add('hidden'));

    btnSelectAll?.addEventListener('click', () => {
      grid.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
    });

    btnReset?.addEventListener('click', () => {
      const defaultKeys = this.allColumns.filter(c => c.default).map(c => c.key);
      grid.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        cb.checked = defaultKeys.includes(cb.value);
      });
    });

    btnSave?.addEventListener('click', () => {
      const selected = Array.from(grid.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.value);
      if (selected.length === 0) {
        alert("⚠️ Vui lòng chọn ít nhất 1 cột hiển thị!");
        return;
      }
      this.saveColumns(selected);
      modal.classList.add('hidden');
      this.loadCandidates();
    });
  }

  /* MODAL XEM CV TRỰC TIẾP NỘI BỘ */
  setupCvModal() {
    const modal = document.getElementById('cv-viewer-modal');
    const btnClose = document.getElementById('btn-close-cv-modal');
    btnClose?.addEventListener('click', () => {
      modal.classList.add('hidden');
      document.getElementById('cv-viewer-iframe').src = '';
    });
    document.getElementById('btn-download-cv-file')?.addEventListener('click', async () => {
      const button = document.getElementById('btn-download-cv-file');
      const filename = button?.dataset.filename || '';
      if (!filename) return;
      button.disabled = true;
      const result = await this.api.save_cv_as(filename);
      button.disabled = false;
      if (result.ok) this.showAppToast('Đã lưu CV', result.path, 'success', 7000);
      else if (!result.cancelled) this.showAppToast('Không thể lưu CV', result.error, 'error', 7000);
    });
  }

  /* MODAL TRA CỨU LỊCH SỬ NHẬT KÝ SQLITE */
  setupLogHistoryModal() {
    const modal = document.getElementById('log-history-modal');
    const btnOpen = document.getElementById('btn-open-log-history');
    const btnClose1 = document.getElementById('btn-close-log-history-modal');
    const btnClose2 = document.getElementById('btn-close-log-modal-footer');
    const btnFilter = document.getElementById('btn-filter-logs');

    btnOpen?.addEventListener('click', () => {
      modal.classList.remove('hidden');
      this.fetchLogHistory();
    });

    btnClose1?.addEventListener('click', () => modal.classList.add('hidden'));
    btnClose2?.addEventListener('click', () => modal.classList.add('hidden'));

    btnFilter?.addEventListener('click', () => this.fetchLogHistory());

    document.getElementById('log-search-input')?.addEventListener('keyup', (e) => {
      if (e.key === 'Enter') this.fetchLogHistory();
    });
  }

  async fetchLogHistory() {
    if (!this.api || !this.api.get_history_logs) return;
    const filters = {
      search: document.getElementById('log-search-input')?.value || '',
      level: document.getElementById('log-level-select')?.value || '',
      limit: 200
    };

    const consoleEl = document.getElementById('log-history-console');
    consoleEl.innerHTML = '<div class="log-line text-muted">Đang tải nhật ký từ CSDL...</div>';

    let res;
    try {
      res = await this.api.get_history_logs(filters);
    } catch (e) {
      consoleEl.innerHTML = `<div class="log-line text-danger">Lỗi truy vấn: ${this.escapeHtml(String(e))}</div>`;
      return;
    }

    consoleEl.innerHTML = '';

    if (!res.items || res.items.length === 0) {
      consoleEl.innerHTML = '<div class="log-line text-muted">Không tìm thấy bản ghi nhật ký nào phù hợp trong CSDL.</div>';
      document.getElementById('log-history-count').textContent = 'Hiển thị 0 bản ghi nhật ký';
      return;
    }

    res.items.forEach(log => {
      const line = document.createElement('div');
      line.className = 'log-line';
      if (log.level === 'ERROR' || log.message.includes('LỖI') || log.message.includes('✗')) {
        line.classList.add('text-danger');
      } else if (log.level === 'SUCCESS' || log.message.includes('✓') || log.message.includes('KẾT QUẢ')) {
        line.classList.add('text-success');
      }

      line.textContent = `[${log.created_at}] ${log.message}`;
      consoleEl.appendChild(line);
    });

    document.getElementById('log-history-count').textContent = `Hiển thị ${res.items.length} / ${res.total.toLocaleString()} bản ghi nhật ký trong CSDL`;
  }

  /* MODAL XEM CHI TIẾT ỨNG VIÊN (ALL 19 FIELDS) */
  setupCandidateDetailModal() {
    const modal = document.getElementById('candidate-detail-modal');
    const btnClose1 = document.getElementById('btn-close-detail-modal');
    const btnClose2 = document.getElementById('btn-close-detail-modal-footer');

    btnClose1?.addEventListener('click', () => modal.classList.add('hidden'));
    btnClose2?.addEventListener('click', () => modal.classList.add('hidden'));
  }

  async openCandidateDetail(c) {
    if (!c) return;
    const modal = document.getElementById('candidate-detail-modal');
    // Bảng danh sách có thể đang là snapshot RAM cũ (engine tải/parsing trên ổ
    // đám mây). Đọc lại đúng dòng này từ CSDL để các trường chi tiết (nơi làm
    // việc mong muốn, tình trạng hôn nhân, ngoại ngữ...) hiển thị đúng.
    if (this.api?.get_candidate_detail && c.source && c.cv_id) {
      try {
        const fresh = await this.api.get_candidate_detail(c.source, c.account, c.cv_id);
        if (fresh?.ok && fresh.candidate) {
          const merged = { ...c, ...fresh.candidate };
          // Cảnh báo được backend tính riêng ở get_candidates, không lấy từ dòng thô.
          merged.alerts = c.alerts;
          merged.alerts_short = c.alerts_short;
          merged.applications = c.applications;
          c = merged;
        }
      } catch (_e) { /* giữ nguyên dữ liệu bảng nếu đọc lẻ thất bại */ }
    }
    document.getElementById('detail-candidate-fullname').textContent = c.fullname || 'Ứng viên không tên';

    const fields = this.allColumns.filter(field => !['stt', 'alerts'].includes(field.key));
    const visible = fields.filter(field => this.visibleColumns.includes(field.key));
    const hidden = fields.filter(field => !this.visibleColumns.includes(field.key));
    const renderFields = items => `<div class="detail-grid">${items.map(field => {
      let value = c[field.key];
      if (field.key === 'source') value = String(value || '').toUpperCase();
      if (field.key === 'is_viewed') value = Number(value) ? 'Đã xem' : 'Chưa xem';
      return `<div class="detail-item-box"><div class="detail-item-label">${this.escapeHtml(field.label)}</div><div class="detail-item-value">${this.escapeHtml(String(value ?? '').trim() || '—')}</div></div>`;
    }).join('')}</div>`;
    const body = document.getElementById('detail-candidate-body');
    body.innerHTML = `${c.alerts ? `<section class="detail-section"><h4 class="detail-section-title">⚠️ Cảnh báo cần lưu ý <span>Hiển thị đầy đủ</span></h4>${this.renderCandidateAlertDetail(c)}</section>` : ''}
      <section class="detail-section"><h4 class="detail-section-title">Thông tin đang hiển thị trên bảng</h4>${renderFields(visible)}</section>
      ${hidden.length ? `<details class="detail-extra"><summary>Xem thêm ${hidden.length} trường thông tin</summary>${renderFields(hidden)}</details>` : ''}`;
    this.bindApplicationCvButtons(body);

    const btnCv = document.getElementById('btn-detail-open-cv');
    if (c.filename) {
      btnCv.style.display = 'inline-flex';
      btnCv.onclick = () => {
        this.openCvInModal(c.filename);
      };
    } else {
      btnCv.style.display = 'none';
    }

    modal.classList.remove('hidden');
    body.insertAdjacentHTML('beforeend', '<div id="candidate-parsing-detail" class="modal-parsing-section"><div class="modal-parsing-header"><div class="modal-parsing-title"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg><span>KẾT QUẢ BÓC TÁCH NỘI DUNG CV</span></div><span class="badge badge-info">Đang tải...</span></div><div class="detail-item-value">Đang đọc kết quả bóc tách chi tiết…</div></div>');
    try {
      const parsed = await this.api.get_candidate_parsing(c.source, c.account, c.cv_id);
      const parsingBox = document.getElementById('candidate-parsing-detail');
      if (!parsingBox || modal.classList.contains('hidden')) return;
      if (parsed.ok && parsed.document) {
        const d = parsed.document;
        const parsedFields = d.fields || {};
        const labels = {
          done: '✓ Đã parsing xong',
          pending: '⏳ Đang chờ xử lý',
          running: '↻ Đang bóc nội dung',
          needs_ocr: '⚡ Cần nhận diện OCR',
          empty: '⚠️ Không bóc được text / File rỗng',
          unsupported: '⚠️ Định dạng chưa hỗ trợ',
          error: '❌ Lỗi bóc nội dung'
        };
        const statusBadgeClass = d.parse_status === 'done' ? 'badge-success' : (d.parse_status === 'needs_ocr' ? 'badge-warning' : (d.parse_status === 'pending' ? 'badge-info' : 'badge-danger'));
        const qualityPct = Math.round(Number(d.quality_score || 0) * 100);
        
        const emails = parsedFields.emails || [];
        const phones = parsedFields.phones || [];
        const urls = parsedFields.urls || [];

        parsingBox.innerHTML = `
          <div class="modal-parsing-header">
            <div class="modal-parsing-title">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>
              <span>KẾT QUẢ BÓC TÁCH NỘI DUNG CV (PARSING DETAILS)</span>
            </div>
            <span class="badge ${statusBadgeClass}">${this.escapeHtml(labels[d.parse_status] || d.parse_status)}</span>
          </div>

          <div class="modal-parsing-chips">
            <div class="modal-parsing-chip">
              <span class="chip-label">Phương thức bóc</span>
              <strong class="chip-value">${this.escapeHtml(d.extraction_method || '—')}</strong>
            </div>
            <div class="modal-parsing-chip">
              <span class="chip-label">Ký tự trích xuất</span>
              <strong class="chip-value">${Number(d.text_length || 0).toLocaleString()} ký tự</strong>
            </div>
            <div class="modal-parsing-chip">
              <span class="chip-label">Độ tin cậy / Chất lượng</span>
              <strong class="chip-value">${qualityPct}%</strong>
            </div>
            <div class="modal-parsing-chip">
              <span class="chip-label">Hoàn tất lúc</span>
              <strong class="chip-value">${this.escapeHtml(d.parsed_at || d.updated_at || '—')}</strong>
            </div>
          </div>

          ${(emails.length || phones.length || urls.length) ? `
          <div class="parsed-entities-grid">
            <div class="parsed-entity-box">
              <div class="parsed-entity-label">📧 Email trích xuất:</div>
              <div class="parsed-entity-list">
                ${emails.length ? emails.map(e => `<span class="parsed-entity-tag">${this.escapeHtml(e)}</span>`).join('') : '<span style="color:var(--tf-muted);font-size:0.8rem;">Không tìm thấy</span>'}
              </div>
            </div>
            <div class="parsed-entity-box">
              <div class="parsed-entity-label">📱 Số điện thoại:</div>
              <div class="parsed-entity-list">
                ${phones.length ? phones.map(p => `<span class="parsed-entity-tag">${this.escapeHtml(p)}</span>`).join('') : '<span style="color:var(--tf-muted);font-size:0.8rem;">Không tìm thấy</span>'}
              </div>
            </div>
          </div>
          ` : ''}

          ${d.parse_error ? `
          <div class="alert-box alert-warning" style="margin-bottom:12px;padding:8px 12px;border-radius:6px;font-size:0.82rem;">
            <strong>Lưu ý bóc tách:</strong> ${this.escapeHtml(d.parse_error)}
          </div>
          ` : ''}

          <div class="parsed-text-wrapper">
            <div class="parsed-text-toolbar">
              <strong>TOÀN BỘ VĂN BẢN TRÍCH XUẤT TỪ CV</strong>
              <button id="btn-copy-parsed-cv-text" type="button" class="btn btn-sm btn-secondary" title="Sao chép toàn bộ nội dung text">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                <span>Sao chép text</span>
              </button>
            </div>
            ${d.full_text || d.text ? `
            <pre class="parsed-cv-text" id="modal-parsed-cv-text-pre">${this.escapeHtml(d.full_text || d.text)}</pre>
            ` : `
            <div class="detail-item-value" style="padding:16px;">Chưa có nội dung văn bản trích xuất.</div>
            `}
          </div>
        `;

        document.getElementById('btn-copy-parsed-cv-text')?.addEventListener('click', () => {
          const text = d.full_text || d.text || '';
          if (navigator.clipboard?.writeText) {
            navigator.clipboard.writeText(text).then(() => {
              this.showAppToast('Đã sao chép văn bản CV', 'Nội dung bóc tách đã được sao chép vào bộ nhớ tạm.', 'success');
            }).catch(() => this._fallbackCopyText(text, 'Đã sao chép văn bản CV'));
          } else {
            this._fallbackCopyText(text, 'Đã sao chép văn bản CV');
          }
        });

      } else if (parsed.busy) {
        parsingBox.innerHTML = `<div class="modal-parsing-header"><div class="modal-parsing-title"><span>KẾT QUẢ BÓC TÁCH NỘI DUNG CV</span></div><span class="badge badge-warning">Đang bận</span></div><div class="detail-item-value">${this.escapeHtml(parsed.error || 'Kết quả sẽ cập nhật sau khi tác vụ hiện tại hoàn tất.')}</div>`;
      } else {
        parsingBox.innerHTML = '<div class="modal-parsing-header"><div class="modal-parsing-title"><span>KẾT QUẢ BÓC TÁCH NỘI DUNG CV</span></div><span class="badge badge-secondary">Chưa xếp hàng</span></div><div class="detail-item-value">CV này chưa được đưa vào hàng đợi parsing. Bạn có thể bấm "Bóc CV cũ chưa parsing" tại tab Parsing CV.</div>';
      }
    } catch (e) { console.error('candidate parsing detail', e); }
  }

  /* BỘ LỌC THỜI GIAN ỨNG TUYỂN (QUICK & CUSTOM DATE RANGE) */
  setupDateFilter() {
    const quickSelect = document.getElementById('filter-quick-date');
    const rangeBox = document.getElementById('date-range-inputs');
    const dateFrom = document.getElementById('filter-date-from');
    const dateTo = document.getElementById('filter-date-to');

    if (!quickSelect) return;

    const formatDate = (d) => {
      const year = d.getFullYear();
      const month = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      return `${year}-${month}-${day}`;
    };

    quickSelect.addEventListener('change', (e) => {
      const val = e.target.value;
      const today = new Date();

      if (val === 'custom') {
        rangeBox?.classList.remove('hidden');
        return;
      }

      rangeBox?.classList.add('hidden');

      if (!val) {
        if (dateFrom) dateFrom.value = '';
        if (dateTo) dateTo.value = '';
      } else if (val === 'today') {
        if (dateFrom) dateFrom.value = formatDate(today);
        if (dateTo) dateTo.value = formatDate(today);
      } else if (val === '7days') {
        const d7 = new Date();
        d7.setDate(today.getDate() - 7);
        if (dateFrom) dateFrom.value = formatDate(d7);
        if (dateTo) dateTo.value = formatDate(today);
      } else if (val === '30days') {
        const d30 = new Date();
        d30.setDate(today.getDate() - 30);
        if (dateFrom) dateFrom.value = formatDate(d30);
        if (dateTo) dateTo.value = formatDate(today);
      } else if (val === 'this_month') {
        const dMonth = new Date(today.getFullYear(), today.getMonth(), 1);
        if (dateFrom) dateFrom.value = formatDate(dMonth);
        if (dateTo) dateTo.value = formatDate(today);
      }

      this.page = 1;
      this.loadCandidates();
    });
  }

  async openCvInModal(filename) {
    if (!this.api || !filename) return;
    let res;
    try {
      res = await this.api.get_cv_data(filename);
    } catch (e) {
      console.error("get_cv_data err:", e);
      alert("⚠️ Không thể mở CV: " + (e && e.message || e));
      return;
    }
    if (!res.ok) {
      alert("⚠️ Không thể mở CV: " + res.error);
      return;
    }
    const modal = document.getElementById('cv-viewer-modal');
    const iframe = document.getElementById('cv-viewer-iframe');
    const titleEl = document.getElementById('cv-viewer-filename');
    const downloadBtn = document.getElementById('btn-download-cv-file');

    titleEl.textContent = res.filename;
    iframe.src = res.data_url;
    downloadBtn.dataset.filename = res.filename;

    modal.classList.remove('hidden');
  }

  updateProviderBadge() {
    const select = document.getElementById('download-provider-select');
    const badge = document.getElementById('active-account-badge');
    if (!select || !badge) return;
    const opt = select.selectedOptions?.[0];
    if (!opt || !opt.value) {
      badge.textContent = 'Chưa chọn';
      badge.className = 'provider-badge';
      return;
    }
    const val = opt.value.toLowerCase();
    let cls = 'topcv';
    let text = 'TopCV';
    if (val.includes('vietnamworks')) { cls = 'vietnamworks'; text = 'VietnamWorks'; }
    else if (val.includes('careerviet')) { cls = 'careerviet'; text = 'CareerViet'; }
    else if (val.includes('vieclam24h')) { cls = 'vieclam24h'; text = 'Việc Làm 24h'; }
    else if (val.includes('itviec')) { cls = 'itviec'; text = 'ITViec'; }
    else if (val.includes('joboko')) { cls = 'joboko'; text = 'Joboko'; }
    else if (val.includes('jobsgo')) { cls = 'jobsgo'; text = 'JobsGO'; }
    badge.className = `provider-badge ${cls}`;
    badge.textContent = text;
  }

  async loadProviders() {
    if (!this.api) return;
    const providers = await this.api.get_providers();
    const select = document.getElementById('download-provider-select');
    select.innerHTML = '';
    providers.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id;
      opt.dataset.accountId = p.account_id || '';
      opt.textContent = `${p.provider_name} · ${p.display_name}${p.email && p.email !== p.display_name ? ` · ${p.email}` : ''}` + (p.is_experimental ? ' (Đang phát triển)' : '');
      opt.disabled = !p.is_enabled;
      select.appendChild(opt);
    });
    if (!providers.length) select.innerHTML = '<option value="">Chưa có tài khoản vận hành đang bật</option>';
    this.updateProviderBadge();
  }

  async updateStats() {
    if (!this.api) return;
    try {
      const st = await this.api.get_stats();
      this.sidebarBaseTotal = Number(st.total || 0);
      document.getElementById('sidebar-db-count').textContent = `${st.total.toLocaleString()} hồ sơ`;
      return st;
    } catch (e) {
      console.error("get_stats err:", e);
    }
  }

  async loadCheckpoint() {
    if (!this.api) return;
    const card = document.getElementById('page-options-card');
    if (!card || card.classList.contains('hidden')) return;
    const providerSelect = document.getElementById('download-provider-select');
    const providerId = providerSelect?.value || '';
    const accountId = providerSelect?.selectedOptions?.[0]?.dataset?.accountId || '';
    const providerLabel = document.getElementById('download-provider-select')?.selectedOptions?.[0]?.textContent || providerId;
    const requestId = ++this.checkpointRequestId;
    const banner = document.getElementById('checkpoint-banner');
    const infoEl = document.getElementById('checkpoint-info');
    const btnResume = document.getElementById('btn-resume-checkpoint');
    const btnRefresh = document.getElementById('btn-refresh-checkpoint');
    const numEl = document.getElementById('checkpoint-page-num');

    banner?.classList.remove('is-ready', 'is-empty', 'is-error', 'is-busy');
    banner?.classList.add('is-checking');
    banner?.setAttribute('aria-busy', 'true');
    if (infoEl) infoEl.innerHTML = `<i class="checkpoint-spinner" aria-hidden="true"></i><span><strong>Đang kiểm tra bộ nhớ ${this.escapeHtml(providerLabel)}…</strong><small>Vui lòng chờ trong giây lát; dữ liệu có thể đang được đọc từ ổ đĩa đám mây / mạng chia sẻ.</small></span>`;
    if (btnResume) {
      btnResume.classList.add('hidden');
      btnResume.disabled = true;
    }
    btnRefresh?.classList.add('hidden');

    try {
      const cp = await this.api.get_checkpoint(providerId, accountId);
      // Người dùng có thể đổi kênh trong lúc SQLite đang trả lời. Không cho kết quả cũ
      // ghi đè checkpoint của kênh mới.
      const selectedOption = document.getElementById('download-provider-select')?.selectedOptions?.[0];
      if (requestId !== this.checkpointRequestId || selectedOption?.value !== providerId ||
          selectedOption?.dataset?.accountId !== accountId) return;

      banner?.classList.remove('is-checking');
      if (cp?.busy) {
        banner?.classList.add('is-busy');
        const saved = cp.has_more && cp.next_page > 0
          ? ` Bộ nhớ gần nhất đang ở trang ${cp.next_page}/${cp.total_pages || '?'}.`
          : '';
        if (infoEl) infoEl.innerHTML = `<span><strong>Đang có tác vụ dữ liệu chạy.</strong><small>${saved} Có thể kiểm tra và tiếp tục sau khi tác vụ hoàn tất.</small></span>`;
        btnRefresh?.classList.remove('hidden');
      } else if (cp && cp.has_more && cp.next_page > 0) {
        banner?.classList.add('is-ready');
        const direction = cp.reverse ? 'tải ngược' : 'tải xuôi';
        if (infoEl) infoEl.innerHTML = `<span><strong>Đã tìm thấy lượt backup đang dở.</strong><small>Tiếp tục từ trang ${cp.next_page}/${cp.total_pages || '?'} · ${direction} · ${this.escapeHtml(cp.timestamp || 'gần đây')}</small></span>`;
        if (numEl) numEl.textContent = cp.next_page;
        if (btnResume) {
          btnResume.classList.remove('hidden');
          btnResume.disabled = false;
        }
      } else {
        banner?.classList.add('is-empty');
        if (infoEl) infoEl.innerHTML = cp && cp.last_page > 0
          ? '<span><strong>Lượt backup trước đã hoàn tất.</strong><small>Không còn trang đang dở; bạn có thể bắt đầu một lượt backup toàn bộ mới.</small></span>'
          : '<span><strong>Chưa có bộ nhớ backup cho kênh này.</strong><small>Đây có thể là lần chạy đầu tiên; hãy chọn “Backup toàn bộ lịch sử”.</small></span>';
      }
    } catch (e) {
      if (requestId !== this.checkpointRequestId) return;
      console.error("loadCheckpoint err:", e);
      banner?.classList.remove('is-checking');
      banner?.classList.add('is-error');
      if (infoEl) infoEl.innerHTML = `<span><strong>Chưa kiểm tra được bộ nhớ backup.</strong><small>${this.escapeHtml(e?.message || String(e))}</small></span>`;
      btnRefresh?.classList.remove('hidden');
    } finally {
      if (requestId === this.checkpointRequestId) banner?.setAttribute('aria-busy', 'false');
    }
  }

  async startDownload(mode) {
    if (!this.api) return;

    const providerOption = document.getElementById('download-provider-select')?.selectedOptions?.[0];
    const providerId = providerOption?.value || '';
    const accountId = providerOption?.dataset?.accountId || '';
    const providerLabel = providerOption?.textContent || providerId;
    if (!providerId || !accountId) {
      this.showAppToast('Chưa chọn tài khoản', 'Hãy bật hoặc thêm một tài khoản trong Danh sách tài khoản vận hành.', 'error');
      return;
    }
    const modeLabels = {
      moi: 'đồng bộ CV mới', tatca: 'backup toàn bộ lịch sử',
      resume: 'tiếp tục lượt backup', loi: 'tải lại CV lỗi', custom: 'tải theo phạm vi trang'
    };
    const now = new Date().toLocaleTimeString('vi-VN', { hour12: false });

    // Phản hồi ngay tại thời điểm click. Trước đây giao diện chờ updateStats() đọc
    // Google Drive xong rồi mới đổi trạng thái nên người dùng tưởng nút không hoạt động.
    this.setDownloadingState(true, true);
    this.addLog(`[${now}] Đã nhận yêu cầu ${modeLabels[mode] || 'đồng bộ'} · ${providerLabel}. Đang kiểm tra cấu hình và phiên trình duyệt…`);

    try {
      const validation = await this.api.validate_provider_config(providerId, accountId);
      if (!validation.ok) {
        this.addLog(`[${new Date().toLocaleTimeString('vi-VN', { hour12: false })}] ! Không thể bắt đầu: cấu hình ${providerLabel} chưa đầy đủ.`);
        this.setDownloadingState(false);
        alert(`⚠️ Chưa đủ cấu hình cho nguồn đang chọn:\n\n${validation.errors.join('\n')}`);
        this.switchTab('tab-config');
        return;
      }
    } catch (e) {
      console.error("validate_provider_config err:", e);
      this.addLog(`[${new Date().toLocaleTimeString('vi-VN', { hour12: false })}] ! Không kiểm tra được cấu hình: ${e?.message || String(e)}`);
      this.setDownloadingState(false);
      return;
    }
    
    const options = { account_ids: [accountId] };
    if (mode === 'custom') {
      const sp = parseInt(document.getElementById('input-start-page')?.value || '1');
      const ep = document.getElementById('input-end-page')?.value;
      const reverse = document.getElementById('chk-reverse-order')?.checked || false;
      options.start_page = isNaN(sp) ? 1 : sp;
      if (ep && !isNaN(parseInt(ep))) options.end_page = parseInt(ep);
      options.reverse = reverse;
    }

    this.downloadMode = mode;
    // sidebarBaseTotal đã được nạp nền và tiếp tục được cập nhật realtime. Không đọc
    // lại SQLite trên đường khởi động chỉ để lấy cùng một con số.
    this.downloadBaseStats = { total: this.sidebarBaseTotal };
    this.liveNewTotal = 0;
    this.addLog(`[${new Date().toLocaleTimeString('vi-VN', { hour12: false })}] Cấu hình hợp lệ. Đang bàn giao tác vụ cho bộ máy đồng bộ…`);
    try {
      let res = await this.api.start_download(providerId, mode, options);
      if (res.requires_profile_close) {
        const accepted = window.confirm(
          `${res.error}\n\nBạn có đồng ý để MSB Radar Edge đóng đúng cửa sổ Chrome profile này và tiếp tục đồng bộ không?\n\n` +
          'Hãy lưu mọi thao tác đang làm trên trình duyệt trước khi chọn OK.');
        if (!accepted) {
          this.setDownloadingState(false);
          this.showAppToast('Đã hủy đồng bộ',
            'Chrome profile vẫn được giữ nguyên và không có tiến trình đồng bộ nào bắt đầu.', 'info');
          return;
        }
        options.confirm_close_profile = true;
        res = await this.api.start_download(providerId, mode, options);
      }
      if (!res.ok) {
        this.addLog(`[${new Date().toLocaleTimeString('vi-VN', { hour12: false })}] ! Không thể bắt đầu: ${res.error}`);
        alert("Không thể bắt đầu: " + res.error);
        this.setDownloadingState(false);
      } else {
        this.setDownloadingState(true, false);
        this.addLog(`[${new Date().toLocaleTimeString('vi-VN', { hour12: false })}] Tác vụ đã bắt đầu; nhật ký từ kênh tuyển dụng sẽ xuất hiện bên dưới.`);
      }
    } catch (e) {
      console.error("start_download err:", e);
      this.addLog(`[${new Date().toLocaleTimeString('vi-VN', { hour12: false })}] ! Lỗi khởi động tác vụ: ${e?.message || String(e)}`);
      alert("Không thể bắt đầu tải: " + (e && e.message || e));
      this.setDownloadingState(false);
    }
  }

  async stopDownload() {
    if (!this.api) return;
    try {
      const btn = document.getElementById('btn-stop-download');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="checkpoint-spinner" style="width:13px;height:13px;border-width:2px;display:inline-block;"></span> <span>Đang dừng…</span>';
      }
      const result = await this.api.stop_download();
      if (!result.ok) throw new Error(result.error || 'Không thể dừng tiến trình.');
      // Không addLog ở đây: backend đã tự log(message) và đẩy qua addLogBatch,
      // thêm ở đây sẽ in trùng đúng một câu hai lần trên màn hình.
    } catch (e) {
      console.error("stop_download err:", e);
      const btn = document.getElementById('btn-stop-download');
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<svg class="stop-icon-pulse" width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"></rect></svg> <span>Dừng tải</span>';
      }
      alert("Lỗi khi dừng tải: " + (e && e.message || e));
    }
  }

  setDownloadingState(isDownloading, isPreparing = false) {
    const btnNew = document.getElementById('btn-download-new');
    const btnAll = document.getElementById('btn-download-all');
    const btnRetry = document.getElementById('btn-retry-failed');
    const btnStop = document.getElementById('btn-stop-download');
    const statusPill = document.querySelector('.header-status-pill');
    const statusText = document.getElementById('tab-download-status-text');
    const browserButtons = document.querySelectorAll(
      '#btn-open-provider-browser, #btn-clear-provider-password, #config-browser-provider');

    if (isDownloading) {
      btnNew.disabled = btnAll.disabled = btnRetry.disabled = true;
      btnNew.classList.add('is-syncing');
      browserButtons.forEach(btn => { btn.disabled = true; });
      btnStop.classList.toggle('hidden', isPreparing);
      btnStop.disabled = isPreparing;
      if (statusPill) statusPill.classList.add('is-busy');
      if (statusText) statusText.textContent = isPreparing ? 'Đang chuẩn bị tác vụ…' : 'Đang đồng bộ dữ liệu…';
      const phase = document.getElementById('progress-phase');
      if (isPreparing && phase) phase.textContent = 'Đang chuẩn bị tác vụ…';
    } else {
      btnNew.disabled = btnAll.disabled = btnRetry.disabled = false;
      btnNew.classList.remove('is-syncing');
      browserButtons.forEach(btn => { btn.disabled = false; });
      btnStop.classList.add('hidden');
      btnStop.disabled = false;
      btnStop.innerHTML = '<svg class="stop-icon-pulse" width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"></rect></svg> <span>Dừng tải</span>';
      if (statusPill) statusPill.classList.remove('is-busy');
      if (statusText) statusText.textContent = 'Hệ thống sẵn sàng';
    }
  }

  // Số dòng log tối đa giữ trên màn hình. Tải hàng chục nghìn CV mà không giới hạn thì
  // DOM chất hàng chục nghìn thẻ <div> - chính là một trong các nguyên nhân khiến cửa
  // sổ ì và bị Windows báo "Not Responding". Lịch sử đầy đủ vẫn còn nguyên trong
  // nhatky.log và CSDL, chỉ màn hình hiển thị là giới hạn.
  static LOG_MAX_LINES = 500;

  _makeLogLine(text) {
    const line = document.createElement('div');
    line.className = 'log-line';
    if (text.includes('LỖI') || text.includes('✗')) line.classList.add('text-danger');
    else if (text.includes('✓') || text.includes('KẾT QUẢ')) line.classList.add('text-success');
    line.textContent = text;
    return line;
  }

  _trimLogConsole(consoleEl) {
    const max = App.LOG_MAX_LINES;
    while (consoleEl.children.length > max) {
      consoleEl.removeChild(consoleEl.firstChild);
    }
  }

  addLog(text) {
    const consoleEl = document.getElementById('log-console');
    if (!consoleEl) return;
    consoleEl.appendChild(this._makeLogLine(text));
    this._trimLogConsole(consoleEl);
    consoleEl.scrollTop = consoleEl.scrollHeight;
  }

  /** Nhận một CỤM nhiều dòng log cùng lúc từ Python (xem app/web_api.py _flush_ui).
   * Gom thành 1 lượt chỉnh DOM + 1 lượt cuộn thay vì lặp lại cho từng dòng - phần chậm
   * nhất khi log dồn dập không phải là tạo thẻ <div>, mà là buộc trình duyệt tính lại
   * bố cục/vẽ lại (reflow) sau MỖI thay đổi nhỏ. */
  addLogBatch(lines) {
    if (!lines || !lines.length) return;
    const consoleEl = document.getElementById('log-console');
    if (!consoleEl) return;
    const frag = document.createDocumentFragment();
    for (const text of lines) frag.appendChild(this._makeLogLine(text));
    consoleEl.appendChild(frag);
    this._trimLogConsole(consoleEl);
    consoleEl.scrollTop = consoleEl.scrollHeight;
  }

  /** Nạp lại các dòng nhật ký gần nhất từ nhatky.log lúc vừa mở app - để thấy được cả
   * những lượt chạy TRƯỚC lần mở phần mềm hiện tại (kể cả lượt hẹn giờ chạy lúc không
   * có ai mở giao diện lên xem), thay vì màn hình nhật ký trống trơn mỗi lần mở lại. */
  async loadRecentLogs() {
    if (!this.api) return;
    const lines = await this.api.get_recent_logs(300);
    if (!lines || lines.length === 0) return;
    const consoleEl = document.getElementById('log-console');
    if (!consoleEl) return;
    consoleEl.innerHTML = '';
    const header = document.createElement('div');
    header.className = 'log-line text-muted';
    header.textContent = `— Lịch sử ${lines.length.toLocaleString()} dòng gần nhất —`;
    consoleEl.appendChild(header);
    lines.forEach(line => this.addLog(line));
  }

  updateProgress(p) {
    document.getElementById('progress-phase').textContent = p.phase;
    const pct = p.total > 0 ? Math.min(100, Math.round((p.done / p.total) * 100)) : 0;
    document.getElementById('progress-percent').textContent = `${pct}%`;
    document.getElementById('progress-bar-fill').style.width = `${pct}%`;

    document.getElementById('prog-done').textContent = p.done.toLocaleString();
    document.getElementById('prog-total').textContent = p.total.toLocaleString();
    document.getElementById('prog-new').textContent = p.new.toLocaleString();
    document.getElementById('prog-skipped').textContent = p.skipped.toLocaleString();
    document.getElementById('prog-failed').textContent = p.failed.toLocaleString();

    if (p.eta_sec > 0) {
      const m = Math.floor(p.eta_sec / 60);
      const s = Math.floor(p.eta_sec % 60);
      document.getElementById('prog-eta').textContent = `${m}m ${s}s`;
    } else {
      document.getElementById('prog-eta').textContent = '--:--';
    }
  }

  onCandidateBatch(items) {
    if (!Array.isArray(items) || !items.length) return;
    this.liveNewTotal += items.filter(item => item.is_new).length;
    const sidebarCount = document.getElementById('sidebar-db-count');
    if (sidebarCount) {
      const base = this.downloadBaseStats ? Number(this.downloadBaseStats.total || 0) : this.sidebarBaseTotal;
      sidebarCount.textContent = `${(base + this.liveNewTotal).toLocaleString()} hồ sơ`;
    }
    this.liveCandidates.push(...items);
    if (this.liveCandidates.length > 500) this.liveCandidates.splice(0, this.liveCandidates.length - 500);
    if (this.currentTab !== 'tab-candidates') return;
    clearTimeout(this.liveCandidateTimer);
    this.liveCandidateTimer = setTimeout(() => this.applyLiveCandidates(), 700);
  }

  applyLiveCandidates() {
    const batch = this.liveCandidates.splice(0);
    if (!batch.length || this.currentTab !== 'tab-candidates') return;
    const search = (document.getElementById('filter-search')?.value || '').toLowerCase();
    const sources = this.selectedValues('filter-source');
    const accounts = this.selectedValues('filter-account');
    const status = document.getElementById('filter-status')?.value || '';
    const from = document.getElementById('filter-date-from')?.value || '';
    const to = document.getElementById('filter-date-to')?.value || '';
    const matches = item => {
      if (sources.length && !sources.includes(item.source)) return false;
      if (accounts.length && !accounts.includes(item.account)) return false;
      if (status === 'done' && item.dl_status !== 'Đã tải') return false;
      if (status === 'failed' && item.dl_status === 'Đã tải') return false;
      const date = String(item.applied_ts || '').slice(0, 10);
      if (from && date < from) return false;
      if (to && date > to) return false;
      if (search && !this.matchesBooleanSearch(item, search)) return false;
      return true;
    };
    const relevant = batch.filter(matches);
    if (!relevant.length) return;
    // Snapshot RAM phía frontend: cập nhật nhanh số liệu; refresh DB đầy đủ khi kết thúc.
    const newCount = relevant.filter(item => item.is_new).length;
    this.totalCandidates += newCount;
    const summary = document.getElementById('candidate-filter-summary');
    if (summary) summary.insertAdjacentHTML('beforeend',
      `<br>🔴 Gần real-time: vừa nhận ${relevant.length.toLocaleString()} cập nhật` +
      `${newCount ? ` · ${newCount.toLocaleString()} bản ghi mới` : ''}.`);
    // Chỉ trang đầu/sắp xếp mới nhất mới có thể chèn đúng thứ tự mà không đọc DB.
    if (this.page === 1 && this.sortBy === 'applied_ts' && this.sortDir === 'DESC') {
      this.loadCandidates();
    }
  }

  matchesBooleanSearch(item, search) {
    const normalize = value => String(value ?? '').toLowerCase().normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '');
    const haystack = normalize(Object.values(item).join(' '));
    const tokens = String(search || '').match(/"[^"]+"|\S+/g) || [];
    const groups = [[]];
    let negateNext = false;
    tokens.forEach(raw => {
      const upper = raw.toUpperCase();
      if (raw === upper && upper === 'OR') {
        if (groups[groups.length - 1].length) groups.push([]);
      } else if (raw === upper && upper === 'NOT') {
        negateNext = true;
      } else if (!(raw === upper && upper === 'AND')) {
        const term = normalize(raw.replace(/^"|"$/g, ''));
        if (term) groups[groups.length - 1].push({ term, negate: negateNext });
        negateNext = false;
      }
    });
    return groups.some(group => group.length && group.every(token =>
      token.negate ? !haystack.includes(token.term) : haystack.includes(token.term)));
  }

  onDownloadFinished(res) {
    this.setDownloadingState(false);
    this.updateStats();
    this.downloadMode = null;
    this.downloadBaseStats = null;
    this.liveCandidates = [];
    this.liveNewTotal = 0;
    if (this.currentTab === 'tab-candidates') {
      this.page = 1;
      this.loadCandidates();
    }
    if (this.currentTab === 'tab-report' && !this.reportFiltersDirty) this.loadReport();
    this.checkSystemHealth();
    this.loadCheckpoint();
  }

  async loadCandidates() {
    if (!this.api) return;
    const requestId = ++this.candidateRequestId;
    this.setCandidatesLoading(true);
    const filters = {
      limit: this.limit,
      offset: (this.page - 1) * this.limit,
      search: document.getElementById('filter-search')?.value || '',
      source: this.selectedValues('filter-source'),
      account: this.selectedValues('filter-account'),
      dl_status: document.getElementById('filter-status')?.value || '',
      date_from: document.getElementById('filter-date-from')?.value || '',
      date_to: document.getElementById('filter-date-to')?.value || '',
      sort_by: this.sortBy,
      sort_dir: this.sortDir,
    };

    let res;
    try {
      res = await this.api.get_candidates(filters);
    } catch (e) {
      if (requestId !== this.candidateRequestId) return;
      console.error("get_candidates err:", e);
      const tbody = document.getElementById('candidates-tbody');
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="9" class="text-center text-muted">Lỗi tải dữ liệu: ${this.escapeHtml(String(e && e.message || e))}</td></tr>`;
      }
      this.setCandidatesLoading(false);
      return;
    }
    if (requestId !== this.candidateRequestId) return;
    this.totalCandidates = res.total;
    if (res.stale) {
      this.showAppToast('Đang hiển thị dữ liệu gần nhất',
        res.message || 'Để tránh làm chậm đồng bộ, bảng sẽ cập nhật số liệu mới sau khi tải xong.',
        'info', 5000);
    }

    const activeCols = this.allColumns.filter(c => this.visibleColumns.includes(c.key));

    // Dynamic Header với tính năng click sắp xếp theo cột
    const tableHeader = document.querySelector('.data-table thead tr');
    if (tableHeader) {
      tableHeader.innerHTML = `<th class="row-select-cell"><input id="candidate-select-page" type="checkbox" aria-label="Chọn tất cả ứng viên trên trang này" title="Chọn trang hiện tại"></th>` + activeCols.map(c => {
        const extraClass = c.key === 'dl_status' ? ' col-dl_status' : '';
        if (c.key === 'stt') {
          return `<th class="text-center">STT</th>`;
        }
        const isSorted = this.sortBy === c.key;
        const icon = isSorted ? (this.sortDir === 'ASC' ? ' 🔼' : ' 🔽') : ' ↕️';
        const sortClass = isSorted ? `sortable sorted${extraClass}` : `sortable${extraClass}`;
        return `<th class="${sortClass}" data-key="${c.key}">${c.label}<span class="sort-icon">${icon}</span></th>`;
      }).join('');

      tableHeader.querySelector('#candidate-select-page')?.addEventListener('change', event => {
        res.items.forEach(candidate => {
          const key = this.candidateSelectionKey(candidate);
          if (event.target.checked) this.selectedCandidates.set(key, candidate);
          else this.selectedCandidates.delete(key);
        });
        tbody?.querySelectorAll('.candidate-row-check').forEach(input => {
          input.checked = event.target.checked;
          input.closest('tr')?.classList.toggle('is-selected', event.target.checked);
        });
        this.updateCandidateSelectionUI(res.items);
      });

      tableHeader.querySelectorAll('th.sortable').forEach(th => {
        th.addEventListener('click', () => {
          const key = th.dataset.key;
          if (this.sortBy === key) {
            this.sortDir = this.sortDir === 'ASC' ? 'DESC' : 'ASC';
          } else {
            this.sortBy = key;
            this.sortDir = 'ASC';
          }
          this.loadCandidates();
        });
      });
    }

    const tbody = document.getElementById('candidates-tbody');
    tbody.innerHTML = '';

    if (res.items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="${activeCols.length + 1}" class="text-center text-muted">Không tìm thấy ứng viên nào phù hợp</td></tr>`;
    } else {
      res.items.forEach((c, idx) => {
        const tr = document.createElement('tr');
        const selectionKey = this.candidateSelectionKey(c);
        const isSelected = this.selectedCandidates.has(selectionKey);
        tr.classList.toggle('is-selected', isSelected);
        const isDone = c.dl_status === 'Đã tải';
        const badgeClass = isDone ? 'badge-success' : 'badge-danger';

        const rowCells = activeCols.map(col => {
          if (col.key === 'stt') {
            return `<td class="text-center" style="font-weight:700; color:var(--tf-orange);">#${(this.page - 1) * this.limit + idx + 1}</td>`;
          }
          const val = c[col.key] ?? '';
          const escapedVal = this.escapeHtml(val);
          if (col.key === 'fullname') return `<td title="${escapedVal}"><a href="#" class="btn-open-detail text-gradient" style="text-decoration:none; font-weight:700;">${escapedVal} 🔍</a></td>`;
          if (col.key === 'dl_status') return `<td class="col-dl_status" title="${escapedVal}"><span class="badge ${badgeClass}">${escapedVal}</span></td>`;
          if (col.key === 'source') return `<td title="${escapedVal}">${escapedVal.toUpperCase()}</td>`;
          if (col.key === 'filename') {
            return `<td>${c.filename ? `<button class="btn btn-sm btn-brand btn-open-cv" data-file="${escapedVal}">📄 Mở CV</button>` : '-'}</td>`;
          }
          if (col.key === 'is_viewed') return `<td>${Number(val) ? 'Đã xem' : 'Chưa xem'}</td>`;
          if (col.key === 'alerts') {
            const shortText = this.escapeHtml(c.alerts_short || '');
            return `<td>${shortText ? `<button class="candidate-alert-btn" type="button">${shortText}</button>` : '-'}</td>`;
          }
          if (col.key === 'parse_status') {
            const labels = {done:'✓ Đã parsing',pending:'Chờ parsing',running:'Đang parsing',needs_ocr:'Cần OCR',empty:'Không có text',unsupported:'Chưa hỗ trợ',error:'Lỗi parsing',not_queued:'Chưa parsing'};
            const status = String(val || 'not_queued');
            return `<td><span class="parse-status parse-status-${this.escapeHtml(status)}">${this.escapeHtml(labels[status] || status)}</span></td>`;
          }
          if (col.key === 'parse_quality') {
            return `<td>${val === '' || val == null ? '—' : `${Math.round(Number(val) * 100)}%`}</td>`;
          }
          if (col.key === 'parse_text_length') {
            return `<td>${Number(val || 0).toLocaleString()}</td>`;
          }
          if (col.key === 'parse_needs_ocr') {
            return `<td>${Number(val) ? 'Có' : 'Không'}</td>`;
          }
          return `<td title="${escapedVal}">${escapedVal}</td>`;
        }).join('');

        tr.innerHTML = `<td class="row-select-cell"><input class="candidate-row-check" type="checkbox" ${isSelected ? 'checked' : ''} aria-label="Chọn ${this.escapeHtml(c.fullname || 'ứng viên')}"></td>` + rowCells;
        tr.querySelector('.candidate-row-check')?.addEventListener('change', event => {
          if (event.target.checked) this.selectedCandidates.set(selectionKey, c);
          else this.selectedCandidates.delete(selectionKey);
          tr.classList.toggle('is-selected', event.target.checked);
          this.updateCandidateSelectionUI(res.items);
        });
        tr.addEventListener('dblclick', event => {
          if (!event.target.closest('input, button, a')) this.openCandidateDetail(c);
        });
        tr.querySelector('.btn-open-detail')?.addEventListener('click', (e) => {
          e.preventDefault();
          this.openCandidateDetail(c);
        });
        tr.querySelector('.candidate-alert-btn')?.addEventListener('click', (e) => {
          e.stopPropagation();
          this.openCandidateAlert(c);
        });

        tbody.appendChild(tr);
      });

      tbody.querySelectorAll('.btn-open-cv').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const fn = e.target.dataset.file;
          this.openCvInModal(fn);
        });
      });
    }

    this.updateCandidateSelectionUI(res.items);

    this.setCandidatesLoading(false);
    const totalPages = Math.max(1, Math.ceil(res.total / (this.limit || 50)));
    const start = res.total > 0 ? (this.page - 1) * this.limit + 1 : 0;
    const end = Math.min(this.page * this.limit, res.total);

    document.getElementById('pagination-info').textContent = `Hiển thị ${start}-${end} / ${res.total.toLocaleString()} bản ghi`;
    this.updateCandidateFilterSummary(filters, res);
    document.getElementById('total-pages-display').textContent = totalPages.toLocaleString();

    const pageJumpInput = document.getElementById('page-jump-input');
    if (pageJumpInput) pageJumpInput.value = this.page;

    const btnFirst = document.getElementById('btn-first-page');
    const btnPrev = document.getElementById('btn-prev-page');
    const btnNext = document.getElementById('btn-next-page');
    const btnLast = document.getElementById('btn-last-page');

    if (btnFirst) btnFirst.disabled = (this.page <= 1);
    if (btnPrev) btnPrev.disabled = (this.page <= 1);
    if (btnNext) btnNext.disabled = (this.page >= totalPages);
    if (btnLast) btnLast.disabled = (this.page >= totalPages);

    this.updateTopScrollbarWidth();
  }

  async loadCandidateFilterOptions() {
    this.candidateFilterOptions = await this.api.get_candidate_filter_options();
    this.refreshCandidateAccountOptions();
    this.refreshReportAccountOptions();
    this.refreshParsingFilterOptions();
  }

  refreshParsingFilterOptions() {
    const accountSelect = document.getElementById('parsing-account');
    const positionSelect = document.getElementById('parsing-position');
    const sources = this.selectedValues('parsing-source');
    if (accountSelect) {
      const previous = this.selectedValues('parsing-account');
      let options = this.candidateFilterOptions.accounts || [];
      if (sources.length) {
        const totals = {};
        sources.forEach(source => (this.candidateFilterOptions.accounts_by_source?.[source] || [])
          .forEach(item => totals[item.value] = (totals[item.value] || 0) + Number(item.count || 0)));
        options = Object.entries(totals).map(([value, count]) => ({ value, count }));
      }
      accountSelect.innerHTML = options.map(item => `<option value="${this.escapeHtml(item.value)}">${this.escapeHtml(item.value)} (${Number(item.count).toLocaleString()})</option>`).join('');
      Array.from(accountSelect.options).forEach(option => option.selected = previous.includes(option.value));
      this.renderMultiCheckFilter('parsing-account');
    }
    if (positionSelect && !positionSelect.options.length) {
      positionSelect.innerHTML = (this.candidateFilterOptions.positions || []).map(value => `<option value="${this.escapeHtml(value)}">${this.escapeHtml(value)}</option>`).join('');
      this.renderMultiCheckFilter('parsing-position');
    }
    this.updateParsingFilterSummary();
  }

  parsingFilters() {
    return {
      source: this.selectedValues('parsing-source'),
      account: this.selectedValues('parsing-account'),
      position: this.selectedValues('parsing-position'),
      date_from: document.getElementById('parsing-date-from')?.value || '',
      date_to: document.getElementById('parsing-date-to')?.value || '',
    };
  }

  updateParsingFilterSummary() {
    const filters = this.parsingFilters();
    const labels = [];
    if (filters.source.length) labels.push(`${filters.source.length} nguồn`);
    if (filters.account.length) labels.push(`${filters.account.length} tài khoản`);
    if (filters.position.length) labels.push(`${filters.position.length} vị trí`);
    if (filters.date_from || filters.date_to) labels.push(`ngày ${filters.date_from || 'đầu kỳ'} → ${filters.date_to || 'hiện tại'}`);
    const el = document.getElementById('parsing-filter-summary');
    if (el) el.textContent = labels.length ? `Lượt parsing kế tiếp chỉ xử lý: ${labels.join(' · ')}.` : 'Chưa lọc: lượt parsing sẽ áp dụng cho tất cả CV phù hợp.';
  }

  candidateSelectionKey(candidate) {
    return `${candidate.source || ''}\u001f${String(candidate.account || '').toLowerCase()}\u001f${candidate.cv_id || ''}`;
  }

  updateCandidateSelectionUI(pageItems = []) {
    const count = this.selectedCandidates.size;
    const bar = document.getElementById('candidate-selection-bar');
    bar?.classList.toggle('hidden', count === 0);
    const countEl = document.getElementById('candidate-selected-count');
    if (countEl) countEl.textContent = `${count.toLocaleString()} ứng viên đã chọn`;
    const pageCheckbox = document.getElementById('candidate-select-page');
    if (pageCheckbox) {
      const selectedOnPage = pageItems.filter(item => this.selectedCandidates.has(this.candidateSelectionKey(item))).length;
      pageCheckbox.checked = pageItems.length > 0 && selectedOnPage === pageItems.length;
      pageCheckbox.indeterminate = selectedOnPage > 0 && selectedOnPage < pageItems.length;
    }
  }

  refreshCandidateAccountOptions() {
    const select = document.getElementById('filter-account');
    if (!select) return;
    const previous = this.selectedValues('filter-account');
    const sources = this.selectedValues('filter-source');
    let options = this.candidateFilterOptions.accounts || [];
    if (sources.length) {
      const totals = {};
      sources.forEach(source => (this.candidateFilterOptions.accounts_by_source?.[source] || [])
        .forEach(item => totals[item.value] = (totals[item.value] || 0) + Number(item.count || 0)));
      options = Object.entries(totals).map(([value, count]) => ({ value, count }));
    }
    select.innerHTML = options.map(item =>
      `<option value="${this.escapeHtml(item.value)}">${this.escapeHtml(item.value)} (${Number(item.count).toLocaleString()})</option>`
    ).join('');
    Array.from(select.options).forEach(option => option.selected = previous.includes(option.value));
    this.renderMultiCheckFilter('filter-account');
  }

  refreshReportAccountOptions() {
    const select = document.getElementById('report-account');
    if (!select) return;
    const previous = this.selectedValues('report-account');
    const sources = this.selectedValues('report-source');
    let options = this.candidateFilterOptions.accounts || [];
    if (sources.length) {
      const totals = {};
      sources.forEach(source => (this.candidateFilterOptions.accounts_by_source?.[source] || [])
        .forEach(item => totals[item.value] = (totals[item.value] || 0) + Number(item.count || 0)));
      options = Object.entries(totals).map(([value, count]) => ({ value, count }));
    }
    select.innerHTML = options.map(item =>
      `<option value="${this.escapeHtml(item.value)}">${this.escapeHtml(item.value)} (${Number(item.count).toLocaleString()})</option>`
    ).join('');
    Array.from(select.options).forEach(option => option.selected = previous.includes(option.value));
    this.renderMultiCheckFilter('report-account');
  }

  updateCandidateFilterSummary(filters, result) {
    const target = document.getElementById('candidate-filter-summary');
    if (!target) return;
    const labels = [];
    if (filters.search) labels.push(`từ khóa “${filters.search}”`);
    if (filters.source?.length) labels.push(`nguồn ${filters.source.map(x => x.toUpperCase()).join(', ')}`);
    if (filters.account?.length) labels.push(`tài khoản ${filters.account.join(', ')}`);
    if (filters.dl_status) labels.push(filters.dl_status === 'done' ? 'đã tải xong' : 'lỗi/chưa tải');
    if (filters.date_from || filters.date_to) labels.push(
      `ngày ${filters.date_from || 'đầu kỳ'} → ${filters.date_to || 'hiện tại'}`);
    const warningRows = (result.items || []).filter(item => item.alerts_short).length;
    const sourceStats = (result.by_source || []).map(item =>
      `${String(item.value || 'unknown').toUpperCase()}: ${Number(item.count).toLocaleString()}`);
    const yearStats = (result.by_year || []).map(item =>
      `${item.value}: ${Number(item.count).toLocaleString()}`);
    const notes = [];
    if (result.stale) notes.push('đang dùng snapshot gần nhất vì tiến trình đồng bộ đang ghi database');
    if (!result.total) notes.push('không có bản ghi phù hợp; hãy kiểm tra lại từ khóa hoặc nới điều kiện');
    else if (warningRows) notes.push(`${warningRows} bản ghi trên trang hiện tại có cảnh báo cần xem`);
    if (filters.search) notes.push('từ khóa được dò trên toàn bộ trường dữ liệu');
    target.innerHTML = `<strong>${Number(result.total || 0).toLocaleString()} kết quả</strong>` +
      ` · Phạm vi: ${labels.length ? this.escapeHtml(labels.join(' · ')) : 'toàn bộ dữ liệu'}` +
      (sourceStats.length ? `<br>📊 Theo kênh: ${this.escapeHtml(sourceStats.join(' · '))}` : '') +
      (yearStats.length ? `<br>📅 Theo năm ứng tuyển: ${this.escapeHtml(yearStats.join(' · '))}` : '') +
      (notes.length ? `<br>💡 Lưu ý: ${this.escapeHtml(notes.join('; '))}.` : '');
  }

  openCandidateAlert(candidate) {
    const modal = document.getElementById('candidate-detail-modal');
    document.getElementById('detail-candidate-fullname').textContent =
      `Cảnh báo · ${candidate.fullname || 'Ứng viên không tên'}`;
    document.getElementById('detail-candidate-body').innerHTML = this.renderCandidateAlertDetail(candidate);
    this.bindApplicationCvButtons(document.getElementById('detail-candidate-body'));
    document.getElementById('btn-detail-open-cv').style.display = 'none';
    modal.classList.remove('hidden');
  }

  renderCandidateAlertDetail(candidate) {
    const applications = Array.isArray(candidate.applications) ? candidate.applications : [];
    const lines = String(candidate.alerts || 'Không có cảnh báo chi tiết.').split('\n')
      .filter(line => line && !(applications.length && line.startsWith('Lịch sử:')));
    const decorate = line => {
      if (line.startsWith('Ứng viên')) return ['repeat', '🔁'];
      if (line.startsWith('Lịch sử')) return ['history', '🕘'];
      if (line.startsWith('Vị trí')) return ['history', '💼'];
      if (line.startsWith('Nguồn')) return ['history', '🌐'];
      if (line.includes('email') || line.includes('điện thoại') || line.includes('liên hệ')) return ['contact', '📇'];
      if (line.includes('CV')) return ['file', '📄'];
      return ['', 'ℹ️'];
    };
    const alerts = `<div class="candidate-alert-detail">${
      lines.map(line => {
        const [kind, icon] = decorate(line);
        const content = this.escapeHtml(line).replace(/ \| /g, '<br>');
        return `<div class="candidate-alert-line ${kind}"><div class="candidate-alert-line-icon">${icon}</div><div>${content}</div></div>`;
      }).join('')
    }</div>`;
    return alerts + this.renderApplicationHistory(applications);
  }

  renderApplicationHistory(applications) {
    if (!applications?.length) return '';
    return `<div class="application-history"><div class="application-history-title">📚 Hồ sơ CV theo từng lần ứng tuyển</div>${applications.map((application, index) => {
      const filename = String(application.filename || '');
      const source = String(application.source || '').toUpperCase();
      return `<div class="application-history-row">
        <span class="application-history-number">${index + 1}</span>
        <div class="application-history-main"><strong>${this.escapeHtml(application.applied_at || 'Không rõ ngày')} · ${this.escapeHtml(application.position || 'Chưa rõ vị trí')}</strong><span>${this.escapeHtml(source)}${application.account ? ` · ${this.escapeHtml(application.account)}` : ''}${filename ? ` · ${this.escapeHtml(filename)}` : ' · Chưa có file CV'}</span></div>
        <button type="button" class="btn btn-sm btn-secondary btn-history-cv" data-file="${encodeURIComponent(filename)}" ${filename ? '' : 'disabled'}>${filename ? '📄 Mở CV' : 'Chưa có CV'}</button>
      </div>`;
    }).join('')}</div>`;
  }

  bindApplicationCvButtons(container) {
    container?.querySelectorAll('.btn-history-cv:not(:disabled)').forEach(button => {
      button.addEventListener('click', () => this.openCvInModal(decodeURIComponent(button.dataset.file || '')));
    });
  }

  setCandidatesLoading(isLoading) {
    const table = document.getElementById('candidates-data-table');
    const tbody = document.getElementById('candidates-tbody');
    if (table) table.setAttribute('aria-busy', isLoading ? 'true' : 'false');
    if (isLoading && tbody) {
      const colCount = Math.max(1, this.visibleColumns.length + 1);
      tbody.innerHTML = `<tr class="candidate-loading-row"><td colspan="${colCount}">
        <span class="table-loading-spinner" aria-hidden="true"></span>
        <span><strong>Đang tải dữ liệu ứng viên…</strong><small>Vui lòng chờ trong giây lát</small></span>
      </td></tr>`;
    }
    ['btn-first-page', 'btn-prev-page', 'btn-next-page', 'btn-last-page',
     'btn-jump-page', 'page-jump-input', 'page-size-select', 'btn-apply-filter',
     'btn-reset-filter'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.disabled = isLoading;
    });
  }

  setupTopScrollbar() {
    const wrapper = document.getElementById('table-top-scrollbar-wrapper');
    const container = document.getElementById('candidates-table-container');
    const inner = document.getElementById('table-top-scrollbar-inner');
    const table = document.getElementById('candidates-data-table');

    if (!wrapper || !container || !inner || !table) return;

    let isSyncingTop = false;
    let isSyncingContainer = false;

    wrapper.addEventListener('scroll', () => {
      if (!isSyncingContainer) {
        isSyncingTop = true;
        container.scrollLeft = wrapper.scrollLeft;
      }
      isSyncingContainer = false;
    });

    container.addEventListener('scroll', () => {
      if (!isSyncingTop) {
        isSyncingContainer = true;
        wrapper.scrollLeft = container.scrollLeft;
      }
      isSyncingTop = false;
    });

    window.addEventListener('resize', () => this.updateTopScrollbarWidth());
  }

  updateTopScrollbarWidth() {
    const inner = document.getElementById('table-top-scrollbar-inner');
    const table = document.getElementById('candidates-data-table');
    if (inner && table) {
      setTimeout(() => {
        inner.style.width = `${table.scrollWidth}px`;
      }, 50);
    }
  }

  /* ================= BÁO CÁO & PHÂN TÍCH ĐIỀU HÀNH (EXECUTIVE ANALYTICS) ================= */
  setupReportHub() {
    // Quick Date Presets
    const presetContainer = document.getElementById('report-date-presets');
    if (presetContainer) {
      presetContainer.querySelectorAll('.preset-pill').forEach(btn => {
        btn.addEventListener('click', () => {
          presetContainer.querySelectorAll('.preset-pill').forEach(p => p.classList.remove('active'));
          btn.classList.add('active');

          const range = btn.dataset.range;
          const select = document.getElementById('report-time-range');
          if (select) {
            select.value = range;
            const customDates = document.getElementById('report-custom-dates');
            if (customDates) customDates.classList.toggle('hidden', range !== 'custom');
          }
          if (range !== 'custom') {
            this.loadReport();
          }
        });
      });
    }

    // Refresh Report Button
    document.getElementById('btn-refresh-report')?.addEventListener('click', () => {
      this.showAppToast('Đang làm mới', 'Đang cập nhật số liệu thống kê mới nhất...', 'info', 2000);
      this.loadReport();
    });

    // Export Report to Excel
    document.getElementById('btn-export-report-excel')?.addEventListener('click', () => {
      this.exportReportExcel();
    });

    // View Candidates from Report
    document.getElementById('btn-report-view-candidates')?.addEventListener('click', () => {
      this.viewCandidatesFromReport();
    });
  }

  async loadReport() {
    if (!this.api) return;
    if (this.reportRetryTimer) {
      clearTimeout(this.reportRetryTimer);
      this.reportRetryTimer = null;
    }
    const requestSeq = (this.reportRequestSeq || 0) + 1;
    this.reportRequestSeq = requestSeq;
    const source = this.selectedValues('report-source');
    const positionEl = document.getElementById('report-position');
    const position = this.selectedValues('report-position');
    const timeRange = document.getElementById('report-time-range')?.value || 'all';
    const dateFrom = document.getElementById('report-date-from')?.value || '';
    const dateTo = document.getElementById('report-date-to')?.value || '';
    const errorEl = document.getElementById('report-error');

    // Đồng bộ trạng thái active cho nút Preset dải ngày
    const presetPills = document.querySelectorAll('#report-date-presets .preset-pill');
    presetPills.forEach(p => p.classList.toggle('active', p.dataset.range === timeRange));

    if (timeRange === 'custom' && (!dateFrom || !dateTo)) {
      if (errorEl) {
        errorEl.textContent = 'Hãy chọn đầy đủ ngày bắt đầu và ngày kết thúc rồi bấm Áp dụng.';
        errorEl.classList.remove('hidden');
      }
      return;
    }
    if (timeRange === 'custom' && dateFrom > dateTo) {
      if (errorEl) {
        errorEl.textContent = 'Ngày bắt đầu không được lớn hơn ngày kết thúc.';
        errorEl.classList.remove('hidden');
      }
      return;
    }
    const account = this.selectedValues('report-account');
    
    this.setReportLoading(true);
    let res;
    try {
      res = await this.api.get_report({
        source, account, position, time_range: timeRange,
        date_from: dateFrom, date_to: dateTo,
      });
    } catch (e) {
      console.error("get_report err:", e);
      if (requestSeq !== this.reportRequestSeq) return;
      if (errorEl) {
        errorEl.textContent = `Không tải được báo cáo: ${String(e?.message || e)}`;
        errorEl.classList.remove('hidden');
      }
      this.setReportLoading(false);
      return;
    }
    if (requestSeq !== this.reportRequestSeq) return;
    if (res.busy) {
      this.setReportLoading(false);
      if (res.partial) {
        const total = Number(res.total || 0);
        const done = Number(res.done || 0);
        const failed = Number(res.failed || 0);
        const rate = Number(res.success_rate || 0);
        document.getElementById('kpi-total').textContent = total.toLocaleString();
        document.getElementById('kpi-done').textContent = done.toLocaleString();
        document.getElementById('kpi-failed').textContent = failed.toLocaleString();
        document.getElementById('kpi-rate').textContent = `${rate}%`;
        const fill = document.getElementById('kpi-success-fill');
        if (fill) fill.style.width = `${rate}%`;
      }
      if (!this.reportLoaded || res.partial) {
        const unknownIds = res.partial
          ? ['kpi-unique', 'kpi-duplicates', 'kpi-complete-contact', 'kpi-average', 'kpi-peak-count', 'kpi-change-badge']
          : ['kpi-total', 'kpi-done', 'kpi-failed', 'kpi-rate', 'kpi-unique',
             'kpi-duplicates', 'kpi-complete-contact', 'kpi-average', 'kpi-peak-count', 'kpi-change-badge'];
        unknownIds.forEach(id => {
          const el = document.getElementById(id);
          if (el) el.textContent = '—';
        });
      }
      if (errorEl) {
        errorEl.textContent = `${res.message} Hệ thống sẽ tự tải lại báo cáo khi dữ liệu sẵn sàng.`;
        errorEl.classList.remove('hidden');
      }
      this.reportRetryTimer = setTimeout(() => {
        if (this.currentTab === 'tab-report' && !this.reportFiltersDirty &&
            requestSeq === this.reportRequestSeq) this.loadReport();
      }, 5000);
      return;
    }
    errorEl?.classList.add('hidden');

    let invalidSelection = false;
    if (positionEl) {
      const selected = position;
      const values = Array.isArray(res.positions) ? res.positions : [];
      positionEl.innerHTML = values.map(value => `<option value="${this.escapeHtml(value)}">${this.escapeHtml(value)}</option>`).join('');
      Array.from(positionEl.options).forEach(option => option.selected = selected.includes(option.value));
      this.renderMultiCheckFilter('report-position');
      invalidSelection ||= selected.some(value => !values.includes(value));
    }
    if (invalidSelection) {
      this.setReportLoading(false);
      if (errorEl) {
        errorEl.textContent = 'Vị trí đã chọn không tồn tại trong nguồn hiện tại. Hãy chọn một giá trị gợi ý.';
        errorEl.classList.remove('hidden');
      }
      return;
    }
    if (Number(res.invalid_date_rows || 0) > 0 && errorEl) {
      errorEl.textContent = `Đã bỏ qua ${Number(res.invalid_date_rows).toLocaleString()} hồ sơ có ngày ứng tuyển không hợp lệ khi dựng biểu đồ xu hướng. Các KPI tổng vẫn giữ nguyên.`;
      errorEl.classList.remove('hidden');
    }

    // 1. Cập nhật 5 thẻ KPI chính
    const total = Number(res.total || 0);
    const done = Number(res.done || 0);
    const failed = Number(res.failed || 0);
    const rate = Number(res.success_rate || 0);
    const unique = Number(res.unique_candidates || 0);
    const duplicates = Number(res.duplicate_applications || 0);
    const completeContact = Number(res.complete_contact || 0);

    document.getElementById('kpi-total').textContent = total.toLocaleString();
    document.getElementById('kpi-done').textContent = done.toLocaleString();
    document.getElementById('kpi-failed').textContent = failed.toLocaleString();
    document.getElementById('kpi-rate').textContent = `${rate}%`;
    const successFill = document.getElementById('kpi-success-fill');
    if (successFill) successFill.style.width = `${rate}%`;

    document.getElementById('kpi-unique').textContent = unique.toLocaleString();
    document.getElementById('kpi-duplicates').textContent = duplicates.toLocaleString();
    const uniqueShare = total > 0 ? Math.round((unique / total) * 1000) / 10 : 0;
    const uniqueShareEl = document.getElementById('kpi-unique-share');
    if (uniqueShareEl) uniqueShareEl.textContent = `Độc nhất: ${uniqueShare}%`;

    document.getElementById('kpi-complete-contact').textContent = completeContact.toLocaleString();
    const contactRate = total > 0 ? Math.round((completeContact / total) * 1000) / 10 : 0;
    const contactTag = document.getElementById('kpi-contact-rate-tag');
    if (contactTag) contactTag.textContent = `Đạt ${contactRate}%`;

    const periodLabel = res.granularity === 'month' ? 'Tháng' : 'Ngày';
    const avgLabel = document.getElementById('kpi-average-label');
    if (avgLabel) avgLabel.textContent = `Bình Quân Mỗi ${periodLabel}`;
    document.getElementById('kpi-average').textContent = Number(res.average_per_period || 0).toLocaleString();

    const peak = res.peak || {};
    const peakCountEl = document.getElementById('kpi-peak-count');
    if (peakCountEl) peakCountEl.textContent = `${Number(peak.count || 0).toLocaleString()} hồ sơ`;
    const peakDateEl = document.getElementById('kpi-peak-date');
    if (peakDateEl) peakDateEl.textContent = `Kỳ cao điểm: ${peak.date ? this._fmtFullDate(peak.date) : '—'}`;

    // Tăng trưởng so với kỳ trước
    const changeBadge = document.getElementById('kpi-change-badge');
    const change = res.change_percent;
    if (changeBadge) {
      if (change === null || change === undefined) {
        changeBadge.textContent = '—';
        changeBadge.className = 'kpi-trend-pill neutral';
      } else {
        const sign = Number(change) > 0 ? '+' : '';
        changeBadge.textContent = `${sign}${change}%`;
        changeBadge.className = `kpi-trend-pill ${Number(change) > 0 ? 'positive' : (Number(change) < 0 ? 'negative' : 'neutral')}`;
      }
    }
    const prevEl = document.getElementById('kpi-previous');
    if (prevEl) {
      prevEl.textContent = res.previous_total === null || res.previous_total === undefined
        ? 'Toàn bộ thời gian'
        : `Kỳ trước: ${Number(res.previous_total).toLocaleString()} hồ sơ`;
    }

    // 2. Tự động sinh nhận định thông minh (Smart Executive Insights)
    this.renderSmartInsights(res);

    // 3. Biểu đồ vị trí, nguồn và chất lượng
    this.renderPositionChart(res.by_position);
    this.renderSourceChart(res.by_source);
    this.renderQualityReport(res.quality_rates);
    this.renderParsingReport(res.parsing);

    // 4. Biểu đồ xu hướng
    const trendTitle = document.getElementById('trend-chart-title');
    if (trendTitle) trendTitle.textContent = this._trendTitle(res.time_range, res.date_from, res.date_to);
    const granBadge = document.getElementById('trend-granularity-badge');
    if (granBadge) granBadge.textContent = res.granularity === 'month' ? 'Theo Tháng' : 'Theo Ngày';
    this.renderTrendChart(res.trend_series);

    const filterStatus = document.getElementById('report-filter-status');
    if (filterStatus) {
      filterStatus.textContent = 'Báo cáo đã cập nhật theo bộ lọc hiện tại';
      filterStatus.classList.remove('dirty');
      filterStatus.classList.add('applied');
    }
    this.reportLoaded = true;
    this.reportFiltersDirty = false;
    if (this.reportRetryTimer) {
      clearTimeout(this.reportRetryTimer);
      this.reportRetryTimer = null;
    }
    if (res.stale && errorEl) {
      errorEl.textContent = res.message || 'Đang hiển thị báo cáo gần nhất trong lúc đồng bộ.';
      errorEl.classList.remove('hidden');
    }
    this.setReportLoading(false);
  }

  renderSmartInsights(res) {
    const total = Number(res.total || 0);
    const topSourceEl = document.getElementById('insight-top-source');
    const topPosEl = document.getElementById('insight-top-position');
    const trendEl = document.getElementById('insight-trend-summary');
    const recEl = document.getElementById('insight-recommendation');

    if (!total) {
      if (topSourceEl) topSourceEl.textContent = 'Chưa có hồ sơ nào phù hợp với bộ lọc hiện tại.';
      if (topPosEl) topPosEl.textContent = 'Chưa có dữ liệu vị trí tuyển dụng.';
      if (trendEl) trendEl.textContent = 'Chưa có dữ liệu xu hướng.';
      if (recEl) recEl.textContent = 'Hãy chọn dải thời gian rộng hơn hoặc đồng bộ thêm ứng viên từ tab Tải CV.';
      return;
    }

    // Top Source Insight
    if (topSourceEl) {
      if (res.by_source && res.by_source.length > 0) {
        const bestSource = res.by_source[0];
        const sName = String(bestSource.source || '').toUpperCase();
        const sCount = Number(bestSource.count || 0).toLocaleString();
        const sShare = Number(bestSource.share || 0);
        const sRate = Number(bestSource.success_rate || 0);
        topSourceEl.innerHTML = `<strong>${sName}</strong> dẫn đầu với <strong>${sCount}</strong> hồ sơ (chiếm <strong>${sShare}%</strong> thị phần). Tỷ lệ tải CV thành công đạt <strong>${sRate}%</strong>.`;
      } else {
        topSourceEl.textContent = 'Dữ liệu nguồn chưa được phân loại rõ ràng.';
      }
    }

    // Top Position Insight
    if (topPosEl) {
      if (res.by_position && res.by_position.length > 0) {
        const bestPos = res.by_position[0];
        const pName = this.escapeHtml(bestPos.position || 'Không xác định');
        const pCount = Number(bestPos.count || 0).toLocaleString();
        const pShare = Number(bestPos.share || 0);
        topPosEl.innerHTML = `Vị trí <strong>"${pName}"</strong> thu hút nhiều nhất với <strong>${pCount}</strong> lượt nộp (<strong>${pShare}%</strong> tổng số).`;
      } else {
        topPosEl.textContent = 'Chưa có vị trí tuyển dụng nào nổi bật.';
      }
    }

    // Trend & Peak Insight
    if (trendEl) {
      const peak = res.peak || {};
      const peakDateStr = peak.date ? this._fmtFullDate(peak.date) : 'N/A';
      const peakCount = Number(peak.count || 0).toLocaleString();
      const change = res.change_percent;
      let changeText = '';
      if (change !== null && change !== undefined) {
        const sign = Number(change) > 0 ? '+' : '';
        const status = Number(change) > 0 ? 'tăng trưởng' : (Number(change) < 0 ? 'suy giảm' : 'ổn định');
        changeText = ` So với kỳ liền trước ${status} <strong>${sign}${change}%</strong>.`;
      }
      trendEl.innerHTML = `Mốc cao điểm ghi nhận vào ngày <strong>${peakDateStr}</strong> với <strong>${peakCount}</strong> hồ sơ.${changeText}`;
    }

    // Recommendations
    if (recEl) {
      const successRate = Number(res.success_rate || 0);
      const contactRate = total ? Math.round((Number(res.complete_contact || 0) / total) * 100) : 0;
      const failed = Number(res.failed || 0);

      if (failed > 0) {
        recEl.innerHTML = `Hiện có <strong>${failed.toLocaleString()}</strong> CV bị lỗi tải file. Khuyến nghị bấm nút <em>"Tải lại CV lỗi"</em> ở tab Tải CV để hoàn tất lưu trữ.`;
      } else if (contactRate >= 90) {
        recEl.innerHTML = `Chất lượng dữ liệu rất cao (<strong>${contactRate}%</strong> đủ liên hệ). Khuyến nghị trích xuất Excel hoặc tải ZIP để chuyển cho đội ngũ phỏng vấn.`;
      } else {
        recEl.innerHTML = `Khuyến nghị thiết lập lịch quét tự động theo chu kỳ (ví dụ 60 phút) để cập nhật hồ sơ ứng tuyển mới liên tục.`;
      }
    }
  }

  renderPositionChart(data) {
    const container = document.getElementById('chart-positions');
    if (!container) return;
    if (!data || data.length === 0) {
      container.innerHTML = `<div class="chart-empty text-muted">Chưa có dữ liệu vị trí ứng tuyển</div>`;
      return;
    }
    const maxVal = Math.max(...data.map(d => Number(d.count || 0)), 1);

    container.innerHTML = `
      <div class="position-rank-list">
        ${data.map((d, idx) => {
          const count = Number(d.count || 0);
          const pct = Math.max(4, Math.round((count / maxVal) * 100));
          const label = this.escapeHtml(d.position || 'Không xác định');
          const rankClass = idx === 0 ? 'rank-1' : (idx === 1 ? 'rank-2' : (idx === 2 ? 'rank-3' : 'rank-other'));
          const share = Number(d.share || 0);

          return `
            <div class="position-rank-item" data-position="${label}" title="Bấm để lọc danh sách ứng viên vị trí: ${label}">
              <div class="rank-badge ${rankClass}">#${idx + 1}</div>
              <div class="position-name" title="${label}">${label}</div>
              <div class="position-track"><div class="position-fill" style="width:${pct}%"></div></div>
              <div class="position-count">${count.toLocaleString()} <small style="color:var(--tf-slate); font-weight:400;">(${share}%)</small></div>
            </div>`;
        }).join('')}
      </div>
    `;

    // Click on position to filter in candidates tab
    container.querySelectorAll('.position-rank-item').forEach(item => {
      item.addEventListener('click', () => {
        const pos = item.dataset.position;
        if (pos) {
          this.switchTab('tab-candidates');
          const searchInput = document.getElementById('filter-search');
          if (searchInput) {
            searchInput.value = `"${pos}"`;
          }
          this.page = 1;
          this.loadCandidates();
          this.showAppToast('Lọc theo vị trí', `Đang xem ứng viên vị trí: "${pos}"`, 'info', 3500);
        }
      });
    });
  }

  renderSourceChart(data) {
    const container = document.getElementById('chart-sources');
    if (!container) return;
    if (!data?.length) {
      container.innerHTML = '<div class="chart-empty text-muted">Chưa có dữ liệu nguồn tuyển dụng</div>';
      return;
    }

    container.innerHTML = `
      <div class="source-matrix-list">
        ${data.map(item => {
          const sourceKey = String(item.source || '').toLowerCase();
          const sourceName = String(item.source || 'Khác').toUpperCase();
          const count = Number(item.count || 0);
          const share = Number(item.share || 0);
          const successRate = Number(item.success_rate || 0);
          const accounts = item.accounts || [];

          const accountRows = accounts.map(account => {
            const accShare = count ? Math.round(Number(account.count || 0) * 1000 / count) / 10 : 0;
            return `
              <div class="source-account-row">
                <span title="${this.escapeHtml(account.account)}">${this.escapeHtml(account.account || 'Tài khoản mặc định')}</span>
                <b>${Number(account.count || 0).toLocaleString()} <small style="color:var(--tf-slate); font-weight:normal;">(${accShare}%)</small></b>
              </div>`;
          }).join('');

          return `
            <div class="source-matrix-card">
              <div class="source-matrix-head">
                <div class="source-title-group">
                  <span class="source-pill-badge ${sourceKey}">${sourceName}</span>
                  <strong style="color:var(--tf-white);">${count.toLocaleString()} hồ sơ</strong>
                </div>
                <div class="source-stats-summary">
                  Tỷ trọng: <b>${share}%</b> · Tải thành công: <b style="color:${successRate >= 90 ? '#34d399' : '#fb7185'};">${successRate}%</b>
                </div>
              </div>
              <div class="source-accounts-container">
                ${accountRows || '<span class="text-muted" style="font-size:0.8rem">Không có tài khoản con</span>'}
              </div>
            </div>`;
        }).join('')}
      </div>
    `;
  }

  renderQualityReport(rates) {
    const container = document.getElementById('chart-quality');
    if (!container) return;
    const items = [
      { key: 'email', label: 'Có Email', value: Number(rates?.has_email || 0), note: 'Sẵn sàng gửi thư mời' },
      { key: 'phone', label: 'Có Số Điện Thoại', value: Number(rates?.has_phone || 0), note: 'Sẵn sàng liên hệ trực tiếp' },
      { key: 'file', label: 'Đã Lưu File CV', value: Number(rates?.has_file || 0), note: 'Lưu trữ cục bộ an toàn' },
      { key: 'detail', label: 'Chi Tiết Đầy Đủ', value: Number(rates?.has_detail || 0), note: 'Đã trích xuất thông tin chuyên sâu' },
    ];

    container.innerHTML = `
      <div class="quality-grid-wrapper">
        ${items.map(item => `
          <div class="quality-gauge-card">
            <div class="quality-gauge-head">
              <span>${item.label}</span>
              <strong style="color:${item.value >= 85 ? '#34d399' : (item.value >= 60 ? '#fbbf24' : '#fb7185')}">${item.value}%</strong>
            </div>
            <div class="quality-gauge-track">
              <div class="quality-gauge-fill ${item.key}" style="width:${item.value}%"></div>
            </div>
            <div class="quality-gauge-status">${item.note}</div>
          </div>
        `).join('')}
      </div>
    `;
  }

  renderParsingReport(data) {
    const set = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
    const parsing = data || {};
    set('report-parsing-done', Number(parsing.done || 0).toLocaleString());
    set('report-parsing-pending', Number(parsing.pending || 0).toLocaleString());
    set('report-parsing-not-queued', Number(parsing.not_queued || 0).toLocaleString());
    set('report-parsing-attention', Number(parsing.attention || 0).toLocaleString());
    set('report-parsing-coverage', `${Number(parsing.coverage || 0)}% đã parsing`);
    const renderRows = (id, rows, sourceMode=false) => {
      const target = document.getElementById(id);
      if (!target) return;
      if (!rows?.length) { target.innerHTML = '<div class="chart-empty text-muted">Chưa có dữ liệu</div>'; return; }
      target.innerHTML = rows.map(row => {
        const count = sourceMode ? Number(row.done || 0) : Number(row.count || 0);
        const total = sourceMode ? Number(row.total || 0) : Number(parsing.done || 0);
        const rate = total ? Math.round(count * 1000 / total) / 10 : 0;
        return `<div class="parsing-report-row"><div><strong>${this.escapeHtml(row.value || 'Không rõ')}</strong><span>${count.toLocaleString()} / ${total.toLocaleString()}</span></div><div class="parsing-report-track"><i style="width:${Math.min(100, rate)}%"></i></div><b>${rate}%</b></div>`;
      }).join('');
    };
    renderRows('report-parsing-methods', parsing.by_method, false);
    renderRows('report-parsing-sources', parsing.by_source, true);
  }

  renderTrendChart(data) {
    const container = document.getElementById('chart-trend');
    if (!container) return;
    if (!data || data.length === 0) {
      container.innerHTML = `<div class="chart-empty text-muted">Chưa có dữ liệu để hiển thị</div>`;
      return;
    }

    data = data.map(row => ({ ...row, count: Number(row.total || 0) }));
    const sourceNames = [...new Set(data.flatMap(row => Object.keys(row.sources || {})))];
    const palette = ['#00B4D8', '#10B981', '#F59E0B', '#A855F7', '#F43F5E'];
    const W = 680, H = 260, padL = 44, padR = 20, padT = 36, padB = 32;
    const plotW = W - padL - padR, plotH = H - padT - padB;
    const maxVal = Math.max(0, ...data.map(d => d.count));
    const niceMax = this._niceMax(maxVal);
    const stepX = data.length > 1 ? plotW / (data.length - 1) : 0;

    const points = data.map((d, i) => ({
      x: padL + i * stepX,
      y: padT + plotH - (niceMax ? (d.count / niceMax) * plotH : 0),
      date: d.date,
      count: d.count,
    }));

    const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
    const baseY = padT + plotH;
    const areaPath = `${linePath} L${points[points.length - 1].x.toFixed(1)},${baseY} L${points[0].x.toFixed(1)},${baseY} Z`;

    const gridVals = [0, niceMax / 2, niceMax];
    const gridSvg = gridVals.map(v => {
      const y = padT + plotH - (niceMax ? (v / niceMax) * plotH : 0);
      return `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}" class="chart-grid" stroke="rgba(255,255,255,0.08)"/>`
        + `<text x="${padL - 8}" y="${(y + 4).toFixed(1)}" text-anchor="end" class="chart-axis-text" fill="var(--tf-slate)" font-size="11">${Math.round(v).toLocaleString()}</text>`;
    }).join('');

    const labelEvery = Math.max(1, Math.ceil(points.length / 7));
    const xLabelsSvg = points.filter((_, i) => i % labelEvery === 0 || i === points.length - 1)
      .map(p => `<text x="${p.x.toFixed(1)}" y="${H - 8}" text-anchor="middle" class="chart-axis-text" fill="var(--tf-slate)" font-size="11">${this._fmtShortDate(p.date)}</text>`)
      .join('');

    const last = points[points.length - 1];
    const sourcePaths = sourceNames.map((source, sourceIndex) => {
      const path = data.map((row, index) => {
        const value = Number(row.sources?.[source] || 0);
        const y = padT + plotH - (niceMax ? value / niceMax * plotH : 0);
        return `${index ? 'L' : 'M'}${(padL + index * stepX).toFixed(1)},${y.toFixed(1)}`;
      }).join(' ');
      return `<path d="${path}" class="chart-source-line" fill="none" stroke-width="2" style="stroke:${palette[sourceIndex % palette.length]}"/>`;
    }).join('');

    const legend = `
      <div class="trend-legend">
        <span><i style="background:var(--tf-orange); width:14px; height:4px; border-radius:2px; display:inline-block;"></i> TỔNG HỒ SƠ</span>
        ${sourceNames.map((source, index) => `<span><i style="background:${palette[index % palette.length]}; width:14px; height:4px; border-radius:2px; display:inline-block;"></i> ${this.escapeHtml(source.toUpperCase())}</span>`).join('')}
      </div>
    `;

    container.innerHTML = `
      ${legend}
      <div style="position:relative; width:100%;">
        <svg viewBox="0 0 ${W} ${H}" class="chart-svg" id="trend-svg" style="width:100%; height:auto; overflow:visible;">
          <defs>
            <linearGradient id="trendAreaGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#ff8a33" stop-opacity="0.32"/>
              <stop offset="100%" stop-color="#ff8a33" stop-opacity="0.0"/>
            </linearGradient>
          </defs>
          ${gridSvg}
          <path d="${areaPath}" fill="url(#trendAreaGradient)"/>
          ${sourcePaths}
          <path d="${linePath}" fill="none" stroke="var(--tf-orange)" stroke-width="2.5" class="chart-line"/>
          <circle cx="${last.x.toFixed(1)}" cy="${last.y.toFixed(1)}" r="5" fill="#ff8a33" stroke="#fff" stroke-width="2"/>
          <text x="${(last.x - 8).toFixed(1)}" y="${(last.y - 10).toFixed(1)}" text-anchor="end" fill="var(--tf-orange)" font-weight="bold" font-size="12">${last.count}</text>
          ${xLabelsSvg}
          <line id="trend-crosshair" x1="0" y1="${padT}" x2="0" y2="${baseY}" stroke="rgba(255,255,255,0.4)" stroke-dasharray="3,3" class="chart-crosshair hidden"/>
          <rect x="${padL}" y="${padT}" width="${plotW}" height="${plotH}" fill="transparent" id="trend-hitlayer" style="cursor:crosshair;"/>
        </svg>
        <div class="chart-tooltip hidden" id="trend-tooltip"></div>
      </div>
    `;

    const svgEl = document.getElementById('trend-svg');
    const hitLayer = document.getElementById('trend-hitlayer');
    const crosshair = document.getElementById('trend-crosshair');
    const tooltip = document.getElementById('trend-tooltip');

    if (hitLayer && svgEl && crosshair && tooltip) {
      const showAt = (clientX) => {
        const rect = svgEl.getBoundingClientRect();
        const mx = (clientX - rect.left) * (W / rect.width);
        let idx = stepX ? Math.round((mx - padL) / stepX) : 0;
        idx = Math.max(0, Math.min(points.length - 1, idx));
        const p = points[idx];
        crosshair.setAttribute('x1', p.x);
        crosshair.setAttribute('x2', p.x);
        crosshair.classList.remove('hidden');
        tooltip.classList.remove('hidden');
        tooltip.style.left = `${(p.x / W) * 100}%`;
        tooltip.style.top = `${(p.y / H) * 100}%`;
        const sourceDetail = sourceNames.map(source => `${this.escapeHtml(source.toUpperCase())}: ${Number(data[idx].sources?.[source] || 0).toLocaleString()}`).join(' · ');
        tooltip.innerHTML = `<div class="tt-value">Tổng: ${p.count.toLocaleString()} hồ sơ</div>`
          + `<div class="tt-date">${this._fmtFullDate(p.date)}${sourceDetail ? `<br><small style="color:var(--tf-light)">${sourceDetail}</small>` : ''}</div>`;
      };

      hitLayer.addEventListener('mousemove', (e) => showAt(e.clientX));
      hitLayer.addEventListener('mouseleave', () => {
        crosshair.classList.add('hidden');
        tooltip.classList.add('hidden');
      });
    }
  }

  exportReportExcel() {
    const filters = {
      search: '',
      source: this.selectedValues('report-source'),
      account: this.selectedValues('report-account'),
      dl_status: '',
      date_from: document.getElementById('report-date-from')?.value || '',
      date_to: document.getElementById('report-date-to')?.value || '',
    };
    this.exportDataWithFilters(filters, 'xlsx');
  }

  viewCandidatesFromReport() {
    this.switchTab('tab-candidates');
    const reportSources = this.selectedValues('report-source');
    const reportAccounts = this.selectedValues('report-account');
    const dateFrom = document.getElementById('report-date-from')?.value || '';
    const dateTo = document.getElementById('report-date-to')?.value || '';

    // Đồng bộ sang bộ lọc của tab Ứng viên
    const sourceSelect = document.getElementById('filter-source');
    if (sourceSelect && reportSources.length > 0) {
      Array.from(sourceSelect.options).forEach(opt => opt.selected = reportSources.includes(opt.value));
      this.renderMultiCheckFilter('filter-source');
    }
    const accSelect = document.getElementById('filter-account');
    if (accSelect && reportAccounts.length > 0) {
      Array.from(accSelect.options).forEach(opt => opt.selected = reportAccounts.includes(opt.value));
      this.renderMultiCheckFilter('filter-account');
    }
    if (dateFrom) {
      const dFromEl = document.getElementById('filter-date-from');
      if (dFromEl) dFromEl.value = dateFrom;
    }
    if (dateTo) {
      const dToEl = document.getElementById('filter-date-to');
      if (dToEl) dToEl.value = dateTo;
    }

    this.page = 1;
    this.loadCandidates();
    this.showAppToast('Chuyển danh sách ứng viên', 'Đã áp dụng các điều kiện lọc từ Báo cáo sang Danh sách ứng viên.', 'info', 3000);
  }

  async exportDataWithFilters(filters, fmt) {
    if (!this.api) return;
    try {
      this.showAppToast('Đang xuất báo cáo', 'Hệ thống đang trích xuất dữ liệu...', 'info', 3000);
      const res = await this.api.export_data(fmt, filters);
      if (res && res.path) {
        this.showAppToast('Xuất báo cáo thành công', `Đã lưu file tại: ${res.path}`, 'success', 6000);
      }
    } catch (e) {
      console.error("exportDataWithFilters err:", e);
      this.showAppToast('Lỗi xuất báo cáo', String(e?.message || e), 'error', 6000);
    }
  }

  setReportLoading(isLoading) {
    document.getElementById('report-loading')?.classList.toggle('hidden', !isLoading);
    const status = document.getElementById('report-loading-text');
    if (this.reportLoadingTimer) {
      clearInterval(this.reportLoadingTimer);
      this.reportLoadingTimer = null;
    }
    if (isLoading) {
      const startedAt = Date.now();
      const update = () => {
        const seconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
        if (status) status.textContent = seconds < 5
          ? 'Đang tổng hợp báo cáo, vui lòng chờ…'
          : `Đang tổng hợp ${seconds} giây · dữ liệu lớn trên ổ đĩa đám mây có thể cần thêm thời gian`;
      };
      update();
      this.reportLoadingTimer = setInterval(update, 1000);
    } else if (status) {
      status.textContent = 'Đang tổng hợp báo cáo, vui lòng chờ…';
    }
    ['btn-apply-report', 'btn-reset-report', 'btn-refresh-report'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.disabled = isLoading;
    });
    const apply = document.getElementById('btn-apply-report');
    if (apply) apply.textContent = isLoading ? 'Đang xử lý…' : 'Áp dụng bộ lọc';
  }

  _trendTitle(range, from, to) {
    const labels = {
      today: 'Xu hướng ứng tuyển hôm nay', '7d': 'Xu hướng ứng tuyển 7 ngày gần nhất',
      '30d': 'Xu hướng ứng tuyển 30 ngày gần nhất', '90d': 'Xu hướng ứng tuyển 90 ngày gần nhất',
      this_month: 'Xu hướng ứng tuyển tháng này', this_year: 'Xu hướng ứng tuyển năm nay',
      all: 'Xu hướng ứng tuyển toàn bộ thời gian',
    };
    return range === 'custom' ? `Xu hướng ứng tuyển ${from || '?'} – ${to || '?'}`
      : (labels[range] || 'Xu hướng ứng tuyển');
  }

  _niceMax(v) {
    if (v <= 5) return 5;
    const exp = Math.floor(Math.log10(v));
    const base = Math.pow(10, exp);
    const n = v / base;
    let nice;
    if (n <= 1) nice = 1; else if (n <= 2) nice = 2; else if (n <= 5) nice = 5; else nice = 10;
    return nice * base;
  }

  _fmtShortDate(iso) {
    const [y, m, d] = (iso || '').split('-');
    return d ? `${d}/${m}` : `${m}/${y}`;
  }

  _fmtFullDate(iso) {
    const [y, m, d] = (iso || '').split('-');
    return d ? `${d}/${m}/${y}` : `${m}/${y}`;
  }

  async exportData(fmt) {
    if (!this.api) return;
    const filters = {
      search: document.getElementById('filter-search')?.value || '',
      source: this.selectedValues('filter-source'),
      account: this.selectedValues('filter-account'),
      dl_status: document.getElementById('filter-status')?.value || '',
      date_from: document.getElementById('filter-date-from')?.value || '',
      date_to: document.getElementById('filter-date-to')?.value || '',
      selected_candidates: Array.from(this.selectedCandidates.values()).map(candidate => ({
        source: candidate.source, account: candidate.account, cv_id: candidate.cv_id
      })),
    };
    try {
      const res = await this.api.export_data(fmt, filters);
      if (res.ok) {
        const scope = filters.selected_candidates.length ? ' đã chọn' : '';
        alert(`Đã xuất thành công ${res.count.toLocaleString()} ứng viên${scope}!\nFile: ${res.path}`);
      } else if (!res.cancelled) {
        alert("Lỗi khi xuất báo cáo: " + res.error);
      }
    } catch (e) {
      console.error("export_data err:", e);
      alert("Lỗi khi xuất báo cáo: " + (e && e.message || e));
    }
  }

  async loadConfig(loadDatabaseStatus = true) {
    if (!this.api) return;
    try {
      const cfg = await this.api.get_config();
      if (cfg.config_warning) this.showAppToast('Khôi phục cấu hình', cfg.config_warning, 'error', 10000);
      this.providerAccounts = cfg.provider_accounts || [];
      this.renderProviderAccounts();
      await this.loadProviders();
      this.scheduleJobs = cfg.schedule_jobs || [];
      this.renderScheduleJobs();
      document.getElementById('cfg-email').value = cfg.email || '';
      document.getElementById('cfg-password').value = '';
      document.getElementById('cfg-vietnamworks-email').value = cfg.vietnamworks_email || '';
      document.getElementById('cfg-vietnamworks-password').value = '';
      document.getElementById('cfg-careerviet-email').value = cfg.careerviet_email || '';
      document.getElementById('cfg-careerviet-password').value = '';
      document.getElementById('cfg-vieclam24h-email').value = cfg.vieclam24h_email || '';
      document.getElementById('cfg-vieclam24h-password').value = '';
      document.getElementById('cfg-itviec-email').value = cfg.itviec_email || '';
      document.getElementById('cfg-itviec-password').value = '';
      document.getElementById('cfg-joboko-email').value = cfg.joboko_email || '';
      document.getElementById('cfg-joboko-password').value = '';
      { const jh = document.getElementById('cfg-joboko-headless'); if (jh) jh.checked = cfg.joboko_headless !== false; }
      document.getElementById('cfg-jobsgo-email').value = cfg.jobsgo_email || '';
      document.getElementById('cfg-jobsgo-password').value = '';
      const passwordIds = {
        topcv: 'cfg-password', vietnamworks: 'cfg-vietnamworks-password',
        careerviet: 'cfg-careerviet-password', vieclam24h: 'cfg-vieclam24h-password',
        itviec: 'cfg-itviec-password', joboko: 'cfg-joboko-password', jobsgo: 'cfg-jobsgo-password'
      };
      Object.entries(passwordIds).forEach(([source, id]) => {
        const input = document.getElementById(id);
        if (input) input.placeholder = cfg.password_status?.[source]
          ? 'Đã lưu an toàn — để trống nếu không đổi' : 'Chưa lưu mật khẩu';
      });
      document.getElementById('cfg-cv-folder').value = cfg.cv_folder || '';
      document.getElementById('cfg-db-path').value = cfg.db_path || '';
      document.getElementById('cfg-concurrency').value = cfg.concurrency || 4;
      document.getElementById('cfg-delay-ms').value = cfg.delay_ms || 250;
      document.getElementById('cfg-pattern').value = cfg.filename_pattern || '{id}_{ten}';
      { const h = document.getElementById('cfg-headless'); if (h) h.checked = cfg.headless === true; }
      const setVal = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
      setVal('cfg-proxy-url', cfg.proxy_url || '');
      setVal('cfg-ssl-ca-bundle', cfg.ssl_ca_bundle || '');
      setVal('cfg-chromedriver-path', cfg.chromedriver_path || '');
      const sslVerify = document.getElementById('cfg-ssl-verify');
      if (sslVerify) sslVerify.checked = cfg.ssl_verify !== false;
      document.getElementById('cfg-schedule-interval').value = cfg.schedule_interval_min || 60;
      const scheduleSources = cfg.schedule_sources?.length ? cfg.schedule_sources : [cfg.schedule_source || 'topcv'];
      Array.from(document.getElementById('cfg-schedule-source').options).forEach(option => option.selected = scheduleSources.includes(option.value));
      this.renderMultiCheckFilter('cfg-schedule-source');
      document.getElementById('cfg-schedule-mode').value = cfg.schedule_mode || 'moi';
      document.getElementById('cfg-schedule-start').value = cfg.schedule_start_time || '';
      document.getElementById('cfg-autostart-schedule').checked = cfg.autostart_schedule || false;
      document.getElementById('cfg-parsing-ocr').checked = cfg.parsing_ocr_enabled !== false;

      // Nhận diện thương hiệu & Giao diện (Branding & Theme)
      this._currentThemeMode = cfg.theme_mode || 'dark';
      this._currentColorPreset = cfg.color_preset || 'amber_gold';
      this._currentCustomColor = cfg.custom_color || '#F59E0B';
      this._currentAppIcon = cfg.app_icon || '⚡';
      this._currentLogoUrl = cfg.app_logo_url || '';

      const appNameInput = document.getElementById('cfg-app-name');
      if (appNameInput) appNameInput.value = cfg.app_name || 'MSB Radar Edge';

      const appTaglineInput = document.getElementById('cfg-app-tagline');
      if (appTaglineInput) appTaglineInput.value = cfg.app_tagline || 'Trạm Thu Thập & Xử Lý CV Ngoại Biên';

      const themeRadio = document.querySelector(`input[name="cfg-theme-mode"][value="${this._currentThemeMode}"]`);
      if (themeRadio) {
        themeRadio.checked = true;
        document.querySelectorAll('.theme-mode-card').forEach(c => c.classList.remove('is-selected'));
        themeRadio.closest('.theme-mode-card')?.classList.add('is-selected');
      }

      document.querySelectorAll('.preset-icon-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.icon === this._currentAppIcon && !this._currentLogoUrl);
      });

      const previewIcon = document.getElementById('logo-preview-icon');
      const previewImg = document.getElementById('logo-preview-img');
      const btnRemoveLogo = document.getElementById('btn-remove-logo');
      if (this._currentLogoUrl) {
        if (previewIcon) previewIcon.classList.add('hidden');
        if (previewImg) { previewImg.src = this._currentLogoUrl; previewImg.classList.remove('hidden'); }
        if (btnRemoveLogo) btnRemoveLogo.classList.remove('hidden');
      } else {
        if (previewIcon) { previewIcon.textContent = this._currentAppIcon; previewIcon.classList.remove('hidden'); }
        if (previewImg) { previewImg.src = ''; previewImg.classList.add('hidden'); }
        if (btnRemoveLogo) btnRemoveLogo.classList.add('hidden');
      }

      document.querySelectorAll('.color-preset-swatch').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.preset === this._currentColorPreset);
      });
      const customIndicator = document.getElementById('custom-color-indicator');
      if (customIndicator) customIndicator.style.background = this._currentCustomColor;
      const customPicker = document.getElementById('cfg-custom-color-picker');
      if (customPicker) customPicker.value = this._currentCustomColor;

      const densitySelect = document.getElementById('cfg-table-density');
      if (densitySelect) densitySelect.value = cfg.table_density || 'normal';

      this.applyTheme(cfg);

      if (loadDatabaseStatus) this.refreshParsingStatus();
    } catch (e) {
      console.error("get_config err:", e);
      alert("Không tải được cấu hình hiện tại: " + (e && e.message || e));
      return;
    }
    await this.refreshScheduleStatus();
    if (loadDatabaseStatus) this.checkSystemHealth();
  }

  renderProviderAccounts() {
    const target = document.getElementById('provider-account-list');
    if (!target) return;
    const names = { topcv: 'TopCV', vietnamworks: 'VietnamWorks', careerviet: 'CareerViet', vieclam24h: 'Việc Làm 24h', itviec: 'ITViec', joboko: 'Joboko', jobsgo: 'JobsGO' };
    target.innerHTML = this.providerAccounts?.length ? this.providerAccounts.map(account => `
      <div class="smart-account-row ${account.enabled === false ? 'is-disabled' : ''}" data-id="${this.escapeHtml(account.id)}">
        <i class="smart-account-status"></i><div class="smart-account-main"><strong>${this.escapeHtml(account.label || account.email)}</strong><span>${names[account.source] || account.source} · ${this.escapeHtml(account.email)}</span></div>
        <div class="smart-account-meta">${account.has_password ? '🔐 Đã lưu mật khẩu' : '⚠ Chưa có mật khẩu'} · Profile riêng</div>
        <div class="smart-account-actions"><button class="btn btn-sm btn-secondary account-open-browser">🌐 Mở</button><button class="btn btn-sm btn-secondary account-edit">Sửa</button><button class="btn btn-sm btn-danger account-delete">Xóa</button></div>
      </div>`).join('') : '<div class="info-callout">Chưa có tài khoản. Thêm tài khoản đầu tiên để bắt đầu đồng bộ.</div>';
    target.querySelectorAll('.smart-account-row').forEach(row => {
      const account = this.providerAccounts.find(item => item.id === row.dataset.id);
      row.querySelector('.account-edit')?.addEventListener('click', () => this.openAccountEditor(account));
      row.querySelector('.account-open-browser')?.addEventListener('click', event => this.openProviderBrowser(account.source, event.target, account.id));
      row.querySelector('.account-delete')?.addEventListener('click', async () => {
        if (!confirm(`Xóa cấu hình ${account.label || account.email}? Dữ liệu ứng viên đã tải không bị xóa.`)) return;
        try {
          const result = await this.api.delete_provider_account(account.id);
          if (result?.ok) {
            this.showAppToast('Đã xóa tài khoản', `Đã xóa tài khoản ${account.label || account.email}.`, 'success');
            await this.loadConfig();
            const needsSetup = await this.api.needs_setup();
            this.applySetupLock(needsSetup);
          } else {
            this.showAppToast('Không thể xóa', result?.error || 'Lỗi khi xóa tài khoản.', 'error');
          }
        } catch (err) {
          this.showAppToast('Không thể xóa', err?.message || String(err), 'error');
        }
      });
    });
  }

  openAccountEditor(account = {}) {
    document.getElementById('account-editor-id').value = account.id || '';
    document.getElementById('account-editor-source').value = account.source || 'topcv';
    document.getElementById('account-editor-label').value = account.label || '';
    document.getElementById('account-editor-email').value = account.email || '';
    const passInput = document.getElementById('account-editor-password');
    if (passInput) {
      passInput.value = '';
      passInput.placeholder = account.has_password ? 'Đã lưu an toàn — để trống nếu không đổi' : 'Nhập mật khẩu';
      passInput.setAttribute('type', 'password');
      const toggleBtn = passInput.closest('.password-input-wrapper')?.querySelector('.password-toggle-btn');
      if (toggleBtn) {
        toggleBtn.textContent = '👁';
        toggleBtn.title = 'Hiện mật khẩu';
      }
    }
    document.getElementById('account-editor-enabled').checked = account.enabled !== false;
    const error = document.getElementById('account-editor-error');
    if (error) { error.textContent = ''; error.classList.add('hidden'); }
    document.getElementById('provider-account-editor').classList.remove('hidden');
    document.getElementById('account-editor-label').focus();
  }

  async saveProviderAccount() {
    const saveButton = document.getElementById('btn-save-provider-account');
    const error = document.getElementById('account-editor-error');
    const account = { id: document.getElementById('account-editor-id').value,
      source: document.getElementById('account-editor-source').value,
      label: document.getElementById('account-editor-label').value.trim(),
      email: document.getElementById('account-editor-email').value.trim(),
      password: document.getElementById('account-editor-password').value,
      enabled: document.getElementById('account-editor-enabled').checked };
    if (!account.email) {
      if (error) { error.textContent = 'Email đăng nhập là bắt buộc.'; error.classList.remove('hidden'); }
      document.getElementById('account-editor-email')?.focus();
      return;
    }
    if (!this.api?.save_provider_account) {
      const message = 'Backend chưa sẵn sàng. Hãy đóng và mở lại phần mềm rồi thử lại.';
      if (error) { error.textContent = message; error.classList.remove('hidden'); }
      return this.showAppToast('Không thể lưu tài khoản', message, 'error');
    }
    const oldLabel = saveButton?.textContent || 'Lưu tài khoản';
    if (saveButton) { saveButton.disabled = true; saveButton.textContent = 'Đang lưu…'; }
    if (error) { error.textContent = ''; error.classList.add('hidden'); }
    try {
      const result = await this.api.save_provider_account(account);
      if (!result?.ok) {
        const message = result?.error || 'Không nhận được xác nhận lưu từ hệ thống.';
        if (error) { error.textContent = message; error.classList.remove('hidden'); }
        return this.showAppToast('Không thể lưu tài khoản', message, 'error');
      }
      document.getElementById('provider-account-editor').classList.add('hidden');
      await this.loadConfig(false);
      const dangKhoa = this.setupLocked;
      const needsSetup = typeof result.needs_setup === 'boolean'
        ? result.needs_setup : await this.api.needs_setup();
      this.applySetupLock(needsSetup);
      if (dangKhoa && !needsSetup) {
        this.showAppToast('Thiết lập hoàn tất',
          'Tài khoản đã được lưu. Các tính năng của MSB Radar Edge đã được mở khóa.', 'success', 6000);
        this.switchTab('tab-download');
      } else {
        this.showAppToast('Đã lưu tài khoản', 'Tài khoản có Chrome profile riêng và đã được đưa vào hàng đợi.', 'success');
      }
    } catch (exception) {
      const message = String(exception?.message || exception || 'Lỗi không xác định khi lưu tài khoản.');
      if (error) { error.textContent = message; error.classList.remove('hidden'); }
      this.showAppToast('Không thể lưu tài khoản', message, 'error', 7000);
    } finally {
      if (saveButton) { saveButton.disabled = false; saveButton.textContent = oldLabel; }
    }
  }

  renderScheduleJobs() {
    const target = document.getElementById('schedule-job-list');
    if (!target) return;
    const names = {topcv:'TopCV',vietnamworks:'VietnamWorks',careerviet:'CareerViet',vieclam24h:'Việc Làm 24h',itviec:'ITViec',joboko:'Joboko',jobsgo:'JobsGO'};
    const cadence = minutes => minutes === 1440 ? 'hằng ngày' : minutes % 60 === 0 ? `mỗi ${minutes / 60} giờ` : `mỗi ${minutes} phút`;
    target.innerHTML = this.scheduleJobs?.length ? this.scheduleJobs.map(job => {
      const issue = (job.issues || []).join(' · ');
      const accountText = job.account_ids?.length ? `${job.account_count ?? job.account_ids.length} tài khoản đã chọn` : `${job.account_count ?? 0} tài khoản đang bật`;
      return `<article class="schedule-job-row ${job.enabled ? '' : 'is-disabled'}" data-id="${this.escapeHtml(job.id)}">
        <i class="schedule-job-state"></i><div class="schedule-job-main"><strong>${this.escapeHtml(job.name)}</strong><div class="schedule-job-scope">${(job.sources||[]).map(source=>`<i>${names[source]||source}</i>`).join('')}</div><span>${accountText} · ${job.mode==='tatca'?'Backup toàn bộ':'Chỉ CV mới'} · ${cadence(Number(job.interval_min||60))}</span></div>
        <div class="schedule-job-actions"><label class="mini-switch" title="Bật/tắt lịch"><input class="schedule-toggle" type="checkbox" ${job.enabled?'checked':''}><span></span></label><button class="btn btn-sm btn-secondary schedule-run" ${job.enabled?'':'disabled'}>Chạy ngay</button><button class="btn btn-sm btn-secondary schedule-edit">Sửa</button><button class="btn btn-sm btn-danger schedule-delete">Xóa</button></div>
        <div class="schedule-job-meta"><span class="${issue?'schedule-job-error':'schedule-job-next'}">${issue ? `⚠ ${this.escapeHtml(issue)}` : job.next_run_at ? `Kế tiếp: ${this._fmtFullDateTime(job.next_run_at)}` : job.enabled ? 'Sẵn sàng khi bật bộ hẹn giờ' : 'Lịch đang tắt'}</span><br>${job.last_run_at ? `Lần cuối: ${this._fmtFullDateTime(job.last_run_at)} · ${this.escapeHtml(job.last_status||'')}` : 'Chưa có lần chạy nào'}</div></article>`;
    }).join('') : '<div class="schedule-empty"><strong>Chưa có lịch tự động</strong><span>Tạo lịch đầu tiên để hệ thống chủ động kiểm tra CV theo phạm vi riêng.</span><button type="button" class="btn btn-brand schedule-empty-add">＋ Thêm lịch đầu tiên</button></div>';
    target.querySelector('.schedule-empty-add')?.addEventListener('click',()=>this.openScheduleEditor());
    target.querySelectorAll('.schedule-job-row').forEach(row => {
      const job = this.scheduleJobs.find(item => item.id === row.dataset.id);
      row.querySelector('.schedule-edit')?.addEventListener('click', () => this.openScheduleEditor(job));
      row.querySelector('.schedule-run')?.addEventListener('click', async event => {
        event.target.disabled = true;
        const result = await this.api.run_schedule_job_now(job.id);
        this.showAppToast(result.ok ? 'Đã đưa vào hàng đợi' : 'Không thể chạy lịch', result.ok ? `Lịch “${job.name}” sẽ chạy ngay khi tài nguyên sẵn sàng.` : result.error, result.ok ? 'success' : 'error');
        await this.refreshScheduleStatus();
      });
      row.querySelector('.schedule-toggle')?.addEventListener('change', async event => {
        const result = await this.api.save_schedule_job({...job, enabled:event.target.checked});
        if (!result.ok) this.showAppToast('Không thể thay đổi lịch', result.error, 'error');
        await this.refreshScheduleStatus();
      });
      row.querySelector('.schedule-delete')?.addEventListener('click', async () => {
        if (!confirm(`Xóa lịch “${job.name}”?`)) return;
        try {
          const result = await this.api.delete_schedule_job(job.id);
          if (result?.ok) {
            this.showAppToast('Đã xóa lịch', `Đã xóa lịch “${job.name}”.`, 'success');
            await this.loadConfig();
            await this.refreshScheduleStatus();
          } else {
            this.showAppToast('Không thể xóa', result?.error || 'Lỗi khi xóa lịch hẹn giờ.', 'error');
          }
        } catch (err) {
          this.showAppToast('Không thể xóa', err?.message || String(err), 'error');
        }
      });
    });
  }

  renderScheduleAccountOptions(selectedIds = null) {
    const target = document.getElementById('schedule-editor-accounts');
    const sources = Array.from(document.getElementById('schedule-editor-sources')?.selectedOptions || [])
      .map(option => option.value);
    const current = selectedIds || Array.from(target?.selectedOptions || []).map(option => option.value);
    if (!target) return;
    const names = {topcv:'TopCV',vietnamworks:'VietnamWorks',careerviet:'CareerViet',vieclam24h:'Việc Làm 24h',itviec:'ITViec',joboko:'Joboko',jobsgo:'JobsGO'};
    target.innerHTML = (this.providerAccounts || []).filter(account =>
      sources.includes(account.source) && account.enabled !== false).map(account =>
      `<option value="${this.escapeHtml(account.id)}">${this.escapeHtml(names[account.source] || account.source)} · ${this.escapeHtml(account.label || account.email)}</option>`).join('');
    Array.from(target.options).forEach(option => option.selected = current.includes(option.value));
    this.renderMultiCheckFilter('schedule-editor-accounts');
  }

  openScheduleEditor(job={}) {
    document.getElementById('schedule-editor-id').value = job.id || '';
    document.getElementById('schedule-editor-name').value = job.name || '';
    document.getElementById('schedule-editor-mode').value = job.mode || 'moi';
    document.getElementById('schedule-editor-interval').value = job.interval_min || 60;
    document.getElementById('schedule-editor-start').value = String(job.start_time || '').replace(' ', 'T').slice(0, 16);
    document.getElementById('schedule-editor-enabled').checked = job.enabled !== false;
    Array.from(document.getElementById('schedule-editor-sources').options).forEach(option =>
      option.selected = (job.sources || []).includes(option.value));
    this.renderMultiCheckFilter('schedule-editor-sources');
    this.renderScheduleAccountOptions(job.account_ids || []);
    document.getElementById('schedule-editor-title').textContent = job.id ? 'Chỉnh sửa lịch tự động' : 'Thêm lịch tự động';
    document.getElementById('schedule-job-editor').classList.remove('hidden');
    document.getElementById('schedule-editor-name').focus();
  }

  async saveScheduleJob() {
    const job = {
      id: document.getElementById('schedule-editor-id').value,
      name: document.getElementById('schedule-editor-name').value.trim(),
      sources: Array.from(document.getElementById('schedule-editor-sources').selectedOptions).map(o => o.value),
      account_ids: Array.from(document.getElementById('schedule-editor-accounts').selectedOptions).map(o => o.value),
      mode: document.getElementById('schedule-editor-mode').value,
      start_time: document.getElementById('schedule-editor-start').value.replace('T', ' '),
      interval_min: Number(document.getElementById('schedule-editor-interval').value || 60),
      enabled: document.getElementById('schedule-editor-enabled').checked
    };
    const result = await this.api.save_schedule_job(job);
    if (!result.ok) return this.showAppToast('Không thể lưu lịch', result.error, 'error');
    document.getElementById('schedule-job-editor').classList.add('hidden');
    await this.loadConfig();
    this.showAppToast('Đã lưu lịch', 'Lịch sẽ được xếp hàng tuần tự khi bộ hẹn giờ hoạt động.', 'success');
  }

  async openProviderBrowser(providerId, button, accountId = '') {
    if (!this.api) return;
    const names = {
      topcv: 'TopCV', vietnamworks: 'VietnamWorks', careerviet: 'CareerViet',
      vieclam24h: 'Việc Làm 24h', itviec: 'ITViec', joboko: 'Joboko', jobsgo: 'JobsGO'
    };
    const oldText = button?.textContent;
    if (button) {
      button.disabled = true;
      button.textContent = 'Đang mở…';
    }
    try {
      const result = await this.api.open_provider_browser(providerId, accountId);
      if (result.ok) {
        this.showAppToast(`Đã mở ${names[providerId] || providerId}`,
          'Bạn có thể thao tác thủ công. Hãy đóng cửa sổ Chrome này trước khi đồng bộ CV.',
          'success', 7000);
      } else {
        this.showAppToast('Không thể mở trình duyệt', result.error, 'error', 7000);
      }
    } catch (e) {
      this.showAppToast('Không thể mở trình duyệt', e && e.message || String(e), 'error', 7000);
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = oldText || '🌐 Mở trình duyệt';
      }
    }
  }

  async refreshParsingStatus(loadEvents=false) {
    if (this.parsingStatusTimer) clearTimeout(this.parsingStatusTimer);
    try {
      const status = await this.api.get_cv_parsing_status();
      const set = (id, value) => { const el=document.getElementById(id); if(el) el.textContent=value; };
      const done = Number(status.done || 0);
      const total = Number(status.total || 0);
      const processed = Number(status.processed || 0);
      set('parsing-done', done.toLocaleString());
      set('parsing-pending', Number(status.pending || 0).toLocaleString());
      set('parsing-errors', Number(status.error || 0) + Number(status.empty || 0) + Number(status.needs_ocr || 0) + Number(status.unsupported || 0) + Number(status.session_failed || 0));
      set('parsing-ocr', status.ocr_available ? 'Sẵn sàng' : 'Chưa cài');
      set('parsing-coverage', `Độ phủ ${total ? Math.round(done * 1000 / total) / 10 : 0}%`);
      set('parsing-current-file', status.running
        ? `${status.current_name || 'Ứng viên'} · ${status.current_filename || status.current_cv_id || ''}`
        : 'Chưa có tác vụ');
      set('parsing-progress-text', `${processed.toLocaleString()} CV trong lượt hiện tại · ${Number(status.session_done || 0).toLocaleString()} thành công · ${Number(status.session_failed || 0).toLocaleString()} cần kiểm tra`);
      const fill = document.getElementById('parsing-progress-fill');
      if (fill) fill.style.width = `${processed ? Math.min(100, processed * 100 / Math.max(1, processed + Number(status.pending || 0))) : 0}%`;
      const box = document.getElementById('parsing-summary');
      if (box) box.innerHTML = `<span>${status.running ? '↻' : '✓'}</span><div><strong>${status.running ? 'Đang bóc nội dung CV' : 'Hàng đợi sẵn sàng'}</strong><small>${Number(status.total||0).toLocaleString()} CV được quản lý · OCR ${status.ocr_available?'sẵn sàng':'chưa cài'} · Office cũ ${status.legacy_office_available?'sẵn sàng':'cần LibreOffice'}</small></div>`;
      if (loadEvents || this.currentTab === 'tab-parsing') await this.refreshParsingEvents();
      if (this.currentTab === 'tab-parsing' && !status.running && (!this._lastParsingResultsLoad || Date.now() - this._lastParsingResultsLoad > 4000)) {
        this._lastParsingResultsLoad = Date.now();
        this.loadParsingResults();
      }
      if (status.running || this.currentTab === 'tab-parsing') {
        this.parsingStatusTimer = setTimeout(() => this.refreshParsingStatus(true), 1200);
      }
    } catch (e) { console.error('parsing status', e); }
  }

  /** Máy chủ (web_api._push_parsing_status) gọi ngay khi một lượt parsing kết
   *  thúc — kể cả khi người dùng đang ở tab khác — để trạng thái/nút không kẹt. */
  onParsingStatus() {
    this.refreshParsingStatus(true);
  }

  async refreshParsingEvents() {
    const result = await this.api.get_cv_parsing_events(this.parsingEventSeq);
    if (!result?.ok || !Array.isArray(result.events) || !result.events.length) return;
    const consoleEl = document.getElementById('parsing-log-console');
    if (!consoleEl) return;
    if (!this.parsingEventSeq) consoleEl.innerHTML = '';
    const fragment = document.createDocumentFragment();
    result.events.forEach(event => {
      const line = document.createElement('div');
      line.className = `log-line ${event.level || 'info'}`;
      line.textContent = `[${event.time}] ${event.message}`;
      fragment.appendChild(line);
    });
    consoleEl.appendChild(fragment);
    while (consoleEl.children.length > 1000) consoleEl.firstElementChild?.remove();
    consoleEl.scrollTop = consoleEl.scrollHeight;
    this.parsingEventSeq = Number(result.last_seq || this.parsingEventSeq);
  }

  // ---------------- Đồng bộ lên Hub ----------------
  //
  // Quản lý trạng thái kết nối, điều khiển hàng đợi outbox và lịch tự động đẩy
  // dữ liệu hồ sơ và CV lên hệ thống trung tâm MSB Radar Hub.

  setupSyncHub() {
    const on = (id, handler) => {
      const node = document.getElementById(id);
      if (node) node.addEventListener('click', handler);
    };

    on('btn-hub-sync-now', () => this.hubSync(false));
    on('btn-hub-sync-full', () => this.hubSync(true));
    on('btn-hub-retry-failed', () => this.hubRetryFailed());
    on('btn-hub-save', () => this.hubSaveConfig());
    on('btn-hub-test', () => this.hubTest());
    on('btn-hub-register', () => this.hubRegister());

    // Nút sao chép mã máy (Edge ID)
    const copyBtn = document.getElementById('btn-copy-edge-id');
    if (copyBtn) {
      copyBtn.addEventListener('click', async () => {
        const edgeIdInput = document.getElementById('hub-edge-id');
        const edgeId = (edgeIdInput ? edgeIdInput.value : '').trim();
        if (edgeId) {
          try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
              await navigator.clipboard.writeText(edgeId);
            } else {
              edgeIdInput.select();
              document.execCommand('copy');
            }
            this.showAppToast('Đã sao chép mã máy', `Edge ID: ${edgeId}`, 'success');
          } catch (e) {
            edgeIdInput.select();
            document.execCommand('copy');
            this.showAppToast('Đã sao chép mã máy', `Edge ID: ${edgeId}`, 'success');
          }
        }
      });
    }

  }

  async hubRefresh() {
    if (!this.api) return;
    try {
      this.onSyncStatus(await this.api.get_sync_status());
    } catch (e) {
      console.error('get_sync_status err:', e);
    }
  }

  /** Máy chủ đẩy trạng thái sang đây sau mỗi lượt đồng bộ. */
  onSyncStatus(status) {
    if (!status) return;
    const set = (id, value) => {
      const node = document.getElementById(id);
      if (node) node.textContent = String(value);
    };
    const queue = status.queue || {};
    set('hub-q-pending', queue.pending || 0);
    set('hub-q-inflight', queue.inflight || 0);
    set('hub-q-synced', queue.synced || 0);
    set('hub-q-failed', queue.failed || 0);

    const url = document.getElementById('hub-url');
    if (url && document.activeElement !== url) url.value = status.hub_url || '';
    const edgeId = document.getElementById('hub-edge-id');
    if (edgeId) edgeId.value = status.edge_id || '';

    const banner = document.getElementById('hub-not-configured');
    if (banner) banner.classList.toggle('hidden', Boolean(status.configured));

    const staleNote = status.stale ? ' (số liệu tạm — đang tải/parsing)' : '';
    const autoStatus = document.getElementById('hub-auto-status');
    if (autoStatus) {
      if (!status.configured) autoStatus.textContent = 'Chưa cấu hình Hub.';
      else if (status.syncing) autoStatus.textContent = 'Đang gửi dữ liệu lên Hub…';
      else if (status.paused) autoStatus.textContent = 'Tạm dừng — nhường tài nguyên cho tải/parsing.';
      else autoStatus.textContent = 'Sẵn sàng — tự đồng bộ khi có CV mới đã parse.' + staleNote;
    }

    const autoDot = document.getElementById('hub-auto-pulse-dot');
    if (autoDot) {
      autoDot.className = !status.configured ? 'pulse-dot dot-danger'
        : status.syncing ? 'pulse-dot dot-primary' : 'pulse-dot dot-success';
    }

    // Cập nhật Header Status Pill
    const pillText = document.getElementById('hub-live-status-text');
    const pillDot = document.getElementById('hub-live-status-dot');
    if (pillText) {
      if (!status.configured) {
        pillText.textContent = 'Chưa kết nối Hub';
        if (pillDot) pillDot.className = 'pulse-dot dot-danger';
      } else if (status.syncing) {
        pillText.textContent = 'Đang truyền dữ liệu...';
        if (pillDot) pillDot.className = 'pulse-dot dot-primary';
      } else if (status.paused) {
        pillText.textContent = 'Tạm dừng nhường tài nguyên';
        if (pillDot) pillDot.className = 'pulse-dot dot-warning';
      } else {
        pillText.textContent = 'Tự động theo pipeline';
        if (pillDot) pillDot.className = 'pulse-dot dot-success';
      }
    }

    const last = status.last_run || {};
    const lastNode = document.getElementById('hub-last-run');
    if (lastNode) {
      if (!last.at) {
        lastNode.textContent = 'Chưa đồng bộ lần nào.';
      } else if (last.error) {
        lastNode.textContent = `Lượt gần nhất (${last.at}) gặp lỗi: ${last.error}`;
      } else {
        lastNode.textContent =
          `Lượt gần nhất ${last.at}: Đã gửi ${last.synced || 0} bản ghi, ` +
          `${last.uploaded || 0} file CV (${last.seconds || 0}s).`;
      }
    }
  }

  async hubSync(full) {
    const progressFill = document.getElementById('hub-progress-fill');
    if (progressFill) {
      progressFill.style.transition = 'width 0.5s ease';
      progressFill.style.width = '35%';
    }
    const result = await this.api.sync_now(Boolean(full));
    if (!result.ok) {
      if (progressFill) progressFill.style.width = '0%';
      this.showAppToast('Không đồng bộ được', result.error || '', 'error');
      return;
    }
    if (progressFill) progressFill.style.width = '75%';
    this.showAppToast('Đang đồng bộ',
      full ? 'Đang quét lại toàn bộ kho — việc này có thể mất vài phút.'
           : 'Đang gửi những thay đổi mới lên Hub.', 'info');
    // Chạy nền, nên hỏi lại trạng thái sau một lúc thay vì chờ.
    setTimeout(() => {
      if (progressFill) {
        progressFill.style.width = '100%';
        setTimeout(() => { progressFill.style.width = '0%'; }, 800);
      }
      this.hubRefresh();
    }, 2500);
  }

  async hubRetryFailed() {
    const result = await this.api.retry_failed_sync();
    if (!result.ok) {
      this.showAppToast('Không xếp lại được', result.error || '', 'error');
      return;
    }
    this.showAppToast('Đã xếp lại hàng đợi',
      `${result.requeued} bản ghi sẽ được gửi lại ở lượt tới.`, 'success');
    this.hubRefresh();
  }

  async hubSaveConfig() {
    const payload = { hub_url: (document.getElementById('hub-url') || {}).value || '' };
    const keyNode = document.getElementById('hub-api-key');
    // Ô trống nghĩa là "giữ khoá đang có", không phải "xoá khoá đi" — ô mật khẩu
    // luôn hiện trống vì không bao giờ đọc ngược khoá ra được.
    if (keyNode && keyNode.value) payload.hub_api_key = keyNode.value;

    const result = await this.api.save_hub_config(payload);
    if (!result.ok) {
      this.showAppToast('Không lưu được', result.error || '', 'error');
      return;
    }
    if (keyNode) keyNode.value = '';
    this.showAppToast('Đã lưu kết nối Hub', '', 'success');
    this.onSyncStatus(result.status);
  }

  async hubTest() {
    const node = document.getElementById('hub-test-result');
    if (node) {
      node.className = 'hub-test-badge testing';
      node.textContent = '⏳ Đang kiểm tra kết nối...';
    }
    const result = await this.api.test_hub_connection();
    if (node) {
      if (result.ok) {
        node.className = 'hub-test-badge success';
        node.textContent = `✓ ${result.detail || 'Hub phản hồi bình thường.'}`;
      } else {
        node.className = 'hub-test-badge error';
        node.textContent = `✕ Không kết nối được: ${result.error || 'Lỗi mạng hoặc API Key'}`;
      }
    }
  }

  async hubRegister() {
    const result = await this.api.register_edge_with_hub();
    this.showAppToast(result.ok ? 'Đã khai báo với Hub' : 'Không khai báo được',
      result.ok ? `Mã máy: ${result.edge_id}` : (result.error || ''),
      result.ok ? 'success' : 'error');
    this.hubRefresh();
  }

  setupThemeAndBranding() {
    // 1. Theme Mode selection
    document.querySelectorAll('.theme-mode-card').forEach(card => {
      card.addEventListener('click', () => {
        const mode = card.dataset.mode;
        const radio = card.querySelector('input[type="radio"]');
        if (radio) radio.checked = true;
        document.querySelectorAll('.theme-mode-card').forEach(c => c.classList.remove('is-selected'));
        card.classList.add('is-selected');
        this.applyTheme({
          theme_mode: mode,
          color_preset: this._currentColorPreset,
          custom_color: this._currentCustomColor,
          app_name: document.getElementById('cfg-app-name')?.value,
          app_tagline: document.getElementById('cfg-app-tagline')?.value,
          app_icon: this._currentAppIcon,
          app_logo_url: this._currentLogoUrl,
        });
      });
    });

    // 2. Preset icon buttons
    document.querySelectorAll('.preset-icon-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const icon = btn.dataset.icon;
        document.querySelectorAll('.preset-icon-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this._currentAppIcon = icon;
        this._currentLogoUrl = '';
        const previewIcon = document.getElementById('logo-preview-icon');
        const previewImg = document.getElementById('logo-preview-img');
        const btnRemove = document.getElementById('btn-remove-logo');
        if (previewIcon) { previewIcon.textContent = icon; previewIcon.classList.remove('hidden'); }
        if (previewImg) { previewImg.classList.add('hidden'); previewImg.src = ''; }
        if (btnRemove) { btnRemove.classList.add('hidden'); }
        this.applyTheme({
          theme_mode: this._currentThemeMode,
          color_preset: this._currentColorPreset,
          custom_color: this._currentCustomColor,
          app_name: document.getElementById('cfg-app-name')?.value,
          app_tagline: document.getElementById('cfg-app-tagline')?.value,
          app_icon: icon,
          app_logo_url: '',
        });
      });
    });

    // 3. Logo file upload
    const fileInput = document.getElementById('cfg-logo-file');
    const btnUpload = document.getElementById('btn-upload-logo');
    const btnRemove = document.getElementById('btn-remove-logo');
    btnUpload?.addEventListener('click', () => fileInput?.click());
    fileInput?.addEventListener('change', (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      if (file.size > 2 * 1024 * 1024) {
        this.showAppToast('Ảnh quá lớn', 'Vui lòng chọn tệp ảnh dung lượng dưới 2MB.', 'error');
        return;
      }
      const reader = new FileReader();
      reader.onload = (event) => {
        const dataUrl = event.target?.result;
        this._currentLogoUrl = dataUrl;
        const previewIcon = document.getElementById('logo-preview-icon');
        const previewImg = document.getElementById('logo-preview-img');
        if (previewIcon) previewIcon.classList.add('hidden');
        if (previewImg) { previewImg.src = dataUrl; previewImg.classList.remove('hidden'); }
        if (btnRemove) btnRemove.classList.remove('hidden');
        document.querySelectorAll('.preset-icon-btn').forEach(b => b.classList.remove('active'));
        this.applyTheme({
          theme_mode: this._currentThemeMode,
          color_preset: this._currentColorPreset,
          custom_color: this._currentCustomColor,
          app_name: document.getElementById('cfg-app-name')?.value,
          app_tagline: document.getElementById('cfg-app-tagline')?.value,
          app_icon: this._currentAppIcon,
          app_logo_url: dataUrl,
        });
      };
      reader.readAsDataURL(file);
    });

    btnRemove?.addEventListener('click', () => {
      this._currentLogoUrl = '';
      if (fileInput) fileInput.value = '';
      const previewIcon = document.getElementById('logo-preview-icon');
      const previewImg = document.getElementById('logo-preview-img');
      if (previewIcon) { previewIcon.textContent = this._currentAppIcon || '⚡'; previewIcon.classList.remove('hidden'); }
      if (previewImg) { previewImg.classList.add('hidden'); previewImg.src = ''; }
      btnRemove.classList.add('hidden');
      this.applyTheme({
        theme_mode: this._currentThemeMode,
        color_preset: this._currentColorPreset,
        custom_color: this._currentCustomColor,
        app_name: document.getElementById('cfg-app-name')?.value,
        app_tagline: document.getElementById('cfg-app-tagline')?.value,
        app_icon: this._currentAppIcon || '⚡',
        app_logo_url: '',
      });
    });

    // 4. Color presets
    document.querySelectorAll('.color-preset-swatch').forEach(btn => {
      btn.addEventListener('click', () => {
        const preset = btn.dataset.preset;
        document.querySelectorAll('.color-preset-swatch').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this._currentColorPreset = preset;
        if (preset === 'custom') {
          const picker = document.getElementById('cfg-custom-color-picker');
          if (picker) picker.click();
        } else {
          this.applyTheme({
            theme_mode: this._currentThemeMode,
            color_preset: preset,
            custom_color: this._currentCustomColor,
            app_name: document.getElementById('cfg-app-name')?.value,
            app_tagline: document.getElementById('cfg-app-tagline')?.value,
            app_icon: this._currentAppIcon,
            app_logo_url: this._currentLogoUrl,
          });
        }
      });
    });

    const customColorPicker = document.getElementById('cfg-custom-color-picker');
    customColorPicker?.addEventListener('input', (e) => {
      const hex = e.target.value;
      this._currentCustomColor = hex;
      this._currentColorPreset = 'custom';
      const indicator = document.getElementById('custom-color-indicator');
      if (indicator) indicator.style.background = hex;
      document.querySelectorAll('.color-preset-swatch').forEach(b => b.classList.remove('active'));
      document.querySelector('.color-preset-swatch[data-preset="custom"]')?.classList.add('active');
      this.applyTheme({
        theme_mode: this._currentThemeMode,
        color_preset: 'custom',
        custom_color: hex,
        app_name: document.getElementById('cfg-app-name')?.value,
        app_tagline: document.getElementById('cfg-app-tagline')?.value,
        app_icon: this._currentAppIcon,
        app_logo_url: this._currentLogoUrl,
      });
    });

    // 5. Live App Name update
    document.getElementById('cfg-app-name')?.addEventListener('input', (e) => {
      this.applyTheme({
        theme_mode: this._currentThemeMode,
        color_preset: this._currentColorPreset,
        custom_color: this._currentCustomColor,
        app_name: e.target.value,
        app_tagline: document.getElementById('cfg-app-tagline')?.value,
        app_icon: this._currentAppIcon,
        app_logo_url: this._currentLogoUrl,
      });
    });

    // System dark mode listener
    if (window.matchMedia) {
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
        if (this._currentThemeMode === 'auto') {
          this.applyTheme({
            theme_mode: 'auto',
            color_preset: this._currentColorPreset,
            custom_color: this._currentCustomColor,
            app_name: document.getElementById('cfg-app-name')?.value,
            app_tagline: document.getElementById('cfg-app-tagline')?.value,
            app_icon: this._currentAppIcon,
            app_logo_url: this._currentLogoUrl,
          });
        }
      });
    }
  }

  applyTheme(cfg = {}) {
    const themeMode = cfg.theme_mode || this._currentThemeMode || 'dark';
    this._currentThemeMode = themeMode;
    const isDark = themeMode === 'dark' || (themeMode === 'auto' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);

    if (isDark) {
      document.body.classList.remove('light-theme');
      document.body.classList.add('dark-theme');
      document.documentElement.classList.remove('light-theme');
      document.documentElement.classList.add('dark-theme');
      try {
        localStorage.setItem('msb_radar_theme', 'dark');
        localStorage.setItem('theme', 'dark');
      } catch (e) {}
    } else {
      document.body.classList.remove('dark-theme');
      document.body.classList.add('light-theme');
      document.documentElement.classList.remove('dark-theme');
      document.documentElement.classList.add('light-theme');
      try {
        localStorage.setItem('msb_radar_theme', 'light');
        localStorage.setItem('theme', 'light');
      } catch (e) {}
    }

    // Palette & Colors
    const presetKey = cfg.color_preset || this._currentColorPreset || 'amber_gold';
    this._currentColorPreset = presetKey;
    const customHex = cfg.custom_color || this._currentCustomColor || '#F59E0B';
    this._currentCustomColor = customHex;

    const palette = PRESET_PALETTES[presetKey] || PRESET_PALETTES.amber_gold;
    const primary = presetKey === 'custom' ? customHex : palette.primary;
    const primaryDark = presetKey === 'custom' ? this._adjustColorBrightness(customHex, -20) : palette.primaryDark;
    const primaryLight = presetKey === 'custom' ? this._adjustColorBrightness(customHex, 20) : palette.primaryLight;
    const orange = presetKey === 'custom' ? customHex : palette.orange;

    const root = document.documentElement;
    root.style.setProperty('--tf-orange', orange);
    root.style.setProperty('--tf-orange-light', primaryLight);
    root.style.setProperty('--tf-orange-dark', primaryDark);
    root.style.setProperty('--custom-accent-color', customHex);

    // Brand Name & Tagline & Icon
    const appName = cfg.app_name || 'MSB Radar Edge';
    const appIcon = cfg.app_icon || '⚡';
    const appLogoUrl = cfg.app_logo_url || '';

    // Update document title
    document.title = appName;

    // Update sidebar brand name
    const brandNameEl = document.getElementById('sidebar-brand-name');
    if (brandNameEl) {
      brandNameEl.innerHTML = `${this.escapeHtml(appName)} <span class="text-gradient"></span>`;
    }

    // Update sidebar brand icon / logo
    const brandIconEl = document.getElementById('sidebar-brand-icon');
    if (brandIconEl) {
      if (appLogoUrl) {
        brandIconEl.innerHTML = `<img src="${this.escapeHtml(appLogoUrl)}" alt="Logo" style="width: 38px; height: 38px; object-fit: contain; border-radius: 8px;">`;
      } else if (appIcon && appIcon !== '⚡') {
        brandIconEl.innerHTML = `<span style="font-size: 26px; line-height: 1;">${this.escapeHtml(appIcon)}</span>`;
      } else {
        brandIconEl.innerHTML = `
          <svg viewBox="0 0 280 160" width="46" height="28" style="filter: drop-shadow(0 2px 10px rgba(245, 158, 11, 0.4)); display: block;">
            <defs>
              <linearGradient id="logoGradSideDyn" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" style="stop-color: var(--tf-orange-light, #F59E0B)" />
                <stop offset="45%" style="stop-color: var(--tf-orange, #FF8A33)" />
                <stop offset="100%" style="stop-color: var(--tf-orange-dark, #E65C00)" />
              </linearGradient>
            </defs>
            <g transform="translate(15, 15)">
              <path d="M 50,130 C 15,130 15,65 50,65 C 85,65 95,130 130,130 C 165,130 175,65 210,65 C 245,65 245,130 210,130 C 175,130 165,65 130,65 C 95,65 85,130 50,130 Z" fill="none" stroke="url(#logoGradSideDyn)" stroke-width="22" stroke-linecap="round" stroke-linejoin="round" />
            </g>
          </svg>`;
      }
    }
  }

  _adjustColorBrightness(hex, percent) {
    let num = parseInt(hex.replace('#', ''), 16);
    if (isNaN(num)) return hex;
    let r = (num >> 16) + Math.round(255 * (percent / 100));
    let g = ((num >> 8) & 0x00FF) + Math.round(255 * (percent / 100));
    let b = (num & 0x0000FF) + Math.round(255 * (percent / 100));
    r = Math.min(255, Math.max(0, r));
    g = Math.min(255, Math.max(0, g));
    b = Math.min(255, Math.max(0, b));
    return `#${((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1)}`;
  }

  setupParsingHub() {
    const pillContainer = document.getElementById('parsing-status-pills');
    if (pillContainer) {
      pillContainer.querySelectorAll('.status-pill').forEach(btn => {
        btn.addEventListener('click', () => {
          pillContainer.querySelectorAll('.status-pill').forEach(p => p.classList.remove('active'));
          btn.classList.add('active');
          this.parsingStatusFilter = btn.dataset.status || '';
          this.parsingPage = 1;
          this.loadParsingResults();
        });
      });
    }

    const searchInput = document.getElementById('parsing-results-search');
    let searchTimer = null;
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        if (searchTimer) clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
          this.parsingSearchQuery = e.target.value.trim();
          this.parsingPage = 1;
          this.loadParsingResults();
        }, 300);
      });
      searchInput.addEventListener('keyup', (e) => {
        if (e.key === 'Enter') {
          if (searchTimer) clearTimeout(searchTimer);
          this.parsingSearchQuery = e.target.value.trim();
          this.parsingPage = 1;
          this.loadParsingResults();
        }
      });
    }

    document.getElementById('btn-refresh-parsing-results')?.addEventListener('click', () => {
      this.loadParsingResults();
    });

    document.getElementById('btn-prev-parsing-page')?.addEventListener('click', () => {
      if (this.parsingPage > 1) {
        this.parsingPage--;
        this.loadParsingResults();
      }
    });

    document.getElementById('btn-next-parsing-page')?.addEventListener('click', () => {
      this.parsingPage++;
      this.loadParsingResults();
    });
  }

  async loadParsingResults() {
    if (!this.api) return;
    const tbody = document.getElementById('parsing-results-tbody');
    if (!tbody) return;

    try {
      const filters = {
        limit: this.parsingPageSize || 15,
        offset: ((this.parsingPage || 1) - 1) * (this.parsingPageSize || 15),
        parse_status: this.parsingStatusFilter || '',
        search: this.parsingSearchQuery || '',
      };
      const res = await this.api.get_parsing_documents(filters);
      if (!res || !res.ok) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center" style="padding:24px;color:var(--tf-danger);">⚠️ ${this.escapeHtml(res?.error || 'Không thể tải danh sách kết quả bóc tách')}</td></tr>`;
        return;
      }

      const items = res.items || [];
      const total = res.total || 0;

      if (!items.length) {
        const msg = res.busy ? '⏳ Tiến trình bóc tách đang chạy độc quyền trên ổ đĩa đám mây. Danh sách chi tiết sẽ cập nhật ngay khi hoàn tất.' : 'Không tìm thấy hồ sơ nào phù hợp bộ lọc.';
        tbody.innerHTML = `<tr><td colspan="7" class="text-center" style="padding:32px;color:var(--tf-slate);">${msg}</td></tr>`;
        const infoEl = document.getElementById('parsing-pagination-info');
        if (infoEl) infoEl.textContent = `Hiển thị 0 / ${total.toLocaleString()} hồ sơ`;
        const prevBtn = document.getElementById('btn-prev-parsing-page');
        const nextBtn = document.getElementById('btn-next-parsing-page');
        if (prevBtn) prevBtn.disabled = true;
        if (nextBtn) nextBtn.disabled = true;
        return;
      }

      const labels = {
        done: '✓ Đã xong',
        pending: '⏳ Đang chờ',
        running: '↻ Đang bóc',
        needs_ocr: '⚡ Cần OCR',
        empty: '⚠️ Trống text',
        unsupported: '⚠️ Chưa hỗ trợ',
        error: '❌ Lỗi'
      };

      tbody.innerHTML = items.map(item => {
        const name = item.fullname || 'Ứng viên chưa rõ tên';
        const initials = name.split(' ').map(w => w[0]).filter(Boolean).slice(-2).join('').toUpperCase() || 'CV';
        const qualityPct = Math.round(Number(item.quality_score || 0) * 100);
        const statusClass = item.parse_status === 'done' ? 'badge-success' : (item.parse_status === 'needs_ocr' ? 'badge-warning' : (item.parse_status === 'pending' ? 'badge-info' : 'badge-danger'));
        const sourceName = String(item.source || '').toUpperCase();
        const appliedAt = item.applied_at || (item.applied_ts ? item.applied_ts.split(' ')[0] : '—');

        return `
          <tr data-source="${this.escapeHtml(item.source)}" data-account="${this.escapeHtml(item.account || '')}" data-cvid="${this.escapeHtml(item.cv_id)}">
            <td>
              <div class="parsing-candidate-cell">
                <div class="parsing-candidate-avatar">${initials}</div>
                <div class="parsing-candidate-meta">
                  <span class="parsing-candidate-name" title="${this.escapeHtml(name)}">${this.escapeHtml(name)}</span>
                  <span class="parsing-candidate-id">Mã: ${this.escapeHtml(item.cv_id)} · ${this.escapeHtml(item.filename || '')}</span>
                </div>
              </div>
            </td>
            <td>
              <div class="parsing-position-cell">
                <span class="parsing-position-title" title="${this.escapeHtml(item.position || 'Chưa rõ vị trí')}">${this.escapeHtml(item.position || 'Chưa rõ vị trí')}</span>
                <span class="provider-badge ${item.source || 'topcv'}" style="font-size:0.7rem;padding:2px 6px;">${this.escapeHtml(sourceName)}</span>
              </div>
            </td>
            <td>
              <span style="font-weight:600;color:var(--tf-white);" title="${this.escapeHtml(item.applied_ts || '')}">${this.escapeHtml(appliedAt)}</span>
            </td>
            <td>
              <span class="badge ${statusClass}">${this.escapeHtml(labels[item.parse_status] || item.parse_status)}</span>
            </td>
            <td>
              <span style="font-family:var(--font-mono);font-size:0.78rem;color:#94a3b8;">${this.escapeHtml(item.extraction_method || '—')}</span>
            </td>
            <td>
              <div class="parsing-quality-pill" title="${Number(item.text_length || 0).toLocaleString()} ký tự">
                <div class="parsing-quality-bar">
                  <div class="parsing-quality-bar-fill" style="width:${qualityPct}%"></div>
                </div>
                <span>${qualityPct}%</span>
              </div>
            </td>
            <td>
              <div class="parsing-actions-cell">
                <button type="button" class="btn btn-sm btn-secondary btn-inspect-parsing" title="Xem chi tiết kết quả bóc tách">
                  🔍 Chi tiết
                </button>
                ${item.filename ? `
                <button type="button" class="btn btn-sm btn-ghost btn-open-parsing-cv" title="Mở file CV gốc">
                  📄
                </button>
                ` : ''}
              </div>
            </td>
          </tr>
        `;
      }).join('');

      tbody.querySelectorAll('tr').forEach((row, idx) => {
        const item = items[idx];
        row.querySelector('.btn-inspect-parsing')?.addEventListener('click', () => {
          this.openCandidateDetail(item);
        });
        row.querySelector('.btn-open-parsing-cv')?.addEventListener('click', () => {
          if (item.filename) this.openCvInModal(item.filename);
        });
      });

      const startIdx = ((this.parsingPage - 1) * this.parsingPageSize) + 1;
      const endIdx = Math.min(this.parsingPage * this.parsingPageSize, total);
      const infoEl = document.getElementById('parsing-pagination-info');
      if (infoEl) infoEl.textContent = `Hiển thị ${startIdx} - ${endIdx} / ${total.toLocaleString()} hồ sơ`;
      const pageNumEl = document.getElementById('parsing-current-page-num');
      if (pageNumEl) pageNumEl.textContent = String(this.parsingPage);

      const prevBtn = document.getElementById('btn-prev-parsing-page');
      const nextBtn = document.getElementById('btn-next-parsing-page');
      if (prevBtn) prevBtn.disabled = this.parsingPage <= 1;
      if (nextBtn) nextBtn.disabled = endIdx >= total;

    } catch (e) {
      console.error('loadParsingResults err:', e);
    }
  }

  async loadRuntimeReadiness(forceShow=false) {
    const cacheKey = 'runtime_readiness_v2';
    const version = document.querySelector('.version-badge')?.textContent?.trim() || 'dev';
    const maxAgeMs = 30 * 24 * 60 * 60 * 1000;
    const modal = document.getElementById('runtime-readiness-modal');
    const list = document.getElementById('runtime-readiness-list');
    const note = document.getElementById('runtime-readiness-note');
    let cached = null;
    try { cached = JSON.parse(LS.get(cacheKey) || 'null'); } catch (_) { cached = null; }
    // Bản cũ chỉ lưu cờ sau khi một lượt kiểm tra đầy đủ đã thành công. Kế thừa
    // kết quả đó để người dùng hiện hữu không phải chịu thêm một lượt quét khi nâng cấp.
    if (!cached && LS.get('runtime_check_v1') === '1') {
      cached = {
        version,
        checked_at: Date.now(),
        migrated: true,
        result: { ok: true, checks: {}, support: 'Windows 10/11 64-bit' }
      };
      LS.set(cacheKey, JSON.stringify(cached));
    }
    const hadCache = !!cached;
    const checkedAt = Number(cached?.checked_at || 0);
    const cacheValid = !forceShow && cached?.result?.ok && cached.version === version &&
      checkedAt > 0 && Date.now() - checkedAt < maxAgeMs;

    let result;
    if (cacheValid) {
      result = cached.result;
    } else {
      if (forceShow && modal) modal.classList.remove('hidden');
      if (list) list.innerHTML = '<div class="runtime-check"><span class="health-pulse"></span><div><strong>Đang kiểm tra…</strong><small>Đang xác nhận Chrome, WebView2, OCR và bộ đọc tài liệu.</small></div></div>';
      result = await this.api.get_runtime_readiness();
      cached = { version, checked_at: Date.now(), result };
      LS.set(cacheKey, JSON.stringify(cached));
    }

    const rows = Object.values(result.checks || {});
    if (list) list.innerHTML = rows.length
      ? rows.map(row => `<div class="runtime-check ${row.ok?'is-ok':row.required?'is-error':'is-warning'}"><span>${row.ok?'✓':row.required?'×':'!'}</span><div><strong>${this.escapeHtml(row.label)}</strong><small>${row.ok?'Sẵn sàng':row.required?'Bắt buộc để dùng phần mềm':'Tùy chọn; một số định dạng CV sẽ bị giới hạn'}</small></div></div>`).join('')
      : '<div class="runtime-check is-ok"><span>✓</span><div><strong>Đã kế thừa lần kiểm tra thành công trước đó</strong><small>Bấm Kiểm tra lại nếu muốn chẩn đoán mới ngay bây giờ.</small></div></div>';
    const lastChecked = new Date(Number(cached?.checked_at || Date.now())).toLocaleString('vi-VN');
    if (note) note.innerHTML = result.ok
      ? `<strong>Máy đã sẵn sàng.</strong> Không cần kiểm tra lại mỗi lần mở. ${cached?.migrated ? 'Kết quả thành công từ bản trước đã được kế thừa' : 'Lần kiểm tra: ' + this.escapeHtml(lastChecked)}.`
      : `<strong>Chưa thể sử dụng đầy đủ.</strong> Hỗ trợ ${this.escapeHtml(result.support||'Windows 10/11 64-bit')}. Lần kiểm tra: ${this.escapeHtml(lastChecked)}.`;
    const menuButton = document.getElementById('btn-menu-runtime-check');
    if (menuButton) menuButton.title = `${result.ok ? 'Hệ thống sẵn sàng' : 'Hệ thống cần kiểm tra'} · ${lastChecked}`;
    if (modal && (forceShow || !hadCache || !result.ok)) modal.classList.remove('hidden');
    const continueButton = document.getElementById('btn-runtime-continue');
    if (continueButton) {
      continueButton.disabled = false;
      continueButton.onclick = () => modal?.classList.add('hidden');
    }
    const recheck = document.getElementById('btn-runtime-recheck');
    if (recheck) recheck.onclick = () => this.loadRuntimeReadiness(true);
    return result;
  }

  async checkSystemHealth() {
    const target = document.getElementById('system-health-summary');
    if (target) {
      target.classList.remove('is-warning', 'is-error');
      target.innerHTML = '<span class="health-pulse"></span><div><strong>Đang kiểm tra…</strong><small>Kiểm tra database, dung lượng, backup và Chrome profile.</small></div>';
    }
    const result = await this.api.get_system_health();
    if (result.busy) {
      if (target) target.innerHTML = '<span>↻</span><div><strong>Đang đồng bộ dữ liệu</strong><small>Tạm hoãn kiểm tra sâu để không tranh database; sẽ kiểm tra lại sau lượt tải.</small></div>';
      return;
    }
    if (!result.ok) {
      if (target) {
        target.classList.add('is-error');
        target.innerHTML = `<span>✕</span><div><strong>Dữ liệu cần xử lý</strong><small>${this.escapeHtml(result.error || result.quick_check)}</small></div>`;
      }
      return;
    }
    const openProfiles = Object.entries(result.profiles_open || {}).filter(([, open]) => open).map(([name]) => name);
    const freeGb = result.free_bytes / 1073741824;
    const warnings = [];
    if (!result.last_backup) warnings.push('Chưa có bản sao lưu database');
    else if (Number(result.backup_age_hours || 0) > 168) warnings.push('Bản sao lưu đã cũ hơn 7 ngày');
    if (freeGb < 5) warnings.push(`ổ đĩa chỉ còn ${freeGb.toFixed(1)} GB`);
    if (Number(result.failed || 0) > 0) warnings.push(`${Number(result.failed).toLocaleString()} CV cần tải lại`);
    if (openProfiles.length) warnings.push(`${openProfiles.length} Chrome profile đang mở; cần đóng trước khi đồng bộ`);
    const sizeMb = Number(result.database_bytes || 0) / 1048576;
    const setText = (id, value) => { const el=document.getElementById(id); if(el) el.textContent=value; };
    setText('health-records', Number(result.rows || 0).toLocaleString());
    setText('health-db-size', sizeMb >= 1024 ? `${(sizeMb/1024).toFixed(1)} GB` : `${sizeMb.toFixed(1)} MB`);
    setText('health-failed', Number(result.failed || 0).toLocaleString());
    setText('health-backup-age', result.backup_age_hours === null ? 'Chưa có' : Number(result.backup_age_hours) < 1 ? 'Vừa xong' : `${Math.round(result.backup_age_hours)} giờ trước`);
    const actions = document.getElementById('health-actions');
    if (actions) {
      actions.classList.toggle('hidden', !warnings.length);
      actions.innerHTML = warnings.length ? `<strong>Việc nên làm:</strong><ul>${warnings.map(item=>`<li>${this.escapeHtml(item)}</li>`).join('')}</ul>` : '';
    }
    if (target) {
      if (warnings.length) target.classList.add('is-warning');
      target.innerHTML = `<span>${warnings.length ? '!' : '✓'}</span><div><strong>${warnings.length ? `${warnings.length} việc cần lưu ý` : 'Dữ liệu hoạt động tốt'}</strong><small>Database ${this.escapeHtml(result.quick_check)} · schema v${Number(result.schema_version || 0)} · còn ${freeGb.toFixed(1)} GB</small></div>`;
    }
  }

  async backupDatabase() {
    const result = await this.api.backup_database();
    this.showAppToast(result.ok ? 'Sao lưu thành công' : 'Sao lưu thất bại',
      result.ok ? result.path : result.error, result.ok ? 'success' : 'error', 8000);
    if (result.ok) this.checkSystemHealth();
  }

  async deleteCandidateData() {
    const filters = {
      source: document.getElementById('delete-data-source')?.value || '',
      account: document.getElementById('delete-data-account')?.value.trim() || '',
      date_from: document.getElementById('delete-data-from')?.value || '',
      date_to: document.getElementById('delete-data-to')?.value || ''
    };
    if (!Object.values(filters).some(Boolean)) {
      this.showAppToast('Thiếu phạm vi', 'Hãy chọn ít nhất nguồn, tài khoản hoặc khoảng ngày.', 'error');
      return;
    }
    const confirmation = window.prompt(
      'Thao tác sẽ xóa cả bản ghi và file CV, không thể hoàn tác. Nhập chính xác: XOA DU LIEU');
    if (confirmation !== 'XOA DU LIEU') return;
    const result = await this.api.delete_candidate_data(filters, confirmation);
    this.showAppToast(result.ok ? 'Đã xóa dữ liệu' : 'Không thể xóa',
      result.ok ? `${result.rows} bản ghi, ${result.files} file CV.` : result.error,
      result.ok ? 'success' : 'error', 8000);
    if (result.ok) {
      await this.updateStats();
      await this.loadCandidates();
      this.checkSystemHealth();
    }
  }

  async saveConfig() {
    if (!this.api) return;
    const saveBtn = document.getElementById('btn-save-config');
    const saveLabel = saveBtn?.querySelector('span');
    const oldLabel = saveLabel?.textContent || 'Lưu Cấu Hình';
    if (saveBtn) saveBtn.disabled = true;
    if (saveLabel) saveLabel.textContent = 'Đang lưu…';
    const cfgDict = {
      email: document.getElementById('cfg-email').value,
      password: document.getElementById('cfg-password').value,
      vietnamworks_email: document.getElementById('cfg-vietnamworks-email').value,
      vietnamworks_password: document.getElementById('cfg-vietnamworks-password').value,
      careerviet_email: document.getElementById('cfg-careerviet-email').value,
      careerviet_password: document.getElementById('cfg-careerviet-password').value,
      vieclam24h_email: document.getElementById('cfg-vieclam24h-email').value,
      vieclam24h_password: document.getElementById('cfg-vieclam24h-password').value,
      itviec_email: document.getElementById('cfg-itviec-email').value,
      itviec_password: document.getElementById('cfg-itviec-password').value,
      joboko_email: document.getElementById('cfg-joboko-email').value,
      joboko_password: document.getElementById('cfg-joboko-password').value,
      joboko_headless: document.getElementById('cfg-joboko-headless')?.checked !== false,
      jobsgo_email: document.getElementById('cfg-jobsgo-email').value,
      jobsgo_password: document.getElementById('cfg-jobsgo-password').value,
      cv_folder: document.getElementById('cfg-cv-folder').value,
      db_path: document.getElementById('cfg-db-path').value,
      concurrency: parseInt(document.getElementById('cfg-concurrency').value) || 4,
      delay_ms: parseInt(document.getElementById('cfg-delay-ms').value) || 250,
      filename_pattern: document.getElementById('cfg-pattern').value,
      headless: document.getElementById('cfg-headless')?.checked === true,
      proxy_url: (document.getElementById('cfg-proxy-url')?.value || '').trim(),
      ssl_verify: document.getElementById('cfg-ssl-verify')?.checked !== false,
      ssl_ca_bundle: (document.getElementById('cfg-ssl-ca-bundle')?.value || '').trim(),
      chromedriver_path: (document.getElementById('cfg-chromedriver-path')?.value || '').trim(),
      schedule_enabled: document.getElementById('cfg-schedule-enabled').checked,
      schedule_interval_min: parseInt(document.getElementById('cfg-schedule-interval').value) || 60,
      schedule_source: this.selectedValues('cfg-schedule-source')[0] || 'topcv',
      schedule_sources: this.selectedValues('cfg-schedule-source'),
      schedule_mode: document.getElementById('cfg-schedule-mode').value,
      schedule_start_time: document.getElementById('cfg-schedule-start').value.trim(),
      autostart_schedule: document.getElementById('cfg-autostart-schedule').checked,
      parsing_enabled: true,
      parsing_ocr_enabled: document.getElementById('cfg-parsing-ocr').checked,
      app_name: document.getElementById('cfg-app-name')?.value || 'MSB Radar Edge',
      app_tagline: document.getElementById('cfg-app-tagline')?.value || 'Trạm Thu Thập & Xử Lý CV Ngoại Biên',
      app_icon: this._currentAppIcon || '⚡',
      app_logo_url: this._currentLogoUrl || '',
      theme_mode: document.querySelector('input[name="cfg-theme-mode"]:checked')?.value || this._currentThemeMode || 'dark',
      color_preset: this._currentColorPreset || 'amber_gold',
      custom_color: this._currentCustomColor || '#F59E0B',
      table_density: document.getElementById('cfg-table-density')?.value || 'normal',
    };

    try {
      const res = await this.api.save_config(cfgDict);
      if (res.ok) {
        this.applyTheme(cfgDict);
        await this.refreshScheduleStatus();
        const dangKhoa = this.setupLocked;
        const needsSetup = await this.api.needs_setup();
        this.applySetupLock(needsSetup);
        if (dangKhoa && !needsSetup) {
          // Vừa hoàn tất cài đặt lần đầu - mở khoá toàn bộ và chỉ đường đi tiếp.
          this.showAppToast('Thiết lập hoàn tất',
            'Cấu hình đã được lưu. Hãy Đồng bộ CV; nếu cần dữ liệu cũ, mở Nâng cao / Backup lịch sử.', 'success', 6000);
          this.switchTab('tab-download');
        } else {
          this.showAppToast('Đã lưu cấu hình',
            res.schedule_applied ? 'Mọi thay đổi đã được áp dụng; lịch tự động đang hoạt động.'
                                 : 'Mọi thay đổi đã được lưu; lịch tự động đang tắt.', 'success');
        }
      } else this.showAppToast('Không thể lưu cấu hình', res.error, 'error', 7000);
    } catch (e) {
      console.error("save_config err:", e);
      this.showAppToast('Không thể lưu cấu hình', e && e.message || String(e), 'error', 7000);
    } finally {
      if (saveBtn) saveBtn.disabled = false;
      if (saveLabel) saveLabel.textContent = oldLabel;
    }
  }

  _fallbackCopyText(text, successTitle = 'Đã sao chép') {
    try {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'absolute';
      textarea.style.left = '-9999px';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      this.showAppToast(successTitle, 'Nội dung đã được sao chép vào bộ nhớ tạm.', 'success');
    } catch (e) {
      this.showAppToast('Không thể sao chép', 'Hãy bôi đen và nhấn Ctrl+C để sao chép.', 'warning');
    }
  }

  showAppToast(title, message, type = 'success', duration = 4200) {
    let stack = document.getElementById('app-toast-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.id = 'app-toast-stack';
      stack.className = 'app-toast-stack';
      document.body.appendChild(stack);
    }
    const item = document.createElement('div');
    item.className = `app-toast ${type}`;
    const heading = document.createElement('strong');
    heading.textContent = `MSB Radar Edge · ${title}`;
    const body = document.createElement('span');
    body.textContent = message || '';
    item.append(heading, body);
    stack.appendChild(item);
    setTimeout(() => {
      item.classList.add('leaving');
      setTimeout(() => item.remove(), 220);
    }, duration);
  }

  async testWindowsNotifier() {
    if (!this.api) return;
    try {
      const res = await this.api.test_notification();
      if (res && res.ok) {
        this.showAppToast('Kiểm tra thông báo', 'Đã gửi thông báo thử nghiệm tới Windows.', 'success');
      } else {
        this.showAppToast('Thông báo Windows đang bị chặn', (res && res.error) || 'Chưa cấp quyền thông báo.', 'error', 7000);
      }
    } catch (e) {
      console.error("test_notification err:", e);
      this.showAppToast('Không thể gửi thông báo', e && e.message || String(e), 'error', 7000);
    }
  }

  setupHelpHub() {
    // 1. Category Filter Pills
    const pills = document.querySelectorAll('#help-filter-chips .help-pill');
    const sections = document.querySelectorAll('#tab-help [data-help-section]');
    const searchInput = document.getElementById('help-search-input');
    const clearBtn = document.getElementById('btn-help-clear-search');
    const resultsInfo = document.getElementById('help-search-results-info');
    const matchCountEl = document.getElementById('help-match-count');
    const resetFilterBtn = document.getElementById('btn-reset-help-filter');

    const applyFilter = () => {
      const activePill = document.querySelector('#help-filter-chips .help-pill.active');
      const category = activePill ? activePill.dataset.category : 'all';
      const rawQuery = String(searchInput?.value || '').trim();
      const query = rawQuery.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');

      clearBtn?.classList.toggle('hidden', !rawQuery);

      let totalMatches = 0;

      sections.forEach(section => {
        const sectionCat = section.dataset.helpSection;
        const matchesCategory = (category === 'all' || sectionCat === category || sectionCat === 'launcher');

        if (!matchesCategory) {
          section.classList.add('is-hidden');
          return;
        }

        if (!query) {
          section.classList.remove('is-hidden');
          // Reset internal cards visibility
          section.querySelectorAll('.roadmap-step-card, .feature-info-card, .boolean-card, .provider-guide-card, .troubleshoot-card, .faq-item').forEach(card => {
            card.style.display = '';
          });
          return;
        }

        // Section keywords or text
        const keywords = String(section.dataset.helpKeywords || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
        const sectionText = String(section.textContent || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');

        // Filter individual items inside this section
        const innerCards = section.querySelectorAll('.roadmap-step-card, .feature-info-card, .boolean-card, .provider-guide-card, .troubleshoot-card, .faq-item');
        let hasCardMatch = false;

        if (innerCards.length > 0) {
          innerCards.forEach(card => {
            const cardText = String(card.textContent || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
            const isMatch = cardText.includes(query);
            card.style.display = isMatch ? '' : 'none';
            if (isMatch) {
              hasCardMatch = true;
              totalMatches++;
              // If it's a FAQ item, expand it so the user sees the matched answer immediately
              if (card.classList.contains('faq-item')) {
                card.classList.add('active');
                card.querySelector('.faq-question')?.setAttribute('aria-expanded', 'true');
              }
            }
          });
          section.classList.toggle('is-hidden', !hasCardMatch && !keywords.includes(query));
        } else {
          const isSectionMatch = sectionText.includes(query) || keywords.includes(query);
          section.classList.toggle('is-hidden', !isSectionMatch);
          if (isSectionMatch) totalMatches++;
        }
      });

      if (resultsInfo && matchCountEl) {
        if (query) {
          resultsInfo.classList.remove('hidden');
          matchCountEl.textContent = String(totalMatches);
        } else {
          resultsInfo.classList.add('hidden');
        }
      }
    };

    pills.forEach(pill => {
      pill.addEventListener('click', () => {
        pills.forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        applyFilter();
      });
    });

    searchInput?.addEventListener('input', applyFilter);

    clearBtn?.addEventListener('click', () => {
      if (searchInput) searchInput.value = '';
      applyFilter();
      searchInput?.focus();
    });

    resetFilterBtn?.addEventListener('click', () => {
      if (searchInput) searchInput.value = '';
      pills.forEach(p => p.classList.remove('active'));
      document.querySelector('#help-filter-chips .help-pill[data-category="all"]')?.classList.add('active');
      applyFilter();
    });

    // 2. FAQ Accordion Toggle
    document.querySelectorAll('#faq-accordion-container .faq-question').forEach(btn => {
      btn.addEventListener('click', () => {
        const item = btn.closest('.faq-item');
        const isActive = item?.classList.contains('active');
        item?.classList.toggle('active', !isActive);
        btn.setAttribute('aria-expanded', String(!isActive));
      });
    });

    document.getElementById('btn-help-expand-all')?.addEventListener('click', () => {
      document.querySelectorAll('#faq-accordion-container .faq-item').forEach(item => {
        item.classList.add('active');
        item.querySelector('.faq-question')?.setAttribute('aria-expanded', 'true');
      });
    });

    document.getElementById('btn-help-collapse-all')?.addEventListener('click', () => {
      document.querySelectorAll('#faq-accordion-container .faq-item').forEach(item => {
        item.classList.remove('active');
        item.querySelector('.faq-question')?.setAttribute('aria-expanded', 'false');
      });
    });

    // 3. Boolean Search 1-Click Copy & Test Query
    document.querySelectorAll('.btn-copy-syntax').forEach(btn => {
      btn.addEventListener('click', async () => {
        const query = btn.dataset.query;
        if (!query) return;
        try {
          await navigator.clipboard.writeText(query);
          const originalText = btn.innerHTML;
          btn.innerHTML = '✓ Đã chép!';
          btn.style.background = 'var(--success)';
          btn.style.borderColor = 'var(--success)';
          this.showAppToast('Đã sao chép cú pháp', `Cú pháp tìm kiếm đã lưu vào bộ nhớ đệm: ${query}`, 'success', 2500);
          setTimeout(() => {
            btn.innerHTML = originalText;
            btn.style.background = '';
            btn.style.borderColor = '';
          }, 2000);
        } catch (e) {
          console.error('Clipboard copy error:', e);
          this.showAppToast('Lỗi sao chép', 'Không thể truy cập bộ nhớ tạm.', 'error');
        }
      });
    });

    document.querySelectorAll('.btn-test-query').forEach(btn => {
      btn.addEventListener('click', () => {
        const query = btn.dataset.query;
        if (!query) return;
        this.switchTab('tab-candidates');
        const searchField = document.getElementById('filter-search');
        if (searchField) {
          searchField.value = query;
          this.page = 1;
          this.loadCandidates();
          this.showAppToast('Tra cứu ứng viên', `Đang tìm kiếm theo mẫu: ${query}`, 'info', 3000);
        }
      });
    });

    // 4. Quick Action Launcher Buttons
    document.getElementById('btn-help-open-config')?.addEventListener('click', () => {
      this.switchTab('tab-config');
    });

    document.getElementById('btn-help-open-parsing')?.addEventListener('click', () => {
      this.switchTab('tab-parsing');
    });

    document.getElementById('btn-help-test-toast')?.addEventListener('click', () => {
      this.testWindowsNotifier();
    });

    document.getElementById('btn-help-open-cv-folder')?.addEventListener('click', async () => {
      if (!this.api || !this.api.open_folder) return;
      try {
        const res = await this.api.open_folder('cv');
        if (res && res.ok) {
          this.showAppToast('Mở thư mục CV', `Đang mở: ${res.path}`, 'success', 2500);
        } else {
          this.showAppToast('Lỗi mở thư mục', (res && res.error) || 'Thư mục không tồn tại.', 'error');
        }
      } catch (e) {
        console.error('open_folder cv err:', e);
      }
    });

    document.getElementById('btn-help-open-db-folder')?.addEventListener('click', async () => {
      if (!this.api || !this.api.open_folder) return;
      try {
        const res = await this.api.open_folder('db');
        if (res && res.ok) {
          this.showAppToast('Mở thư mục CSDL', `Đang mở: ${res.path}`, 'success', 2500);
        } else {
          this.showAppToast('Lỗi mở thư mục', (res && res.error) || 'Thư mục không tồn tại.', 'error');
        }
      } catch (e) {
        console.error('open_folder db err:', e);
      }
    });

    document.getElementById('btn-help-open-logs')?.addEventListener('click', () => {
      const modal = document.getElementById('log-history-modal');
      if (modal) {
        modal.classList.remove('hidden');
        this.loadHistoryLogs();
      } else if (this.api && this.api.open_folder) {
        this.api.open_folder('log');
      }
    });

    document.getElementById('btn-help-check-runtime')?.addEventListener('click', () => {
      const modal = document.getElementById('runtime-readiness-modal');
      if (modal) {
        modal.classList.remove('hidden');
        this.loadRuntimeReadiness(true);
      }
    });
  }

  escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

}

window.app = new App();
