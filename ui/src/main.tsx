import { StrictMode, lazy, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import './i18n'
import './index.css'
import App from './App.tsx'

const SceneTemplateReview = lazy(() => import('./features/sceneTemplates/SceneTemplateReviewPage'))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {window.location.pathname === '/scene-template-review'
      ? <Suspense fallback={<p>Loading scene gallery…</p>}><SceneTemplateReview /></Suspense>
      : <App />}
  </StrictMode>,
)
