import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Workflows from './Workflows'
import { api, WorkflowStage } from './api'

const mockStages: WorkflowStage[] = [
  {
    id: 1,
    domain: 'talent',
    code: 'pending',
    label: 'Mới trong danh sách',
    color: '#64748b',
    position: 0,
    is_terminal: false,
    requires_reason: false,
    sla_hours: 24,
    is_active: true,
    allowed_next: ['contacting'],
  },
  {
    id: 2,
    domain: 'talent',
    code: 'contacting',
    label: 'Đang tiếp cận',
    color: '#2563eb',
    position: 1,
    is_terminal: false,
    requires_reason: false,
    sla_hours: 48,
    is_active: true,
    allowed_next: ['submitted', 'returned'],
  },
  {
    id: 3,
    domain: 'talent',
    code: 'submitted',
    label: 'Hoàn tất mục tiêu',
    color: '#10b981',
    position: 2,
    is_terminal: true,
    requires_reason: false,
    sla_hours: null,
    is_active: true,
    allowed_next: [],
  },
  {
    id: 4,
    domain: 'talent',
    code: 'returned',
    label: 'Đưa về chăm sóc dài hạn',
    color: '#ea580c',
    position: 3,
    is_terminal: true,
    requires_reason: true,
    sla_hours: null,
    is_active: true,
    allowed_next: [],
  },
  {
    id: 5,
    domain: 'rb',
    code: 'new',
    label: 'Mới',
    color: '#64748b',
    position: 0,
    is_terminal: false,
    requires_reason: false,
    sla_hours: 12,
    is_active: true,
    allowed_next: ['accepted'],
  },
  {
    id: 6,
    domain: 'rb',
    code: 'won',
    label: 'Thành công',
    color: '#10b981',
    position: 1,
    is_terminal: true,
    requires_reason: false,
    sla_hours: null,
    is_active: true,
    allowed_next: [],
  },
]

describe('Workflows Pipeline Configuration Studio', () => {
  let queryClient: QueryClient

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    })
    vi.spyOn(api, 'workflowStages').mockResolvedValue({ results: mockStages })
    vi.spyOn(api, 'workflowStageUpdate').mockResolvedValue({ results: mockStages })
  })

  afterEach(() => {
    cleanup()
  })

  it('hiển thị đầy đủ tiêu đề, các chỉ số KPI và các bước Talent mặc định', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Workflows />
        </MemoryRouter>
      </QueryClientProvider>
    )

    expect(await screen.findByText('Cấu hình Pipeline & Quy trình Vận hành')).toBeInTheDocument()
    expect(screen.getByText(/Talent Radar \(Tuyển dụng\)/)).toBeInTheDocument()
    expect(screen.getByText(/Growth Radar \(Khách hàng & Bán lẻ\)/)).toBeInTheDocument()

    // Kiểm tra render các bước Talent
    const items = await screen.findAllByText('Mới trong danh sách')
    expect(items.length).toBeGreaterThan(0)
    expect(screen.getByRole('heading', { name: 'Đang tiếp cận' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Hoàn tất mục tiêu' })).toBeInTheDocument()
  })

  it('cho phép chuyển đổi giữa tab Talent Radar và Growth Radar', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Workflows />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await screen.findAllByText('Mới trong danh sách')

    // Bấm sang tab Growth Radar
    const rbTab = screen.getByText(/Growth Radar \(Khách hàng & Bán lẻ\)/)
    fireEvent.click(rbTab)

    expect(await screen.findByRole('heading', { name: 'Thành công' })).toBeInTheDocument()
    expect(screen.queryByText('Mới trong danh sách')).not.toBeInTheDocument()
  })

  it('chuyển đổi giữa các chế độ xem Sơ đồ luồng, Bảng ma trận và Thẻ cấu hình', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Workflows />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await screen.findAllByText('Mới trong danh sách')

    // Chuyển sang Bảng ma trận
    const tableBtn = screen.getByText('Bảng ma trận')
    fireEvent.click(tableBtn)

    expect(screen.getByText('Mã định danh')).toBeInTheDocument()
    expect(screen.getByText('Bước tiếp theo cho phép')).toBeInTheDocument()

    // Chuyển sang Thẻ cấu hình
    const cardsBtn = screen.getByText('Thẻ cấu hình')
    fireEvent.click(cardsBtn)

    expect(screen.getAllByText('Chỉnh sửa chi tiết').length).toBeGreaterThan(0)
  })

  it('lọc danh sách bước theo từ khóa tìm kiếm', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Workflows />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await screen.findAllByText('Mới trong danh sách')

    const searchInput = screen.getByPlaceholderText('Tìm kiếm bước theo tên hoặc mã...')
    fireEvent.change(searchInput, { target: { value: 'tiếp cận' } })

    expect(screen.getByRole('heading', { name: 'Đang tiếp cận' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Mới trong danh sách' })).not.toBeInTheDocument()
  })

  it('mở modal chỉnh sửa chi tiết khi click vào bước trên sơ đồ luồng', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Workflows />
        </MemoryRouter>
      </QueryClientProvider>
    )

    const stageCard = await screen.findByRole('heading', { name: 'Mới trong danh sách' })
    fireEvent.click(stageCard)

    expect(screen.getByText('Bước kết thúc quy trình (Terminal Stage)')).toBeInTheDocument()
  })
})
