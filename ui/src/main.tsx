import { StrictMode, lazy, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import './i18n'
import './index.css'
import App from './App.tsx'
import { AppErrorBoundary } from './components/AppErrorBoundary'
import { reportUiError } from './lib/reportUiError'

const SceneTemplateReview = lazy(() => import('./features/sceneTemplates/SceneTemplateReviewPage'))

createRoot(document.getElementById('root')!, {
  onUncaughtError: (error, info) => reportUiError(error, 'uncaught', info.componentStack),
}).render(
  <StrictMode>
    <AppErrorBoundary>
      {window.location.pathname === '/scene-template-review'
        ? <Suspense fallback={<p>Cargando galería de escenas…</p>}><SceneTemplateReview /></Suspense>
        : <App />}
    </AppErrorBoundary>
  </StrictMode>,
)
