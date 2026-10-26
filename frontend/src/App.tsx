import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, CalendarDays,
  CheckCircle2, ChevronDown, Clock3, CloudLightning, Download, ExternalLink,
  Gauge, RefreshCw, ShieldCheck, SlidersHorizontal, Wind, Zap,
} from 'lucide-react'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'

type Metrics = {
  maeMW: number | null; rmseMW: number | null; biasMW: number | null; wapePct: number | null;
  mapePct?: number | null; mapeEligiblePeriods?: number; p90AbsErrorMW?: number | null; p95AbsErrorMW?: number | null;
  p90OverforecastMW?: number | null; overforecastPct?: number | null;
  matchedPeriods: number; coveragePct: number; expectedPeriods?: number; forecastPeriods?: number;
  actualPeriods?: number; missingForecastPeriods?: number; missingActualPeriods?: number;
  forecastAvailabilityPct?: number; actualEnergyGWh?: number | null; forecastEnergyGWh?: number | null;
}
type Point = {
  startTime: string; deliveryDate: string; decisionDate: string; intervalIndex: number; resolutionMinutes: number;
  actualMW: number | null; actualHalfHour00MW?: number | null; actualHalfHour30MW?: number | null;
  forecastMW: number | null; errorMW: number | null;
  actualMinusForecastMW?: number | null; absoluteErrorMW: number | null; percentageError: number | null;
  publishTime: string | null; forecastLeadHours?: number | null; decisionLeadHours?: number | null;
  intervalLowMW?: number | null; intervalHighMW?: number | null;
}
type Daily = { decisionDate: string; deliveryDate: string; label: string } & Metrics & {
  latestPublishTime: string | null; periods: number; calibrationReady: boolean; calibrationDays: number;
  calibrationMatchedPeriods: number; marginP90OverforecastMW: number | null; intervalCoveragePct: number | null;
  meanIntervalWidthMW: number | null;
}
type Horizon = { band: string; lowerHours: number; upperHours: number | null; count: number; maeMW: number | null; rmseMW: number | null; biasMW: number | null; overforecastPct: number | null }
type Analysis = {
  scope: { decisionMonth: string; decisionStart: string; decisionEndExclusive: string; deliveryStart: string; deliveryEndInclusive: string; timezone: string; cutoff: string; decisionRule: string; calibrationRule: string };
  metrics: Metrics; daily: Daily[]; rows: Point[]; horizon: Horizon[]; byHour: {hour:number; label:string; count:number; maeMW:number|null; biasMW:number|null; overforecastPct:number|null}[];
  histogram: {centerMW:number;count:number;lowerMW:number;upperMW:number}[];
  backtest: {method:string; nominalCoveragePct:number; calibratedDecisionDays:number; totalDecisionDays:number; meanObservedCoveragePct:number|null; meanIntervalWidthMW:number|null; meanAbsoluteCoverageGapPct:number|null; note:string};
  source: 'live' | 'cache' | 'stale-cache' | 'demo'; status: 'live' | 'cached' | 'demo'; warnings: string[];
  generatedAt: string; meta: { actualRecords: number; forecastRecords: number; matchedPeriods: number; expectedDecisionPeriods: number; warmupDecisionDays:number; sourceActualResolutionMinutes:number; sourceForecastResolutionMinutes:number; evaluationResolutionMinutes:number; sourceActualHalfHourlyPeriods:number; expectedSourceActualHalfHourlyPeriods:number; latestSelectedPublishTime: string | null; sourceDatasets: string[]; units: string; fetchedAt:string|null; dataSha256:string; analysisRunId:string; decisionPeriodCountPerDay:number; cacheTtlSeconds:number; minCalibrationDays:number; calibrationWindowDays:number };
}
const API_ROOT = import.meta.env.VITE_API_ROOT || ''
const CUTOFFS = ['08:00', '09:00', '09:50', '10:00', '10:30', '11:00', '12:00', '14:00']
const fmtNum = (v: number | null | undefined, decimals = 0) => v == null || !Number.isFinite(v) ? '—' : v.toLocaleString('en-GB', { maximumFractionDigits: decimals, minimumFractionDigits: decimals })
const fmtMW = (v: number | null | undefined) => v == null ? '—' : `${fmtNum(v)} MW`
const fmtDate = (value: string | null | undefined, withDay = true) => {
  if (!value) return 'Not available'
  const d = new Date(value)
  return d.toLocaleDateString('en-GB', withDay ? { day: '2-digit', month: 'short', year: 'numeric' } : { day: '2-digit', month: 'short' })
}
const fmtTime = (value: string | null | undefined) => value ? new Date(value).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/London', timeZoneName: 'short' }) : 'No eligible forecast'
const shortTime = (value: string) => new Date(value).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/London' })
const errorTone = (v: number | null) => v == null ? 'neutral' : v > 0 ? 'warm' : 'cool'

function App() {
  const [cutoff, setCutoff] = useState('09:00')
  const [selectedDate, setSelectedDate] = useState('2026-01-14')
  const [data, setData] = useState<Analysis | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [refreshToken, setRefreshToken] = useState(0)
  const forceRefreshRef = useRef(false)
  const [activeNav, setActiveNav] = useState('Overview')
  const [showMethodology, setShowMethodology] = useState(false)
  const [demoMode, setDemoMode] = useState(false)

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      setLoading(true)
      setError('')
      try {
        // A manual refresh is a one-shot request. Changing cutoff/date should reuse the cached source snapshot.
        const shouldRefresh = forceRefreshRef.current
        forceRefreshRef.current = false
        const params = new URLSearchParams({ month: '2026-01', cutoff, refresh: shouldRefresh ? 'true' : 'false', demo: demoMode ? 'true' : 'false' })
        const response = await fetch(`${API_ROOT}/api/analysis?${params.toString()}`)
        const body = await response.json()
        if (!response.ok) throw new Error(body.detail || `API returned ${response.status}`)
        if (cancelled) return
        const result = body as Analysis
        setData(result)
        const dayExists = result.daily.some(d => d.decisionDate === selectedDate)
        if (!dayExists) setSelectedDate(result.daily.find(d => d.decisionDate === '2026-01-14')?.decisionDate || result.daily[0]?.decisionDate || '')
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Unable to load analysis.')
      } finally {
        if (!cancelled) { setLoading(false); setRefreshing(false) }
      }
    }
    run()
    return () => { cancelled = true }
  }, [cutoff, refreshToken, demoMode])

  const selectedDay = data?.daily.find(d => d.decisionDate === selectedDate) || data?.daily[0]
  const dayRows = useMemo(() => (data?.rows || []).filter(r => r.decisionDate === (selectedDay?.decisionDate || selectedDate)), [data, selectedDay, selectedDate])
  const chartRows = useMemo(() => dayRows.map(r => ({
    ...r,
    time: shortTime(r.startTime),
    actual: r.actualMW,
    forecast: r.forecastMW,
    absError: r.absoluteErrorMW,
    intervalBand: r.intervalLowMW != null && r.intervalHighMW != null ? [r.intervalLowMW, r.intervalHighMW] : null,
  })), [dayRows])

  const refreshData = () => { forceRefreshRef.current = true; setRefreshing(true); setRefreshToken(v => v + 1) }
  const exportCsv = () => {
    if (!data) return
    const header = ['startTime','decisionDate','deliveryDate','intervalIndex','resolutionMinutes','forecastMW','actualHalfHour00MW','actualHalfHour30MW','actualMW','errorMW','percentageError','publishTime','forecastLeadHours','intervalLowMW','intervalHighMW','source','cutoff','evaluationResolutionMinutes','sourceActualHalfHourlyPeriods','expectedSourceActualHalfHourlyPeriods','analysisRunId','dataSha256','generatedAt']
    const rows = dayRows.map(r => {
      const record = r as unknown as Record<string, unknown>
      const audit: Record<string, unknown> = { source: data.source, cutoff: data.scope.cutoff, analysisRunId: data.meta.analysisRunId, dataSha256: data.meta.dataSha256, generatedAt: data.generatedAt }
      return header.map(key => {
        const value = key in audit ? audit[key] : record[key]
        if (value == null) return ''
        const text = String(value)
        return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
      }).join(',')
    })
    const blob = new Blob([[header.join(','), ...rows].join('\n')], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = `winddesk-decision-${selectedDay?.decisionDate || 'day'}.csv`; a.click()
    URL.revokeObjectURL(url)
  }

  const sourceLive = data?.source === 'live'
  const sourceLabel = data?.source === 'live' ? 'LIVE ELEXON' : data?.source === 'cache' ? 'CACHED SNAPSHOT' : data?.source === 'stale-cache' ? 'STALE SNAPSHOT' : data?.source === 'demo' ? 'SYNTHETIC DEMO' : 'CONNECTING'
  const metrics = data?.metrics

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand-lockup"><div className="brand-mark"><Wind size={20} strokeWidth={1.8} /></div><div><div className="brand-name">WINDDESK</div><div className="brand-sub">FORECAST INTELLIGENCE</div></div></div>
      <div className="workspace-pill"><span className="live-dot"/><span>GB POWER DESK</span><ChevronDown size={13}/></div>
      <div className="nav-label">WORKSPACE</div>
      <nav className="main-nav">
        <button className={`nav-link ${activeNav === 'Overview' ? 'active' : ''}`} onClick={() => setActiveNav('Overview')}><Activity size={17}/><span>Overview</span><span className="nav-index">01</span></button>
        <button className={`nav-link ${activeNav === 'Forecast accuracy' ? 'active' : ''}`} onClick={() => {setActiveNav('Forecast accuracy'); document.getElementById('accuracy-panel')?.scrollIntoView({behavior:'smooth',block:'start'})}}><Gauge size={17}/><span>Forecast accuracy</span></button>
        <button className={`nav-link ${activeNav === 'Hourly intervals' ? 'active' : ''}`} onClick={() => {setActiveNav('Hourly intervals'); document.getElementById('period-table')?.scrollIntoView({behavior:'smooth',block:'start'})}}><CalendarDays size={17}/><span>Hourly intervals</span></button>
      </nav>
      <div className="sidebar-divider"/>
      <div className="nav-label">DATA & CONTROLS</div>
      <button className="nav-link" onClick={() => setShowMethodology(v => !v)}><SlidersHorizontal size={17}/><span>Methodology</span><span className="method-dot">i</span></button>
      <a className="nav-link nav-external" href="https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream" target="_blank" rel="noreferrer"><ExternalLink size={16}/><span>Elexon data source</span></a>
      <div className="sidebar-bottom">
        <div className="status-card"><div className="status-icon"><ShieldCheck size={16}/></div><div><strong>Read-only analysis</strong><span>No automated trades</span></div></div>
        <div className="sidebar-foot"><span>PRODUCT PILOT</span><span>v1.0.0</span></div>
      </div>
    </aside>

    <main className="main-content">
      <header className="topbar">
        <div className="breadcrumbs"><span>Workspace</span><span className="crumb-slash">/</span><strong>Wind procurement</strong></div>
        <div className="topbar-right"><div className="environment-tag" title={data?.meta.fetchedAt ? `Last successful source fetch: ${fmtTime(data.meta.fetchedAt)}` : 'No successful live source fetch recorded'}><span className={`env-dot ${sourceLive ? 'green' : 'amber'}`}/>{loading ? 'CONNECTING' : sourceLabel}</div><div className="topbar-avatar">GB</div></div>
      </header>

      <div className="page-wrap">
        <section className="hero-row">
          <div>
            <div className="eyebrow"><span className="eyebrow-line"/> DAY-AHEAD PROCUREMENT <span className="eyebrow-sep">·</span> UK NATIONAL WIND</div>
            <h1>Know what the wind<br/><em>will deliver.</em></h1>
            <p className="hero-copy">A decision-time view of wind generation forecasts — with measurable uncertainty before the day-ahead buy.</p>
            <div className="scope-line"><CalendarDays size={14}/><span>Decision dates <b>01–31 Jan 2026</b></span><span className="scope-dot">·</span><span>Delivery dates <b>02 Jan–01 Feb</b></span></div>
          </div>
          <div className="hero-visual" aria-label="Wind generation overview illustration">
            <div className="orbital orbital-one"/><div className="orbital orbital-two"/><div className="orbital orbital-three"/>
            <div className="hero-visual-core"><Wind size={38} strokeWidth={1.15}/><span>WIND<br/>OUTLOOK</span></div>
            <div className="floating-readout readout-a"><span className="readout-overline">FORECAST HORIZON</span><strong>D+1</strong><span>Day-ahead</span></div>
            <div className="floating-readout readout-b"><span className="readout-overline">EVALUATION</span><strong>60 <small>MIN</small></strong><span>Hourly comparison</span></div>
          </div>
        </section>

        {data?.source === 'demo' && <div className="data-warning"><AlertTriangle size={16}/><div><strong>Synthetic demo data is active.</strong> Values below are generated fixtures, not Elexon observations. Do not use them for operational or procurement decisions.</div></div>}
        {(data?.source === 'stale-cache') && <div className="data-warning"><AlertTriangle size={16}/><div><strong>Stale cached snapshot.</strong> The live refresh failed. Validate the source timestamp before interpreting any results.</div></div>}
        {data?.warnings?.map((warning, i) => <div className="data-warning" key={i}><AlertTriangle size={16}/><div>{warning}</div></div>)}
        {error && <div className="error-banner"><AlertTriangle size={17}/><div><strong>Could not load analysis</strong><span>{error}</span></div><button onClick={refreshData}>Try again</button></div>}

        <section className="control-strip">
          <div className="control-intro"><div className="control-glyph"><Clock3 size={17}/></div><div><strong>Decision context</strong><span>Choose the latest forecast available at decision time</span></div></div>
          <div className="control-field"><label htmlFor="cutoff">Decision cut-off <span>UK TIME</span></label><div className="select-wrap"><select id="cutoff" value={cutoff} onChange={e => setCutoff(e.target.value)}>{CUTOFFS.map(t => <option key={t} value={t}>{t}</option>)}</select><ChevronDown size={14}/></div></div>
          <div className="control-field delivery-field"><label htmlFor="decision-date">Decision date <span>DELIVERY D+1</span></label><div className="select-wrap"><select id="decision-date" value={selectedDay?.decisionDate || selectedDate} onChange={e => setSelectedDate(e.target.value)} disabled={!data}>{(data?.daily || []).map(d => <option key={d.decisionDate} value={d.decisionDate}>{fmtDate(d.decisionDate, false)} → {fmtDate(d.deliveryDate, false)}</option>)}</select><ChevronDown size={14}/></div></div>
          <label className="demo-mode-toggle" title="Use only synthetic records for an offline UI walkthrough"><input type="checkbox" checked={demoMode} onChange={e => { setDemoMode(e.target.checked); if (!e.target.checked) { forceRefreshRef.current = true; setRefreshToken(v => v + 1) } }} /><span>Demo fixture</span></label><button className="refresh-button" onClick={refreshData} disabled={loading || refreshing}><RefreshCw size={15} className={refreshing ? 'spin' : ''}/><span>{refreshing ? 'Refreshing' : 'Refresh data'}</span></button>
        </section>

        <section className="metric-grid" aria-label="Forecast accuracy summary">
          <article className="metric-card metric-primary"><div className="metric-top"><span>Mean absolute error</span><span className="metric-symbol"><Activity size={16}/></span></div><div className="metric-value">{loading ? '—' : fmtNum(metrics?.maeMW)} <small>MW</small></div><div className="metric-foot"><span className="metric-dot green-dot"/> Typical miss per hourly interval</div><div className="metric-accent-line"/></article>
          <article className="metric-card"><div className="metric-top"><span>Weighted absolute error</span><span className="metric-symbol"><Gauge size={16}/></span></div><div className="metric-value">{loading ? '—' : fmtNum(metrics?.wapePct, 2)}<small>%</small></div><div className="metric-foot">Absolute errors ÷ total actual wind</div></article>
          <article className="metric-card"><div className="metric-top"><span>Forecast bias</span><span className={`bias-icon ${errorTone(metrics?.biasMW ?? null)}`}>{(metrics?.biasMW ?? 0) >= 0 ? <ArrowUpRight size={16}/> : <ArrowDownRight size={16}/>}</span></div><div className={`metric-value ${errorTone(metrics?.biasMW ?? null)}`}>{loading ? '—' : `${(metrics?.biasMW ?? 0) > 0 ? '+' : ''}${fmtNum(metrics?.biasMW)}`} <small>MW</small></div><div className="metric-foot">{(metrics?.biasMW ?? 0) > 0 ? 'Over-forecast on average' : 'Under-forecast on average'}</div></article>
          <article className="metric-card"><div className="metric-top"><span>P90 absolute error</span><span className="metric-symbol"><Gauge size={16}/></span></div><div className="metric-value">{loading ? '—' : fmtNum(metrics?.p90AbsErrorMW)}<small> MW</small></div><div className="metric-foot">90th percentile historical absolute miss</div></article>
          <article className="metric-card"><div className="metric-top"><span>Over-forecast frequency</span><span className="metric-symbol"><ArrowUpRight size={16}/></span></div><div className="metric-value">{loading ? '—' : fmtNum(metrics?.overforecastPct, 1)}<small>%</small></div><div className="metric-foot">Forecast exceeds actual wind outturn</div></article>
          <article className="metric-card"><div className="metric-top"><span>Paired hourly coverage</span><span className="metric-symbol"><CheckCircle2 size={16}/></span></div><div className="metric-value">{loading ? '—' : fmtNum(metrics?.matchedPeriods)}<small> / {fmtNum(metrics?.expectedPeriods ?? 744)}</small></div><div className="metric-foot">{loading ? 'Matching actuals and forecast vintages' : `${fmtNum(metrics?.coveragePct, 1)}% of expected hourly intervals`}<span className="metric-detail">{loading ? '' : `Forecasts ${fmtNum(metrics?.forecastPeriods)} · actual hours ${fmtNum(metrics?.actualPeriods)} · missing forecast/actual hours ${fmtNum(metrics?.missingForecastPeriods)}/${fmtNum(metrics?.missingActualPeriods)} · FUELHH half-hours ${fmtNum(data?.meta.sourceActualHalfHourlyPeriods)}/${fmtNum(data?.meta.expectedSourceActualHalfHourlyPeriods)}`}</span></div></article>
        </section>

        <section className="extended-metrics" aria-label="Additional forecast accuracy metrics">
          <div><span>ROOT MEAN SQUARED ERROR</span><strong>{loading ? '—' : fmtMW(metrics?.rmseMW)}</strong></div>
          <div><span>MAPE · ACTUAL ≥ 100 MW</span><strong>{loading ? '—' : `${fmtNum(metrics?.mapePct, 2)}%`}<small>{fmtNum(metrics?.mapeEligiblePeriods)} eligible periods</small></strong></div>
          <div><span>P95 ABSOLUTE ERROR</span><strong>{loading ? '—' : fmtMW(metrics?.p95AbsErrorMW)}</strong></div>
          <div><span>P90 OVER-FORECAST ERROR</span><strong>{loading ? '—' : fmtMW(metrics?.p90OverforecastMW)}</strong></div>
        </section>

        <section className="insight-grid">
          <article className="panel forecast-panel">
            <div className="panel-header"><div><div className="panel-kicker">DELIVERY PROFILE <span className="kicker-dot"/></div><h2>Forecast vs actual generation</h2><p>{selectedDay ? `Decision ${fmtDate(selectedDay.decisionDate)} · delivery ${fmtDate(selectedDay.deliveryDate)}` : 'Loading selected decision profile'}</p></div><button className="ghost-button" onClick={exportCsv} disabled={!data || !dayRows.length}><Download size={14}/> Export CSV</button></div>
            <div className="chart-legend"><span><i className="legend-forecast"/> Forecast at cut-off</span><span><i className="legend-actual"/> Actual wind outturn</span><span className="legend-band"/> Prior-only 80% empirical band <span className="legend-unit">MW · hourly intervals</span></div>
            <div className="forecast-chart">
              {loading ? <div className="chart-empty"><span className="loader-ring"/>Loading Elexon time series…</div> : chartRows.length ? <ResponsiveContainer width="100%" height="100%"><AreaChart data={chartRows} margin={{top:14,right:12,left:0,bottom:2}}>
                <defs><linearGradient id="actualFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#76c9b4" stopOpacity={0.20}/><stop offset="100%" stopColor="#76c9b4" stopOpacity={0.005}/></linearGradient></defs>
                <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="#283640"/>
                <XAxis dataKey="time" tick={{fill:'#8495a1',fontSize:10}} tickLine={false} axisLine={false} interval={5} minTickGap={20}/>
                <YAxis tick={{fill:'#8495a1',fontSize:10}} tickLine={false} axisLine={false} width={48} tickFormatter={v => `${(v/1000).toFixed(0)}k`}/>
                <Tooltip content={<ForecastTooltip/>} cursor={{stroke:'#607480',strokeDasharray:'3 4'}}/>
                <Area type="monotone" dataKey="intervalBand" name="Prior-only empirical 80% band" stroke="none" fill="#8ba9ce" fillOpacity={0.16} connectNulls={false} isAnimationActive={false}/>
                <Area type="monotone" dataKey="actual" name="Actual wind" stroke="#75c9b4" strokeWidth={2.2} fill="url(#actualFill)" connectNulls={false} activeDot={{r:4,stroke:'#0f1d25',strokeWidth:2}}/>
                <Line type="monotone" dataKey="forecast" name="Forecast at cut-off" stroke="#d7a55c" strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls={false} activeDot={{r:4,fill:'#d7a55c',stroke:'#0f1d25',strokeWidth:2}}/>
              </AreaChart></ResponsiveContainer> : <div className="chart-empty">No matching periods for this date.</div>}
            </div>
            <div className="chart-footer"><div><span className="foot-label">ACTUAL PEAK</span><strong>{fmtMW(Math.max(0, ...dayRows.map(r => r.actualMW || 0)))}</strong></div><div><span className="foot-label">DAY MEAN ABS. ERROR</span><strong>{fmtMW(selectedDay?.maeMW)}</strong></div><div><span className="foot-label">MATCHED PERIODS</span><strong>{selectedDay?.matchedPeriods ?? '—'} <small>of 24 hourly intervals</small></strong></div></div>
          </article>

          <article className="panel decision-panel">
            <div className="panel-header compact"><div><div className="panel-kicker">DECISION SNAPSHOT</div><h2>What was known?</h2><p>Selected day’s information set</p></div><div className="snapshot-icon"><Zap size={18}/></div></div>
            <div className="snapshot-status"><span className="snapshot-status-dot"/><span>Forecast selected at decision cut-off</span></div>
            <div className="snapshot-row"><span>Decision date</span><strong>{fmtDate(selectedDay?.decisionDate)}</strong></div>
            <div className="snapshot-row"><span>Cut-off time</span><strong>{cutoff} <i>UK local</i></strong></div>
            <div className="snapshot-row"><span>Latest selected publish</span><strong className="snapshot-pub">{fmtTime(selectedDay?.latestPublishTime)}</strong></div>
            <div className="snapshot-row"><span>Forecast vintage coverage</span><strong>{selectedDay?.forecastPeriods === 24 ? '24 / 24 hourly intervals' : `${selectedDay?.forecastPeriods ?? 0} / 24 hourly intervals`}</strong></div>
            <div className="snapshot-row"><span>Prior-only P90 wind shortfall buffer</span><strong className="snapshot-margin">{selectedDay?.calibrationReady ? fmtMW(selectedDay.marginP90OverforecastMW) : 'Insufficient history'}</strong></div>
            <div className="snapshot-row"><span>Calibration sample</span><strong>{selectedDay?.calibrationReady ? `${selectedDay.calibrationDays} complete days · ${selectedDay.calibrationMatchedPeriods} periods` : `${selectedDay?.calibrationDays ?? 0} complete days · insufficient calibration history`}</strong></div>
            <div className="snapshot-row"><span>80% interval hit rate (retrospective)</span><strong>{selectedDay?.intervalCoveragePct == null ? '—' : `${fmtNum(selectedDay.intervalCoveragePct, 1)}%`}</strong></div>
            <div className="decision-rule"><div className="rule-icon"><CloudLightning size={16}/></div><div><strong>Wind-risk signal</strong><p>{decisionText(selectedDay?.biasMW ?? null, selectedDay?.wapePct ?? null)}</p></div></div>
            <div className="snapshot-note"><ShieldCheck size={14}/><span>The buffer is calibrated from errors on fully completed prior delivery days only. It is not a procurement quantity or trading instruction.</span></div>
          </article>
        </section>

        <section className="analysis-grid" id="accuracy-panel">
          <article className="panel accuracy-panel">
            <div className="panel-header"><div><div className="panel-kicker">ERROR THROUGH THE MONTH</div><h2>Day-by-day forecast error</h2><p>Each bar is WAPE for the delivery day linked to that decision.</p></div><div className="accuracy-legend"><i/> WAPE %</div></div>
            <div className="daily-bars">
              {(data?.daily || []).map((d, idx) => {
                const h = Math.max(d.wapePct == null ? 0 : 5, Math.min(100, (d.wapePct || 0) * 4.2))
                return <button className={`daily-bar-cell ${selectedDay?.decisionDate === d.decisionDate ? 'selected' : ''}`} key={d.decisionDate} onClick={() => setSelectedDate(d.decisionDate)} title={`Decision ${d.decisionDate} → delivery ${d.deliveryDate}: ${d.wapePct == null ? 'no data' : `${d.wapePct}% WAPE`}`}>
                  <span className="bar-value">{idx % 5 === 0 || d.decisionDate === selectedDay?.decisionDate ? (d.wapePct == null ? '—' : `${d.wapePct.toFixed(1)}`) : ''}</span>
                  <span className="bar-track"><span className="bar-fill" style={{height:`${h}%`}}/></span>
                  <span className="bar-label">{idx % 2 === 0 ? d.label.split(' ')[0] : ''}</span>
                </button>
              })}
              {!data && <div className="chart-empty">Daily accuracy will appear after data loads.</div>}
            </div>
            <div className="bars-scale"><span>0% WAPE</span><span>Lower is better · select a day to inspect</span></div>
          </article>
          <article className="panel error-panel">
            <div className="panel-header compact"><div><div className="panel-kicker">ERROR DISTRIBUTION</div><h2>Hourly forecast error</h2><p>Absolute forecast error for selected delivery.</p></div></div>
            <div className="error-chart-wrap">{loading ? <div className="chart-empty">Loading…</div> : <ResponsiveContainer width="100%" height="100%"><LineChart data={chartRows} margin={{top:10,right:8,left:0,bottom:0}}>
              <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="#283640"/>
              <XAxis dataKey="time" tick={{fill:'#8495a1',fontSize:9}} tickLine={false} axisLine={false} interval={11}/>
              <YAxis tick={{fill:'#8495a1',fontSize:9}} tickLine={false} axisLine={false} width={44} tickFormatter={v => `${(v/1000).toFixed(1)}k`}/>
              <Tooltip content={<ErrorTooltip/>}/><ReferenceLine y={selectedDay?.maeMW || 0} stroke="#8c9ba5" strokeDasharray="3 3"/>
              <Line type="monotone" dataKey="absError" name="Absolute error" stroke="#db9c61" strokeWidth={1.8} dot={false} connectNulls={false}/>
            </LineChart></ResponsiveContainer>}</div>
            <div className="error-summary"><span>Selected day’s MAE benchmark</span><strong>{fmtMW(selectedDay?.maeMW)}</strong></div>
          </article>
        </section>


        <section className="panel horizon-panel" id="horizon-panel">
          <div className="panel-header"><div><div className="panel-kicker">FORECAST LEAD-TIME DIAGNOSTICS</div><h2>Where does accuracy degrade?</h2><p>Error by the actual age of the selected forecast vintage at delivery time. Empty bands mean no matched sample.</p></div><span className="unit-badge">MAE / MW</span></div>
          <div className="horizon-chart">{loading ? <div className="chart-empty">Calculating horizon diagnostics…</div> : <ResponsiveContainer width="100%" height="100%"><BarChart data={data?.horizon || []} margin={{top:12,right:15,left:0,bottom:0}}>
            <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="#283640"/>
            <XAxis dataKey="band" tick={{fill:'#8495a1',fontSize:10}} tickLine={false} axisLine={false}/>
            <YAxis tick={{fill:'#8495a1',fontSize:10}} tickLine={false} axisLine={false} width={55} tickFormatter={v => `${(v/1000).toFixed(1)}k`}/>
            <Tooltip content={<HorizonTooltip/>}/>
            <Bar dataKey="maeMW" name="MAE" fill="#75c4aa" radius={[3,3,0,0]} maxBarSize={42}/>
          </BarChart></ResponsiveContainer>}</div>
          <div className="horizon-foot"><span><b>{data?.backtest.calibratedDecisionDays ?? 0}</b> / 31 decision days had enough prior calibration history</span><span>Mean interval coverage <b>{data?.backtest.meanObservedCoveragePct == null ? '—' : `${fmtNum(data.backtest.meanObservedCoveragePct, 1)}%`}</b> vs nominal 80%</span><span>Mean interval width <b>{fmtMW(data?.backtest.meanIntervalWidthMW)}</b></span></div>
          <div className="horizon-note">Walk-forward diagnostic: each day’s interval is estimated only from matched errors on fully completed delivery days before that decision date. It is not a guarantee of future coverage.</div>
        </section>

        <section className="panel histogram-panel" id="error-distribution">
          <div className="panel-header"><div><div className="panel-kicker">SIGNED ERROR DISTRIBUTION</div><h2>How forecast misses are distributed</h2><p>January hourly evaluation intervals only. Negative values mean wind was under-forecast; positive values mean wind was over-forecast.</p></div><span className="unit-badge">FORECAST − ACTUAL · MW</span></div>
          <div className="histogram-chart">{loading ? <div className="chart-empty">Loading error distribution…</div> : data?.histogram?.length ? <ResponsiveContainer width="100%" height="100%"><BarChart data={data.histogram} margin={{top:12,right:15,left:0,bottom:8}}>
            <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="#283640"/>
            <XAxis dataKey="centerMW" tick={{fill:'#8495a1',fontSize:10}} tickLine={false} axisLine={false} minTickGap={26} tickFormatter={v => `${Number(v) >= 0 ? '+' : ''}${(Number(v)/1000).toFixed(1)}k`}/>
            <YAxis dataKey="count" tick={{fill:'#8495a1',fontSize:10}} tickLine={false} axisLine={false} width={42} allowDecimals={false}/>
            <ReferenceLine x={0} stroke="#9aa9b2" strokeDasharray="3 3"/>
            <Tooltip content={<HistogramTooltip/>}/>
            <Bar dataKey="count" name="Periods" fill="#d7a55c" radius={[3,3,0,0]} maxBarSize={36}/>
          </BarChart></ResponsiveContainer> : <div className="chart-empty">No matched forecast errors are available.</div>}</div>
          <div className="histogram-foot"><span><b>{fmtNum(data?.metrics.matchedPeriods ?? 0)}</b> matched hourly intervals</span><span>Mean signed bias <b>{data?.metrics.biasMW == null ? '—' : `${data.metrics.biasMW > 0 ? '+' : ''}${fmtMW(data.metrics.biasMW)}`}</b></span><span>P90 absolute error <b>{fmtMW(data?.metrics.p90AbsErrorMW)}</b></span></div>
        </section>

        <section className="panel table-panel" id="period-table">
          <div className="panel-header table-head"><div><div className="panel-kicker">AUDITABLE DETAIL</div><h2>Hourly interval ledger</h2><p>Each hourly actual is the mean of its two half-hour FUELHH readings; missing readings stay visible.</p></div><div className="table-count"><span>{dayRows.length} rows</span><span className="table-sep"/><span>60-min comparison</span></div></div>
           <div className="table-scroll"><table><thead><tr><th>HOUR</th><th>DELIVERY TIME</th><th>FORECAST <small>MW</small></th><th>ACTUAL :00 <small>MW</small></th><th>ACTUAL :30 <small>MW</small></th><th>HOURLY MEAN <small>MW</small></th><th>ERROR <small>MW</small></th><th>PUBLISHED AT</th></tr></thead><tbody>
             {dayRows.slice(0, 24).map(r => <tr key={r.startTime}><td><span className="period-chip">H {String(r.intervalIndex).padStart(2,'0')}</span></td><td className="time-cell">{shortTime(r.startTime)}</td><td className="number-cell forecast-number">{fmtNum(r.forecastMW)}</td><td className="number-cell">{fmtNum(r.actualHalfHour00MW)}</td><td className="number-cell">{fmtNum(r.actualHalfHour30MW)}</td><td className="number-cell">{fmtNum(r.actualMW)}</td><td className={`number-cell ${errorTone(r.errorMW)}`}>{r.errorMW == null ? '—' : `${r.errorMW > 0 ? '+' : ''}${fmtNum(r.errorMW)}`}</td><td className="publish-cell">{r.publishTime ? shortTime(r.publishTime) : 'No eligible vintage'}</td></tr>)}
             {!loading && !dayRows.length && <tr><td colSpan={8} className="empty-table">No hourly evaluation intervals are available.</td></tr>}
          </tbody></table></div>
          <div className="table-footer"><span><span className="table-foot-dot"/> Latest eligible publication chosen separately for each hourly interval</span><button onClick={exportCsv} disabled={!data || !dayRows.length}><Download size={13}/> Download selected day</button></div>
        </section>

        {showMethodology && <section className="panel methodology-panel"><div className="panel-header"><div><div className="panel-kicker">REPRODUCIBILITY</div><h2>Methodology & interpretation</h2></div><button className="close-method" onClick={() => setShowMethodology(false)}>Close</button></div><div className="method-grid"><div><strong>1. Decision-time vintage</strong><p>For each hourly delivery interval, use the latest WINDFOR record published at or before the selected Europe/London cut-off on the preceding decision date. Later revisions are excluded from that decision vintage.</p></div><div><strong>2. Actual alignment</strong><p>WINDFOR startTime is the hourly delivery-interval start and publishTime is the vintage timestamp. Compare it with the mean MW from both FUELHH WIND half-hours starting within that hour; reject an incomplete pair.</p></div><div><strong>3. Error definitions</strong><p>Error = forecast − actual. Positive bias means average over-forecast; negative bias means average under-forecast. MAE is the mean absolute MW error; RMSE weights larger misses more heavily; WAPE divides total absolute error by total actual generation.</p></div><div><strong>4. Rolling calibration</strong><p>For a decision on day d, the trailing error calibration includes only delivery dates strictly before d. A minimum of five completed days is required. The shortfall buffer is the empirical P90 of positive forecast-minus-actual error, not P90 absolute error.</p></div><div><strong>5. Scope boundary</strong><p>This January 2026 decision analysis covers delivery dates 2 January through 1 February. No demand, price, thermal availability or other generation datasets are used. The cut-off is a configurable assumption, not a claimed market gate closure.</p></div><div><strong>6. Reproducibility</strong><p>The API returns an analysis run ID and SHA-256 data fingerprint, source state, fetch timestamp, record counts, and explicit warnings. Cached and synthetic records are visibly distinguished from live data.</p></div></div></section>}

        <footer className="page-footer"><div><span className="footer-brand">WINDDESK</span><span>Wind procurement intelligence</span></div><div><span>Source: Elexon BMRS</span><a href="https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream" target="_blank" rel="noreferrer">WINDFOR <ExternalLink size={11}/></a><a href="https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream" target="_blank" rel="noreferrer">FUELHH <ExternalLink size={11}/></a></div><span className="footer-copyright">{data ? `RUN ${data.meta.analysisRunId} · SHA ${data.meta.dataSha256.slice(0, 12)}` : 'PILOT BUILD · 2026'}</span></footer>
      </div>
    </main>
  </div>
}

function decisionText(bias: number | null, wape: number | null) {
  if (bias == null || wape == null) return 'Not enough matched data to form an evidence-based reading. Check feed availability before using this view.'
  const direction = bias > 150 ? 'The forecast ran high on average' : bias < -150 ? 'The forecast ran low on average' : 'Average signed bias was relatively balanced'
  const severity = wape < 5 ? 'with low aggregate error.' : wape < 10 ? 'with a moderate aggregate error.' : 'with material forecast error.'
  return `${direction} (${bias > 0 ? '+' : ''}${fmtNum(bias)} MW), ${severity} Treat the observed error as a risk signal, not a direct reserve or trade quantity.`
}

function ForecastTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  return <div className="chart-tooltip"><span className="tooltip-time">{d?.startTime ? new Date(d.startTime).toLocaleString('en-GB', {weekday:'short',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',timeZone:'Europe/London'}) : label}</span><div><i className="tooltip-dot actual-dot"/>Actual <strong>{fmtMW(d?.actualMW)}</strong></div><div><i className="tooltip-dot forecast-dot"/>Forecast <strong>{fmtMW(d?.forecastMW)}</strong></div><div className="tooltip-divider"/><div>Error <strong>{d?.errorMW == null ? '—' : `${d.errorMW > 0 ? '+' : ''}${fmtMW(d.errorMW)}`}</strong></div><div>Forecast published <strong>{d?.publishTime ? fmtTime(d.publishTime) : '—'}</strong></div></div>
}
function HorizonTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  return <div className="chart-tooltip"><span className="tooltip-time">Forecast lead {label}</span><div>MAE <strong>{fmtMW(d?.maeMW)}</strong></div><div>RMSE <strong>{fmtMW(d?.rmseMW)}</strong></div><div>Signed bias <strong>{d?.biasMW == null ? '—' : `${d.biasMW > 0 ? '+' : ''}${fmtMW(d.biasMW)}`}</strong></div><div>Matched periods <strong>{fmtNum(d?.count)}</strong></div></div>
}
function HistogramTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  return <div className="chart-tooltip"><span className="tooltip-time">Signed error bin</span><div>Range <strong>{fmtMW(d?.lowerMW)} to {fmtMW(d?.upperMW)}</strong></div><div>Matched periods <strong>{fmtNum(d?.count)}</strong></div></div>
}
function ErrorTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return <div className="chart-tooltip"><span className="tooltip-time">{label}</span><div>Absolute error <strong>{fmtMW(payload[0]?.value)}</strong></div></div>
}

export default App
