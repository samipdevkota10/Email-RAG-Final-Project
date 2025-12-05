import { useEffect, useState, useMemo } from 'react'
import DOMPurify from 'dompurify'
import { getNextEvalEmail, submitEvalLabel, type EvalEmail } from '../api'
import './eval.css'

export default function EvalLabeler() {
  const [email, setEmail] = useState<EvalEmail | null>(null)
  const [done, setDone] = useState(false)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [hasOffer, setHasOffer] = useState<boolean | null>(null)
  const [offerType, setOfferType] = useState<string>('')
  const [discountValue, setDiscountValue] = useState<string>('')
  const [discountUnit, setDiscountUnit] = useState<string>('')
  const [holiday, setHoliday] = useState<string>('')
  const [notes, setNotes] = useState<string>('')

  const subject = useMemo(() => {
    if (!email?.header_text) return '(no subject)'
    const raw = email.header_text.trim()
    const headerMatch = raw.match(/['"]subject['"]\s*:\s*['"]([^'"]+)['"]/i)
    return headerMatch?.[1] || raw
  }, [email?.header_text])

  const resetForm = () => {
    setHasOffer(null)
    setOfferType('')
    setDiscountValue('')
    setDiscountUnit('')
    setHoliday('')
    setNotes('')
  }

  const loadNext = async () => {
    setLoading(true)
    setError(null)
    try {
      const resp = await getNextEvalEmail()
      if (resp.done || !resp.email) {
        setDone(true)
        setEmail(null)
      } else {
        setEmail(resp.email)
        setDone(false)
        resetForm()
      }
    } catch (e: any) {
      setError(e?.message ?? 'Failed to load next email')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadNext()
  }, [])

  // Debug HTML sample
  useEffect(() => {
    if (email?.body_html) {
      console.log('BODY_HTML sample:', email.body_html.slice(0, 200))
    }
  }, [email])

  const srcDoc = useMemo(() => {
    if (!email?.body_html)
      return '<!doctype html><html><body><p>No HTML body.</p></body></html>'

    const raw = email.body_html.trim()

    if (raw.startsWith('<!DOCTYPE') || raw.startsWith('<html')) {
      return DOMPurify.sanitize(raw, {
        WHOLE_DOCUMENT: true,
        ADD_ATTR: ['target'],
      })
    }

    const cleaned = DOMPurify.sanitize(raw, { ADD_ATTR: ['target'] })

    return `
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <base target="_blank" />
  <style>
    html, body {
      margin: 0;
      padding: 0;
      background: #0f131a;
      color: #e8eef7;
      font-family: system-ui, sans-serif;
    }
    .mail-wrap { padding: 16px; }
    img, video, iframe, table {
      max-width: 100% !important;
      height: auto !important;
    }
  </style>
</head>
<body>
  <div class="mail-wrap">${cleaned}</div>
</body>
</html>`
  }, [email])

  const canSubmit =
    !!email && hasOffer !== null && (!hasOffer || offerType.length > 0)

  const handleSubmit = async () => {
    if (!email || !canSubmit || saving) return
    setSaving(true)
    setError(null)
    try {
      await submitEvalLabel({
        email_id: email.email_id,
        has_offer: !!hasOffer,
        offer_type: hasOffer ? offerType || null : 'none',
        discount_value: hasOffer && discountValue ? Number(discountValue) : null,
        discount_unit: hasOffer ? discountUnit || null : null,
        holiday: holiday || null,
        notes: notes || null,
        labeled_by: 'samip',
      })
      await loadNext()
    } catch (e: any) {
      setError(e?.message ?? 'Failed to save label')
    } finally {
      setSaving(false)
    }
  }

  if (done) {
    return (
      <div className="eval-shell">
        <h1>Email Labeling</h1>
        <p>All sampled emails have been labeled. 🎉</p>
        <button onClick={loadNext}>Reload</button>
      </div>
    )
  }

  return (
    <div className="eval-shell">
      <header className="eval-header">
        <h1>Email Labeling</h1>
        {email && (
          <div className="eval-meta">
            <span>ID: {email.email_id}</span>
            {email.received_datetime && (
              <span>{email.received_datetime.slice(0, 10)}</span>
            )}
            {email.from_name && <span>From: {email.from_name}</span>}
          </div>
        )}
      </header>

      {error && <div className="eval-error">{error}</div>}
      {loading && <div className="eval-loading">Loading…</div>}

      {email && !loading && (
        <div className="eval-body">
          {/* Email preview */}
          <div className="eval-email">
            <h2 className="eval-subject">{subject}</h2>
            {email.snippet_text && (
              <p className="eval-snippet">{email.snippet_text}</p>
            )}
            <div className="eval-iframe-wrap">
              <iframe
                title={`email-${email.email_id}`}
                srcDoc={srcDoc}
                sandbox="allow-popups allow-popups-to-escape-sandbox"
              />
            </div>
          </div>

          {/* Label Form */}
          <div className="eval-form">
            <h2>Label</h2>

            <div className="form-group">
              <label>Has offer?</label>
              <div className="radio-row">
                <label>
                  <input
                    type="radio"
                    name="has_offer"
                    checked={hasOffer === true}
                    onChange={() => setHasOffer(true)}
                  />
                  Yes
                </label>
                <label>
                  <input
                    type="radio"
                    name="has_offer"
                    checked={hasOffer === false}
                    onChange={() => setHasOffer(false)}
                  />
                  No
                </label>
              </div>
            </div>

            {hasOffer && (
              <>
                <div className="form-group">
                  <label>Offer type</label>
                  <select
                    value={offerType}
                    onChange={e => setOfferType(e.target.value)}
                  >
                    <option value="">Select…</option>
                    <option value="percent">Percent off</option>
                    <option value="dollar_off">Dollar off</option>
                    <option value="bogo">BOGO</option>
                    <option value="free_shipping">Free shipping</option>
                    <option value="bundle">Bundle</option>
                    <option value="other">Other</option>
                  </select>
                </div>

                <div className="form-row-inline">
                  <div className="form-group">
                    <label>Discount value</label>
                    <input
                      type="number"
                      value={discountValue}
                      onChange={e => setDiscountValue(e.target.value)}
                      placeholder="e.g. 20"
                    />
                  </div>

                  <div className="form-group">
                    <label>Unit</label>
                    <select
                      value={discountUnit}
                      onChange={e => setDiscountUnit(e.target.value)}
                    >
                      <option value="">None</option>
                      <option value="%">%</option>
                      <option value="$">$</option>
                      <option value="shipping">shipping</option>
                      <option value="bogo">bogo</option>
                    </select>
                  </div>
                </div>
              </>
            )}

            <div className="form-group">
              <label>Holiday (optional)</label>
              <input
                type="text"
                value={holiday}
                onChange={e => setHoliday(e.target.value)}
                placeholder="Black Friday, Mother's Day, etc."
              />
            </div>

            <div className="form-group">
              <label>Notes</label>
              <textarea
                rows={4}
                value={notes}
                onChange={e => setNotes(e.target.value)}
                placeholder="Any additional details..."
              />
            </div>

            <div className="eval-actions">
              <button
                type="button"
                onClick={loadNext}
                disabled={loading || saving}
              >
                Skip
              </button>
              <button
                type="button"
                onClick={handleSubmit}
                disabled={!canSubmit || saving}
              >
                {saving ? 'Saving…' : 'Save & next'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
