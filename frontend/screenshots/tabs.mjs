import { chromium } from 'playwright'
const browser = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] })
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
const errors = []
page.on('pageerror', e => errors.push('PAGEERROR ' + e.message.slice(0, 300)))
await page.goto('http://localhost:5173/?mock=1&speed=4', { waitUntil: 'load' })
await page.waitForTimeout(9000)
for (const t of ['SCHEMATIC', 'LAYERS', 'THERMAL', 'BOARD 3D']) {
  await page.getByRole('button', { name: t, exact: true }).click()
  await page.waitForTimeout(2200)
  await page.screenshot({ path: `screenshots/tab_${t.replace(/\W/g, '')}.png` })
}
console.log(errors.join('\n'))
await browser.close()
