import { useMemo, useRef, useEffect, useState } from 'react'
import DOMPurify from 'dompurify'
import type { EmailSnippet } from '../types'
import './email-card.css'

type Props = {
  email: EmailSnippet
  idx: number
  height?: number   // card iframe height (preview)
  autoHeight?: boolean
  onOpen?: () => void
}

export default function EmailCard({ email, idx, height = 480, autoHeight = false, onOpen }: Props) {
  const date = email.received_datetime?.slice(0, 10) ?? ''
  const sender = email.from_name || email.from_address || 'Unknown sender'
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const [dynHeight, setDynHeight] = useState<number>(height)

  const srcDoc = useMemo(() => {
    const cleaned = email.body_html
      ? DOMPurify.sanitize(email.body_html, { ADD_ATTR: ['target'] })
      : ''

    return `
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1" />
  <base target="_blank">
  <style>
    html, body {
      margin: 0;
      padding: 0;
      background: #020617;
      color: #e8eef7;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, system-ui, sans-serif;
      line-height: 1.45;
    }
    .mail-wrap {
      box-sizing: border-box;
      padding: 10px 12px;
      min-height: 100%;
    }
    img, video, iframe, table {
      max-width: 100% !important;
      height: auto !important;
    }
    * { box-sizing: border-box; }
    a { color: #7aa2ff; }
  </style>
</head>
<body>
  <div class="mail-wrap">${cleaned}</div>
</body>
</html>`
  }, [email.body_html])

  useEffect(() => {
    if (!autoHeight) return
    const el = iframeRef.current
    if (!el) return

    const handleLoad = () => {
      try {
        const doc = el.contentDocument || el.contentWindow?.document
        if (!doc) return
        const h = Math.max(
          doc.body?.scrollHeight || 0,
          doc.documentElement?.scrollHeight || 0
        )
        setDynHeight(Math.min(Math.max(h + 2, 220), 1400))
      } catch {
        setDynHeight(height)
      }
    }
    el.addEventListener('load', handleLoad)
    return () => el.removeEventListener('load', handleLoad)
  }, [srcDoc, autoHeight, height])

  return (
    <article
      className={`email-card ${onOpen ? 'clickable' : ''}`}
      aria-labelledby={`email-${email.email_id}-${idx}`}
      onClick={onOpen}
    >
      <header className="email-head">
        <div className="email-head-left">
          <strong id={`email-${email.email_id}-${idx}`} className="sender">
            {sender}
          </strong>
          {date && <span className="email-date">{date}</span>}
        </div>
        {email.cosine_sim !== undefined && (
          <span className="email-sim-chip">
            {(email.cosine_sim * 100).toFixed(1)}%
          </span>
        )}
      </header>

      {email.snippet_text && (
        <p className="email-snippet">{email.snippet_text}</p>
      )}

      {email.hero_image_url && (
        <div className="hero-image-container">
          <img
            src={email.hero_image_url}
            alt={`Hero image for ${sender}`}
            className="hero-image"
            onError={e => {
              (e.target as HTMLImageElement).style.display = 'none'
            }}
          />
        </div>
      )}

      {email.body_html && (
        <div
          className="email-frame-wrap"
          style={{ height: autoHeight ? dynHeight : height }}
        >
          <iframe
            ref={iframeRef}
            className="email-iframe"
            sandbox="allow-popups allow-popups-to-escape-sandbox"
            srcDoc={srcDoc}
            title={`email-${email.email_id}`}
          />
        </div>
      )}

      {onOpen && (
        <button
          type="button"
          className="email-open-btn"
          onClick={e => {
            e.stopPropagation()
            onOpen()
          }}
        >
          Open full email
        </button>
      )}
    </article>
  )
}
