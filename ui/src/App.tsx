import { Navigate, Route, Routes } from 'react-router'
import { Shell } from '@/components/Shell'
import { ToastProvider } from '@/components/ui'
import { AppDataProvider } from '@/lib/app-data'
import { ChatPage } from '@/pages/ChatPage'
import { SessionsPage } from '@/pages/SessionsPage'
import { FilesPage } from '@/pages/FilesPage'
import { AnalyticsPage } from '@/pages/AnalyticsPage'
import { ModelsPage } from '@/pages/ModelsPage'
import { LogsPage } from '@/pages/LogsPage'
import { CronPage } from '@/pages/CronPage'
import { SkillsPage } from '@/pages/SkillsPage'
import { ToolsPage } from '@/pages/ToolsPage'
import { ChannelsPage } from '@/pages/ChannelsPage'
import { ConfigPage } from '@/pages/ConfigPage'
import { KeysPage } from '@/pages/KeysPage'
import { SystemPage } from '@/pages/SystemPage'
import { DocsPage } from '@/pages/DocsPage'
import { SetupPage } from '@/pages/SetupPage'
import { UpdatePage, WifiPage } from '@/pages/WifiUpdate'

/**
 * Route table.
 *
 * Pages are imported eagerly on purpose: `React.lazy` emits dynamic imports,
 * and a single inlined bundle plus a constrained device is not a good place
 * for chunk-loading machinery — the whole dashboard is ~440 KB and arrives in
 * one request, so a spinner between routes would be pure latency.
 */
export default function App() {
  return (
    <ToastProvider>
      <AppDataProvider>
        <Shell>
          <Routes>
            <Route path="/" element={<ChatPage />} />
            <Route path="/sessions" element={<SessionsPage />} />
            <Route path="/files" element={<FilesPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
            <Route path="/models" element={<ModelsPage />} />
            <Route path="/logs" element={<LogsPage />} />
            <Route path="/cron" element={<CronPage />} />
            <Route path="/skills" element={<SkillsPage />} />
            <Route path="/tools" element={<ToolsPage />} />
            <Route path="/channels" element={<ChannelsPage />} />
            <Route path="/config" element={<ConfigPage />} />
            <Route path="/keys" element={<KeysPage />} />
            <Route path="/system" element={<SystemPage />} />
            <Route path="/docs" element={<DocsPage />} />
            <Route path="/setup" element={<SetupPage />} />
            <Route path="/wifi" element={<WifiPage />} />
            <Route path="/update" element={<UpdatePage />} />
            {/* legacy routes from the pre-React UI */}
            <Route path="/agent" element={<Navigate to="/config" replace />} />
            <Route path="/functions" element={<Navigate to="/tools" replace />} />
            <Route path="/stats" element={<Navigate to="/analytics" replace />} />
            <Route path="/journey" element={<Navigate to="/sessions" replace />} />
            <Route path="/admin" element={<Navigate to="/system" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Shell>
      </AppDataProvider>
    </ToastProvider>
  )
}
