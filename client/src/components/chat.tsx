import { useEffect, useRef, useState, useMemo, useCallback } from 'react'
import {
  getDateRange,
  chatAnswer,
  searchImagesByText,
  searchImagesByImage,
  getImageIndexStats,
} from '../api'
import type { EmailResponse, ImageSearchResponse, EmailSnippet } from '../types'
import EmailCard from './EmailCard'
import EmailModal from './EmailModal'
import './chat.css'

type BaseMsg = {
  id: string
  role: 'user' | 'assistant'
  text: string
  timestamp: string
}

type AssistantMsg = BaseMsg & {
  role: 'assistant'
  data?: EmailResponse
  summary?: string
  citations?: number[]
  imageResults?: ImageSearchResponse
}

type UserMsg = BaseMsg & { role: 'user' }

type Msg = UserMsg | AssistantMsg

type ToggleProps = {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  hint?: string
}

const ToggleRow = ({ label, checked, onChange, hint }: ToggleProps) => (
  <label className="toggle">
    <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
    <span>
      {label}
      {hint && <small>{hint}</small>}
    </span>
  </label>
)

const quickRanges = [
  { label: '7d', value: 7 },
  { label: '30d', value: 30 },
  { label: 'All', value: 'all' as const },
]
type QuickValue = (typeof quickRanges)[number]['value']

export default function Chat() {
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [includeBody, setIncludeBody] = useState(true)
  const [useVectorSearch, setUseVectorSearch] = useState(false)
  const [searchMode, setSearchMode] = useState<'text' | 'image-text' | 'image-image'>('text')
  const [imageUrl, setImageUrl] = useState('')
  const [uploadedImage, setUploadedImage] = useState<File | null>(null)
  const [imagePreview, setImagePreview] = useState<string | null>(null)
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [limit, setLimit] = useState(12)
  const [busy, setBusy] = useState(false)
  const [meta, setMeta] = useState<{ min?: string; max?: string; total?: number }>({})
  const [selectedEmail, setSelectedEmail] = useState<EmailSnippet | null>(null)
  const [quickRange, setQuickRange] = useState<QuickValue | null>(null)
  const [toast, setToast] = useState<{ type: 'info' | 'error'; message: string } | null>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const showToast = useCallback((message: string, type: 'info' | 'error' = 'error') => {
    setToast({ message, type })
  }, [])

  useEffect(() => {
    if (!toast) return
    const id = window.setTimeout(() => setToast(null), 3500)
    return () => window.clearTimeout(id)
  }, [toast])

  // Initial metadata + welcome message
  useEffect(() => {
    Promise.all([getDateRange(), getImageIndexStats().catch(() => null)])
      .then(([dateRange, imgStats]) => {
        const min = dateRange.min_date?.slice(0, 10)
        const max = dateRange.max_date?.slice(0, 10)
        const totalEmails = dateRange.total_emails ?? 0
        const totalImages = imgStats?.embedded ?? 0
        setMeta({ min, max, total: dateRange.total_emails })
        setMessages([
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            text: `${totalEmails.toLocaleString()} emails · ${totalImages.toLocaleString()} images indexed`,
            timestamp: new Date().toISOString(),
          },
        ])
      })
      .catch(() => {})
  }, [])

  // Auto-scroll to bottom on new messages / loading state
  useEffect(() => {
    listRef.current?.scrollTo({
      top: listRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [messages, busy])

  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      if (!file.type.startsWith('image/')) {
        showToast('Please select an image file')
        return
      }
      setUploadedImage(file)
      // Create preview
      const reader = new FileReader()
      reader.onloadend = () => {
        setImagePreview(reader.result as string)
      }
      reader.readAsDataURL(file)
      // Also set imageUrl to the data URL
      const reader2 = new FileReader()
      reader2.onloadend = () => {
        setImageUrl(reader2.result as string)
      }
      reader2.readAsDataURL(file)
    }
  }

  const clearImage = () => {
    setUploadedImage(null)
    setImagePreview(null)
    setImageUrl('')
    setQuickRange(null)
    // Reset file input
    const fileInput = document.getElementById('image-upload') as HTMLInputElement | null
    if (fileInput) fileInput.value = ''
  }

  // Quick date helpers
  const applyQuickRange = (value: QuickValue) => {
    setQuickRange(value)
    if (value === 'all') {
      setStart('')
      setEnd('')
      return
    }
    const now = new Date()
    const endDate = now.toISOString().slice(0, 10)
    const from = new Date(now)
    from.setDate(from.getDate() - value)
    const startDate = from.toISOString().slice(0, 10)
    setStart(startDate)
    setEnd(endDate)
  }

  const formatTimestamp = (iso?: string) =>
    iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''

  const send = useCallback(async () => {
    const q = input.trim()
    if (searchMode === 'image-image' && !imageUrl.trim() && !uploadedImage) {
      showToast('Upload an image or provide a URL to search visually.')
      return
    }
    if (!q || busy) return

    const timestamp = new Date().toISOString()
    const userMsg: Msg = {
      id: crypto.randomUUID(),
      role: 'user',
      text: searchMode === 'image-image' ? `Find images similar to: ${imageUrl}` : q,
      timestamp,
    }
    setMessages(m => [...m, userMsg])
    setInput('')
    setBusy(true)

    try {
      if (searchMode === 'image-text') {
        // Image text search
        const resp = await searchImagesByText({
          text: q,
          start: start || undefined,
          end: end || undefined,
          limit,
          offset: 0,
        })

        // Convert ImageHit[] to EmailSnippet[] for display
        const emails = resp.items.map(item => ({
          email_id: item.email_id,
          snippet_text: item.snippet_text || 'No snippet',
          from_name: item.from_name,
          from_address: null,
          received_datetime: item.received_datetime,
          body_html: null,
          hero_image_url: item.hero_image_url,
          cosine_sim: item.cosine_sim,
        }))

        setMessages(m => [
          ...m,
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            text: resp.message,
            summary: resp.message,
            timestamp: new Date().toISOString(),
            data: {
              success: true,
              count: resp.count,
              total_count: resp.total_count,
              emails,
              message: resp.message,
            },
            imageResults: resp,
          },
        ])
      } else if (searchMode === 'image-image') {
        // Image similarity search
        // Use uploaded image (base64 data URL) or provided URL
        const imgUrl = uploadedImage ? imageUrl : imageUrl.trim()
        if (!imgUrl) {
          throw new Error('Please upload an image or provide an image URL')
        }
        const resp = await searchImagesByImage({
          image_url: imgUrl,
          start: start || undefined,
          end: end || undefined,
          limit,
          offset: 0,
        })

        const emails = resp.items.map(item => ({
          email_id: item.email_id,
          snippet_text: item.snippet_text || 'No snippet',
          from_name: item.from_name,
          from_address: null,
          received_datetime: item.received_datetime,
          body_html: null,
          hero_image_url: item.hero_image_url,
          cosine_sim: item.cosine_sim,
        }))

        setMessages(m => [
          ...m,
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            text: resp.message,
            summary: resp.message,
            timestamp: new Date().toISOString(),
            data: {
              success: true,
              count: resp.count,
              total_count: resp.total_count,
              emails,
              message: resp.message,
            },
            imageResults: resp,
          },
        ])
      } else {
        // Regular text search (keyword/vector)
        const resp = await chatAnswer({
          query: q,
          mode: useVectorSearch ? 'vector' : 'keyword',
          start: start || undefined,
          end: end || undefined,
          limit,
          offset: 0,
          include_body: includeBody,
        })

        setMessages(m => [
          ...m,
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            text: resp.summary,
            summary: resp.summary,
            timestamp: new Date().toISOString(),
            data: resp.results,
            citations: resp.citations,
          },
        ])
      }
    } catch (e: any) {
      showToast(e?.message ?? 'Search failed. Please try again.')
      setMessages(m => [
        ...m,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          text: e?.message ?? 'Search failed.',
          timestamp: new Date().toISOString(),
        },
      ])
    } finally {
      setBusy(false)
    }
  }, [
    busy,
    end,
    imageUrl,
    includeBody,
    input,
    limit,
    searchMode,
    showToast,
    start,
    uploadedImage,
    useVectorSearch,
  ])

  const disableSend = useMemo(() => {
    if (busy) return true
    if (searchMode === 'image-image') return (!imageUrl.trim() && !uploadedImage) || !input.trim()
    return !input.trim()
  }, [busy, input, searchMode, imageUrl, uploadedImage])

  return (
    <div className="app-shell">
      {/* Header */}
     <header className="app-header">
  <div className="meta">
    {meta.min && meta.max && (
      <span className="chip">
        Dataset: {meta.min} → {meta.max}
      </span>
    )}
    {typeof meta.total === 'number' && (
      <span className="chip">{meta.total} emails</span>
    )}
  </div>
</header>


      <div className="app-body">
        {/* Sidebar filters */}
        <aside className="panel panel-scroll">
          <div className="panel-title">Filters</div>

          {/* Time range */}
          <div className="panel-section">
            <div className="panel-section-head">
              <span>Time range</span>
              {meta.min && meta.max && (
                <span className="panel-hint">
                  {meta.min} → {meta.max}
                </span>
              )}
            </div>
            <div className="form-row">
              <label>Start</label>
              <input
                className="field-input"
                type="date"
                value={start}
                onChange={e => {
                  setQuickRange(null)
                  setStart(e.target.value)
                }}
              />
            </div>
            <div className="form-row">
              <label>End</label>
              <input
                className="field-input"
                type="date"
                value={end}
                onChange={e => {
                  setQuickRange(null)
                  setEnd(e.target.value)
                }}
              />
            </div>
            <div className="segmented" role="group" aria-label="Quick date ranges">
              {quickRanges.map(opt => (
                <button
                  key={opt.label}
                  type="button"
                  className={`segment ${quickRange === opt.value ? 'active' : ''}`}
                  onClick={() => applyQuickRange(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          <div className="divider" />

          {/* Search mode */}
          <div className="panel-section">
            <div className="panel-section-head">
              <span>Search mode</span>
            </div>
            <div className="form-row">
              <label>Mode</label>
              <select
                className="select"
                value={searchMode}
                onChange={e =>
                  setSearchMode(e.target.value as 'text' | 'image-text' | 'image-image')
                }
              >
                <option value="text">Text Search</option>
                <option value="image-text">Image Text Search</option>
                <option value="image-image">Image Similarity</option>
              </select>
            </div>
          </div>

          {/* Options for text mode */}
          {searchMode === 'text' && (
            <div className="panel-section">
              <div className="panel-section-head">
                <span>Options</span>
              </div>
              <ToggleRow
                label="Use AI similarity"
                checked={useVectorSearch}
                onChange={setUseVectorSearch}
                hint="Vector search for semantic matches"
              />

              {!useVectorSearch && (
                <ToggleRow
                  label="Include HTML bodies"
                  checked={includeBody}
                  onChange={setIncludeBody}
                  hint="Slightly slower but broader"
                />
              )}
            </div>
          )}

          {/* Options for image similarity */}
          {searchMode === 'image-image' && (
            <div className="panel-section">
              <div className="panel-section-head">
                <span>Image options</span>
              </div>

              <div className="form-row">
                <label>Upload image</label>
                <input
                  id="image-upload"
                  className="file-input"
                  type="file"
                  accept="image/*"
                  onChange={handleImageUpload}
                />
              </div>

              {imagePreview && (
                <div className="image-preview-container">
                  <img src={imagePreview} alt="Preview" className="image-preview" />
                  <button type="button" className="clear-image-btn" onClick={clearImage}>
                    ×
                  </button>
                </div>
              )}

              <div className="form-row">
                <label>OR image URL</label>
                <input
                  className="field-input"
                  type="text"
                  placeholder="https://example.com/image.jpg"
                  value={imageUrl && !imagePreview ? imageUrl : ''}
                  onChange={e => {
                    if (!imagePreview) {
                      setImageUrl(e.target.value)
                    }
                  }}
                  disabled={!!imagePreview}
                />
              </div>
            </div>
          )}

          {/* Common controls */}
          <div className="panel-section">
            <div className="panel-section-head">
              <span>Results</span>
            </div>
            <div className="form-row">
              <label>Limit</label>
              <input
                className="field-input"
                type="number"
                min={1}
                max={50}
                value={limit}
                onChange={e => setLimit(Number(e.target.value || 10))}
              />
            </div>
            <button
              className="link"
              type="button"
              onClick={() => {
                setStart('')
                setEnd('')
              }}
            >
              Clear dates
            </button>
          </div>
        </aside>

        {/* Main chat */}
        <main className="chat">
          <div
            className="history"
            ref={listRef}
            aria-live="polite"
            aria-busy={busy}
            role="log"
          >
            {messages.map(m => (
              <section key={m.id} className={`msg ${m.role}`}>
                <div className="bubble">
                  <span className="timestamp">{formatTimestamp(m.timestamp)}</span>

                  {/* Assistant summary uses bold heading style */}
                  <p className={`text ${m.role === 'assistant' ? 'summary' : ''}`}>
                    {m.role === 'assistant' && m.summary ? m.summary : m.text}
                  </p>

                  {/* Citations row (NEW) */}
                  {m.role === 'assistant' && m.citations && m.citations.length > 0 && (
                    <div className="citations-row">
                      <strong>Sources:</strong> {m.citations.join(', ')}
                    </div>
                  )}

                  {/* Results grid */}
                  {m.role === 'assistant' && m.data && (
                    <>
                      {m.data.total_count === 0 ? (
                        <div className="empty">
                          <div className="empty-title">No results</div>
                          <div className="muted">
                            Try removing date filters or switch search mode.
                          </div>
                        </div>
                      ) : (
                        <>
                          <div className="grid">
                            {m.data.emails.map((e, i) => (
                              <div
                                key={`${e.email_id}-${i}`}
                                className={`grid-item ${
                                  m.citations?.includes(e.email_id) ? 'is-cited' : ''
                                }`}
                              >
                                <EmailCard
                                  email={e}
                                  idx={i}
                                  onOpen={() => setSelectedEmail(e)}
                                />
                              </div>
                            ))}
                          </div>
                          <div className="muted small center">
                            Showing {m.data.count} of {m.data.total_count}
                          </div>
                        </>
                      )}
                    </>
                  )}
                </div>
              </section>
            ))}

            {busy && (
              <section className="msg assistant">
                <div className="bubble">
                  <div className="skeleton">
                    <div className="line w60" />
                    <div className="line w90" />
                    <div className="grid">
                      {Array.from({ length: 6 }).map((_, i) => (
                        <div key={i} className="card-skel" />
                      ))}
                    </div>
                  </div>
                </div>
              </section>
            )}
          </div>

          {/* Sticky composer */}
          <div className="composer">
            <input
              className="input"
              placeholder={
                searchMode === 'image-text'
                  ? 'Describe the image style, e.g., "warm fall colors"…'
                  : searchMode === 'image-image'
                  ? 'Enter image URL above, then click Send'
                  : useVectorSearch
                  ? 'Ask about creative trends…'
                  : 'Ask about offers or holidays…'
              }
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => (e.key === 'Enter' ? send() : undefined)}
              disabled={searchMode === 'image-image' && !imageUrl.trim() && !uploadedImage}
            />
            <button className="btn" onClick={send} disabled={disableSend}>
              {busy && <span className="spinner" aria-hidden />}
              <span>{busy ? 'Searching' : 'Send'}</span>
            </button>
          </div>
        </main>
      </div>

      {toast && (
        <div className={`toast ${toast.type === 'error' ? 'error' : ''}`} role="status">
          {toast.message}
        </div>
      )}

      {/* Floating email viewer */}
      {selectedEmail && (
        <EmailModal email={selectedEmail} onClose={() => setSelectedEmail(null)} />
      )}
    </div>
  )
}
