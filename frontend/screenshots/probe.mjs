import { chromium } from 'playwright'
const variants = process.argv.slice(2)
const browser = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] })
for (const v of variants) {
  const page = await browser.newPage({ viewport: { width: 900, height: 600 } })
  const logs = []
  page.on('console', m => { if (m.type() === 'error' || /Lost|WebGL|THREE/i.test(m.text())) logs.push(m.text().slice(0, 160)) }); page.on('pageerror', e => logs.push('PAGEERROR ' + e.message.slice(0, 160)))
  await page.goto('http://localhost:5173/?' + v, { waitUntil: 'load' })
  await page.waitForTimeout(+(process.env.WAIT || 3000))
  const info = await page.evaluate(() => { const r = window.__r3f; if (!r) return 'no r3f'; const c = r.gl.getContext(); return `${c.drawingBufferWidth}x${c.drawingBufferHeight} calls=${r.gl.info.render.calls} lost=${c.isContextLost()}` })
  console.log(v.padEnd(40), info, logs.filter(l => !/502/.test(l)).join(' | '))
  await page.close()
}
await browser.close()
