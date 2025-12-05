// src/components/EmailModal.tsx
import { useMemo } from 'react'
import DOMPurify from 'dompurify'
import type { EmailSnippet } from '../types'
import './email-modal.css'

type Props = {
  email: EmailSnippet
  onClose: () => void
}

export default function EmailModal({ email, onClose }: Props) {
  const date = email.received_datetime?.slice(0, 10) ?? ''
  const sender = email.from_name || email.from_address || 'Unknown sender'

  const srcDoc = useMemo(() => {
    const cleaned = email.body_html
      ? DOMPurify.sanitize(email.body_html, { ADD_ATTR: ['target'] })
      : ''

    return `
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <base target="_blank">
  <style>
    html, body {
      margin: 0;
      padding: 0;
      background: #050814;
      color: #e8eef7;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, system-ui, sans-serif;
      line-height: 1.45;
    }
    .mail-wrap {
      box-sizing: border-box;
      padding: 18px;
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

  return (
    <div className="email-modal-backdrop" onClick={onClose}>
      <div
        className="email-modal"
        onClick={e => e.stopPropagation()} // prevent closing when clicking inside
      >
        <header className="email-modal-header">
          <div className="email-modal-meta">
            <div className="email-modal-sender">{sender}</div>
            {date && <div className="email-modal-date">{date}</div>}
          </div>
          <button className="email-modal-close" onClick={onClose} aria-label="Close email">
            ✕
          </button>
        </header>

        {email.hero_image_url && (
          <div className="email-modal-hero">
            <img
              src={email.hero_image_url}
              alt={`Hero image for ${sender}`}
              onError={e => {
                (e.target as HTMLImageElement).style.display = 'none'
              }}
            />
            {email.cosine_sim !== undefined && (
              <span className="email-modal-sim">
                Similarity: {(email.cosine_sim * 100).toFixed(1)}%
              </span>
            )}
          </div>
        )}

        {email.body_html ? (
          <div className="email-modal-frame-wrap">
            <iframe
              className="email-modal-iframe"
              sandbox="allow-popups allow-popups-to-escape-sandbox"
              srcDoc={srcDoc}
              title={`email-full-${email.email_id}`}
            />
          </div>
        ) : (
          <p className="email-modal-fallback">
            No HTML body stored for this email.
          </p>
        )}
      </div>
    </div>
  )
}
