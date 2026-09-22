// Run against a frontend-only preview: node screenshots/demo-replay.mjs http://127.0.0.1:4173
import assert from 'node:assert/strict'
import { chromium } from 'playwright'

const base = process.argv[2] ?? 'http://127.0.0.1:4173'
const manifestResponse = await fetch(`${base}/demo/index.json`)
assert.equal(manifestResponse.status, 200)
const demos = await manifestResponse.json()
assert.equal(demos.length, 4)
const browser = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] })
try {
  const context = await browser.newContext({ viewport: { width: 1500, height: 940 } })
  // Offline backend is intentional. No model or live design request may escape.
  await context.route('**/api/**', route => route.abort())
  const page = await context.newPage()
  const errors = [], sockets = [], backendRuns = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('websocket', socket => sockets.push(socket.url()))
  page.on('request', request => {
    if (/\/api\/runs\/|\/ws\//.test(request.url())) backendRuns.push(request.url())
  })
  for (const demo of demos) {
    await page.goto(`${base}/?speed=5`, { waitUntil: 'load' })
    await page.waitForFunction(() => document.querySelectorAll('.demo-card').length === 4)
    await page.locator('.demo-card').filter({ hasText: demo.name }).click()
    await page.waitForFunction(() => ['done', 'error'].includes(window.__etch?.getState().phase), undefined, { timeout: 180_000 })
    const state = await page.evaluate(() => {
      const s = window.__etch.getState()
      return { phase: s.phase, runId: s.runId, mode: s.mode, stats: s.stats, power: s.power,
        drc: s.drc, error: s.error, toast: s.toast, stages: s.stageStates,
        traces: s.traces.length, vias: s.vias.length, failedNets: s.failedNets,
        remainingAirwires: s.ratsnest.filter(line => s.failedNets.includes(line[4]) || !s.routedNets.includes(line[4])).length,
        backend: s.runInfo.backend, artifacts: s.artifacts }
    })
    assert.equal(state.phase, 'done', `${demo.name}: ${state.error}`)
    assert.equal(state.runId, demo.run_id)
    assert.equal(state.mode, 'replay')
    assert.equal(state.backend, 'offline-refresh')
    assert.equal(state.error, null)
    assert.equal(state.toast, null)
    assert.deepEqual(state.failedNets, [])
    assert.equal(state.remainingAirwires, 0)
    assert.deepEqual(state.stats, demo.stats)
    assert.equal(state.traces, demo.stats.traces)
    assert.equal(state.vias, demo.stats.vias)
    assert.ok(Object.values(state.stages).every(stage => stage === 'done'))
    assert.equal(state.drc.errors, 0)
    assert.equal(state.drc.warnings, 0)
    assert.ok(state.power.length > 0 && state.power.every(rail => rail.width_ok === true && rail.drop_ok === true))
    assert.equal(await page.locator('td[title="Width target not checked in this recording"]').count(), 0)
    assert.ok(await page.locator('.rails').isVisible())
    const kicad = state.artifacts.kicad
    assert.equal(kicad.drc_passed, true)
    assert.equal(kicad.violations + kicad.warnings + kicad.unconnected, 0)
    for (const key of ['zip_url', 'gerber_zip_url', 'render_url']) {
      const path = state.artifacts[key]
      assert.ok(path.startsWith(`/demo/${demo.run_id}/`), `${key} depends on backend`)
      const response = await context.request.get(`${base}${path}`)
      assert.equal(response.status(), 200)
      const data = await response.body()
      assert.ok(data.length > 1000)
      assert.equal(data.subarray(0, key === 'render_url' ? 8 : 4).toString('hex'),
        key === 'render_url' ? '89504e470d0a1a0a' : '504b0304')
    }
    await page.locator('img[alt="KiCad render"]').waitFor()
    await page.waitForFunction(() => {
      const image = document.querySelector('img[alt="KiCad render"]')
      return image?.complete && image.naturalWidth > 0
    })
    // Exercise both actual download buttons, not only their hrefs.
    for (const link of await page.locator('a.download').all()) {
      const [download] = await Promise.all([page.waitForEvent('download'), link.click()])
      assert.equal(await download.failure(), null)
    }
    assert.deepEqual(errors, [])
    assert.deepEqual(sockets, [])
    assert.deepEqual(backendRuns, [])
    await page.screenshot({ path: `screenshots/demo-${demo.name.toLowerCase()}.png` })
    console.log(`${demo.name}: offline replay, copper counts, width checks, render and both downloads PASS`)
  }
} finally {
  await browser.close()
}
