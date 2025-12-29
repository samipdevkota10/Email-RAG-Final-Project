import { useEffect, useRef, useState, useMemo, useCallback } from 'react'
import {
  getAnalyticsOffers,
  getAnalyticsSummary,
  getAvailableIndustries,
  getHeadlineStats,
  getDiscountDistribution,
  getTrends,
} from '../api'
import type { AnalyticsOffer, HeadlineStats, DiscountDistribution, WeeklyStat } from '../types'
import EmailCard from './EmailCard'
import EmailModal from './EmailModal'
import './analytics.css'

// Formatting helpers
const fmtCurrency = (amt?: number, currency = 'USD') =>
  amt === undefined || amt === null
    ? null
    : new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(amt)
const fmtDate = (iso?: string) =>
  iso ? new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : ''

// --- Helper: Convert ISO Week to Readable Date Range ---
const getWeekDateRange = (year: number, week: number) => {
  const date = new Date(year, 0, 1 + (week - 1) * 7)
  const dayOfWeek = date.getDay()
  const isoWeekStart = date
  if (dayOfWeek <= 4) date.setDate(date.getDate() - date.getDay() + 1)
  else date.setDate(date.getDate() + 8 - date.getDay())
  
  const end = new Date(isoWeekStart)
  end.setDate(end.getDate() + 6)
  
  const opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' }
  return `${isoWeekStart.toLocaleDateString('en-US', opts)} - ${end.toLocaleDateString('en-US', opts)}`
}

const QUARTERS = [
  { name: 'Q1', weeks: Array.from({ length: 13 }, (_, i) => i + 1) },
  { name: 'Q2', weeks: Array.from({ length: 13 }, (_, i) => i + 14) },
  { name: 'Q3', weeks: Array.from({ length: 13 }, (_, i) => i + 27) },
  { name: 'Q4', weeks: Array.from({ length: 13 }, (_, i) => i + 40) },
]

export default function Analytics() {
  // --- Search Params (Server Side) ---
  const [year, setYear] = useState(2025)
  const [selectedWeek, setSelectedWeek] = useState<number | null>(null)
  const [selectedIndustry, setSelectedIndustry] = useState<string>('')
  const [topN] = useState(20) // faster initial load

  // --- Display State ---
  const [sortBy, setSortBy] = useState<'week' | 'percent' | 'amount'>('week')
  const [offers, setOffers] = useState<AnalyticsOffer[]>([])
  const [industries, setIndustries] = useState<string[]>([])
  
  // --- Dashboard Stats (The "Up Top" Summary) ---
  const [headline, setHeadline] = useState<HeadlineStats | null>(null)
  const [distribution, setDistribution] = useState<DiscountDistribution | null>(null)
  const [trends, setTrends] = useState<WeeklyStat[]>([])
  
  // --- AI State ---
  const [summary, setSummary] = useState<string>('')
  const [citations, setCitations] = useState<number[]>([])
  
  // --- UI State ---
  const [isSearching, setIsSearching] = useState(false)
  const [isSummarizing, setIsSummarizing] = useState(false)
  const [isLoadingStats, setIsLoadingStats] = useState(true)
  const [selectedEmail, setSelectedEmail] = useState<AnalyticsOffer | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  
  const resultsRef = useRef<HTMLDivElement>(null)

  // 1. Load Dashboard Stats on Mount & Year Change
  useEffect(() => {
    setIsLoadingStats(true)
    Promise.all([
      getAvailableIndustries(),
      getHeadlineStats(year),
      getDiscountDistribution(year),
      getTrends(year, selectedIndustry || undefined)
    ]).then(([ind, stats, dist, trend]) => {
      setIndustries(ind)
      setHeadline(stats)
      setDistribution(dist)
      setTrends(trend)
    }).catch(e => {
      console.error("Failed to load dashboard data", e)
    }).finally(() => {
      setIsLoadingStats(false)
    })
  }, [year])

  // 2. Update trends when industry changes
  useEffect(() => {
    if (!isLoadingStats) {
      getTrends(year, selectedIndustry || undefined)
        .then(setTrends)
        .catch(e => console.error("Failed to load trends", e))
    }
  }, [selectedIndustry, year, isLoadingStats])

  // 3. Auto-fetch offers on mount
  useEffect(() => {
    handleSearch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 4. The Main Search Function
  const handleSearch = useCallback(async () => {
    setIsSearching(true)
    setErrorMsg(null)
    setSummary('')
    setCitations([])
    try {
      const resp = await getAnalyticsOffers({
        year,
        week: selectedWeek || undefined,
        industry: selectedIndustry || undefined,
        top_n: topN,
        sort_by: sortBy === 'week' ? 'week' : sortBy,
        include_other_types: true,
      })
      if (resp.success) {
        setOffers(resp.offers)
        if (resp.offers.length > 0) {
          setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth' }), 100)
        }
      } else {
        setOffers([])
      }
    } catch (e: any) {
      setErrorMsg("Unable to fetch offers. Check connection.")
    } finally {
      setIsSearching(false)
    }
  }, [year, selectedWeek, selectedIndustry, topN, sortBy])

  // 5. AI Summary Function
  const handleGenerateSummary = async () => {
    if (offers.length === 0) return
    setIsSummarizing(true)
    try {
      const topIds = offers.slice(0, 20).map(o => o.offer_id)
      const resp = await getAnalyticsSummary({
        year,
        week: selectedWeek || undefined,
        industry: selectedIndustry || undefined,
        offer_ids: topIds
      })
      setSummary(resp.summary)
      setCitations(resp.citations)
    } catch (e) {
      console.error(e)
    } finally {
      setIsSummarizing(false)
    }
  }

  // 6. Client-Side Sorting
  const displayedOffers = useMemo(() => {
    let sorted = [...offers]
    if (sortBy === 'percent') {
      sorted.sort((a, b) => (b.percent_off || 0) - (a.percent_off || 0))
    } else if (sortBy === 'amount') {
      sorted.sort((a, b) => (b.amount_off || 0) - (a.amount_off || 0))
    } else {
      sorted.sort((a, b) => (b.iso_week || 0) - (a.iso_week || 0))
    }
    return sorted
  }, [offers, sortBy])

  // Group by week for sectioning
  const groupedOffers = useMemo(() => {
    const grouped: Record<number, AnalyticsOffer[]> = {}
    displayedOffers.forEach(offer => {
      const w = offer.iso_week || 0
      if (!grouped[w]) grouped[w] = []
      grouped[w].push(offer)
    })
    return Object.entries(grouped).sort((a, b) => Number(b[0]) - Number(a[0]))
  }, [displayedOffers])

  // Helper to get WoW change for a week
  const getWowForWeek = (weekNum: number): number | null => {
    const stat = trends.find(t => t.week === weekNum)
    return stat?.wow_change ?? null
  }

  return (
    <div className="analytics-shell">
      {/* SIDEBAR */}
      <aside className="analytics-sidebar">
        <div className="sidebar-header">
          <h2>Market Pulse</h2>
          <p className="subtitle">NRF 2025 Analysis</p>
        </div>

        {/* Year Filter */}
        <div className="control-group">
          <label>Year</label>
          <div className="year-stepper">
            <button onClick={() => setYear(y => y - 1)}>←</button>
            <span>{year}</span>
            <button onClick={() => setYear(y => y + 1)}>→</button>
          </div>
        </div>

        {/* Industry Filter */}
        <div className="control-group">
          <label>Industry / Sector</label>
          <select
            className="sidebar-select"
            value={selectedIndustry}
            onChange={e => setSelectedIndustry(e.target.value)}
          >
            <option value="">All Sectors</option>
            {industries.map(i => <option key={i} value={i}>{i}</option>)}
          </select>
        </div>

        {/* Week Filter */}
        <div className="control-group">
          <label>Time Period</label>
          <div className="week-grid-container">
            <button
              className={`week-btn full-year ${selectedWeek === null ? 'active' : ''}`}
              onClick={() => setSelectedWeek(null)}
            >
              Full Year {year}
            </button>
            <div className="quarters-list">
              {QUARTERS.map(q => (
                <div key={q.name} className="quarter-group">
                  <span className="quarter-label">{q.name}</span>
                  <div className="week-grid">
                    {q.weeks.map(w => (
                      <button
                        key={w}
                        className={`week-btn ${selectedWeek === w ? 'active' : ''}`}
                        onClick={() => setSelectedWeek(w === selectedWeek ? null : w)}
                        title={`Week ${w}`}
                      >
                        {w}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Action */}
        <div className="sidebar-footer">
          <button
            className="search-cta"
            onClick={handleSearch}
            disabled={isSearching}
          >
            {isSearching ? 'Analyzing...' : 'Run Analysis'}
          </button>
        </div>
      </aside>

      {/* RESULTS AREA */}
      <main className="analytics-results" ref={resultsRef}>
        
        {/* --- STATS SUMMARY UP TOP --- */}
        {headline && (
          <div className="headline-stats-row">
            <div className="stat-card">
              <span className="stat-label">Active Offers</span>
              <span className="stat-value">{headline.total_active_offers.toLocaleString()}</span>
            </div>
            <div className="stat-card">
              <span className="stat-label">Avg Discount</span>
              <span className="stat-value">{headline.avg_market_discount.toFixed(1)}%</span>
            </div>
            <div className="stat-card">
              <span className="stat-label">Top Industry</span>
              <span className="stat-value small-text">{headline.top_industry || 'N/A'}</span>
            </div>
          </div>
        )}

        {/* --- ENHANCED DISTRIBUTION SECTION --- */}
        {distribution && distribution.buckets && distribution.buckets.length > 0 && (
          <div className="distribution-section">
            <div className="distribution-header">
              <h3>Discount Distribution</h3>
              <div className="distribution-stats">
                <span className="dist-stat">
                  <strong>Median:</strong> {distribution.median_discount?.toFixed(1) || 'N/A'}%
                </span>
                <span className="dist-stat">
                  <strong>Range:</strong> {distribution.min_discount.toFixed(0)}% - {distribution.max_discount.toFixed(0)}%
                </span>
                {distribution.std_dev && (
                  <span className="dist-stat">
                    <strong>Std Dev:</strong> ±{distribution.std_dev.toFixed(1)}%
                  </span>
                )}
              </div>
            </div>
            <div className="histogram-chart">
              {distribution.buckets.map(bucket => (
                <div key={bucket.bucket_label} className="histogram-bar-container">
                  <div 
                    className="histogram-bar"
                    style={{ height: `${Math.max(bucket.percentage, 3)}%` }}
                    title={`${bucket.bucket_label}: ${bucket.count} offers (${bucket.percentage}%)${bucket.avg_in_bucket ? ` • Avg: ${bucket.avg_in_bucket}%` : ''}`}
                  >
                    <span className="bar-count">{bucket.count}</span>
                  </div>
                  <span className="bar-label">{bucket.bucket_label}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Toolbar */}
        <header className="results-header">
          <div className="header-left">
            <h1>
              {selectedWeek ? `Week ${selectedWeek}` : `${year} Overview`}
              {selectedIndustry && <span className="highlight-text"> in {selectedIndustry}</span>}
            </h1>
            {selectedWeek && (
              <span className="date-range-badge">
                📅 {getWeekDateRange(year, selectedWeek)}
              </span>
            )}
          </div>
          <div className="header-controls">
            <span className="count-badge">{offers.length} Offers Found</span>
            <select
              value={sortBy}
              onChange={e => setSortBy(e.target.value as any)}
              className="glass-select"
            >
              <option value="week">Date (Newest)</option>
              <option value="percent">Discount % (High)</option>
              <option value="amount">Amount $ (High)</option>
            </select>
          </div>
        </header>

        {/* AI Summary */}
        {summary && (
          <div className="ai-summary-card">
            <div className="ai-header">
              <span className="ai-icon">✨</span>
              <h3>Executive Summary</h3>
            </div>
            <p>{summary}</p>
            <button className="close-summary" onClick={() => setSummary('')}>Close</button>
          </div>
        )}

        {/* Loading / Error States */}
        {isSearching && (
          <div className="state-message loading">
            <div className="empty-icon">⏳</div>
            <h3>Analyzing Offers...</h3>
          </div>
        )}

        {errorMsg && !isSearching && (
          <div className="state-message error">
            <p>{errorMsg}</p>
            <button onClick={handleSearch}>Try Again</button>
          </div>
        )}

        {!isSearching && !errorMsg && offers.length === 0 && (
          <div className="state-message empty">
            <p>No offers found. Try adjusting filters.</p>
          </div>
        )}

        {/* Grid Stream */}
        <div className="offers-stream">
          {!isSearching && offers.length > 0 && !summary && (
            <div className="summary-trigger-row">
              <button
                className="btn-summarize"
                onClick={handleGenerateSummary}
                disabled={isSummarizing}
              >
                {isSummarizing ? 'Generating...' : '✨ Generate AI Summary'}
              </button>
            </div>
          )}

          {groupedOffers.map(([weekNum, weekOffers]) => (
            <div key={weekNum} className="week-section">
              {!selectedWeek && (
                <div className="week-divider">
                  <h3>Week {weekNum}</h3>
                  <span className="week-dates">{getWeekDateRange(year, Number(weekNum))}</span>
                  {(() => {
                    const wow = getWowForWeek(Number(weekNum))
                    if (wow !== null && wow !== 0) {
                      return (
                        <span className={`wow-badge ${wow > 0 ? 'up' : 'down'}`}>
                          {wow > 0 ? '↑' : '↓'} {Math.abs(wow).toFixed(1)}% WoW
                        </span>
                      )
                    }
                    return null
                  })()}
                </div>
              )}
              
              <div className="card-grid-3">
                {weekOffers.map((offer, idx) => (
                  <div
                    key={offer.offer_id}
                    className={`card-wrapper ${citations.includes(offer.offer_id) ? 'highlighted' : ''}`}
                  >
                    {/* Rank Badge */}
                    {offer.week_rank && offer.week_rank <= 3 && (
                      <div className={`rank-badge rank-${offer.week_rank}`}>
                        #{offer.week_rank}
                      </div>
                    )}
                    
                    {/* Brand Header */}
                    <div className="brand-header-mini">
                      <span className="brand-name">{offer.company_name || offer.from_name}</span>
                      <span className="industry-tag">{offer.primary_industry}</span>
                    </div>

                    <EmailCard
                      email={offer}
                      idx={idx}
                      onOpen={() => setSelectedEmail(offer)}
                    />
                    {/* Offer detail pills */}
                    <div className="offer-pill-row">
                      {offer.discount_type === 'PERCENT' && offer.percent_off !== null && (
                        <span className="pill pill-strong">
                          {offer.is_up_to ? 'Up to ' : ''}{offer.percent_off}% off
                        </span>
                      )}
                      {offer.discount_type === 'AMOUNT' && offer.amount_off !== null && (
                        <span className="pill pill-strong">
                          {offer.is_up_to ? 'Up to ' : ''}{fmtCurrency(offer.amount_off, offer.currency || 'USD')}
                        </span>
                      )}
                      {offer.discount_type && !['PERCENT','AMOUNT'].includes(offer.discount_type) && (
                        <span className="pill pill-type">{offer.discount_type}</span>
                      )}
                      {offer.promo_code && (
                        <span className="pill pill-code">Code: {offer.promo_code}</span>
                      )}
                      {offer.min_spend !== null && offer.min_spend !== undefined && (
                        <span className="pill pill-min">Min {fmtCurrency(offer.min_spend, offer.currency || 'USD')}</span>
                      )}
                    </div>

                    {/* Meta footer */}
                    <div className="offer-meta">
                      <div className="meta-left">
                        <span className="pill pill-light">ISO Week {offer.iso_week}</span>
                        <span className="pill pill-light">Received {fmtDate(offer.received_datetime || undefined)}</span>
                      </div>
                      <div className="meta-right">
                        {offer.secondary_industry && (
                          <span className="pill pill-light">Secondary: {offer.secondary_industry}</span>
                        )}
                      </div>
                    </div>
                    
                    {/* Hot Deal Badge */}
                    {offer.percent_off && offer.percent_off >= 40 && (
                      <div className="hot-deal-badge">🔥 {offer.percent_off}% OFF</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </main>

      {selectedEmail && (
        <EmailModal email={selectedEmail} onClose={() => setSelectedEmail(null)} />
      )}
    </div>
  )
}