import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { CustomThemeProvider } from './CustomThemeContext'
import { SearchStateProvider } from './searchPersistence'
import './styles.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <CustomThemeProvider>
        <BrowserRouter>
          {/* Ngoài <Routes> (trong App) — kết quả tìm kiếm AI sống suốt phiên
              làm việc, không mất khi điều hướng qua route khác rồi quay lại. */}
          <SearchStateProvider>
            <App />
          </SearchStateProvider>
        </BrowserRouter>
      </CustomThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
)
