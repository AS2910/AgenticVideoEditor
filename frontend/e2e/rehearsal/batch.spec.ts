import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { Recorder, SAMPLE_CLIP, deleteAccount, dismissTips, dismissTour, freshEmail, noErrorBanner, signUp, watchServer } from './helpers'

/** Journey 4, the batch (run 5 item 9): a new owner on the public profile, where
 *  `launch.batch_public` (on by default) turns on B1 to B3. Their sample project
 *  gets two more cuts of the ad; then one goal across all three videos from the
 *  example prompt (B1: the plan, the gate, Go, the board, Add all that passed),
 *  language versions of one video (B2), and every video exported with a preset as
 *  one zip and a share link (B3). Vendors are stand-ins (AVE_MOCK_VENDORS=1). */

const H = { 'X-Requested-With': 'voltage' }

async function uploadInto(page: Page, projectId: string, name: string): Promise<string> {
  const r = await page.request.post('/api/videos', {
    headers: H, timeout: 120_000,
    multipart: { file: { name, mimeType: 'video/mp4', buffer: readFileSync(SAMPLE_CLIP) }, consent: 'true', project_id: projectId },
  })
  if (!r.ok()) throw new Error(`upload ${name}: ${r.status()} ${await r.text()}`)
  return (await r.json()).video_id
}

test('batch: one change across a project, language versions, export them all', async ({ page }) => {
  const rec = new Recorder('batch')
  rec.watch(page)
  const server = watchServer(page)
  const email = freshEmail('batch')
  try {
    let projectId = ''
    await test.step('sign up; the public profile has phase B on', async () => {
      await signUp(page, email, rec)
      await expect(page).toHaveURL(/#home$/)
      await dismissTour(page)
      const flags = await (await page.request.get('/api/me/flags')).json()
      expect(flags.flags).toEqual(expect.arrayContaining(['launch.batch_public', 'projects.batch']))
      expect(flags.flags).not.toContain('projects.review')
      await noErrorBanner(page)
    })

    await test.step('the sample project gets two more cuts of the ad', async () => {
      const sample = page.getByTestId('projects-side').getByRole('link', { name: /Sample/ })
      await sample.click()
      await expect(page).toHaveURL(/#p\/[\w-]+$/)
      projectId = /#p\/([\w-]+)$/.exec(page.url())![1]
      await uploadInto(page, projectId, 'offer-reel.mp4')
      await uploadInto(page, projectId, 'offer-bumper.mp4')
      await page.reload()
      await expect(page.getByText('offer-reel.mp4').first()).toBeVisible({ timeout: 60_000 })
      await expect(page.getByText('offer-bumper.mp4').first()).toBeVisible()
      await noErrorBanner(page)
    })

    await test.step('B1: an example prompt, one plan, one gate, Go', async () => {
      const panel = page.getByTestId('batch')
      await panel.scrollIntoViewIfNeeded()
      await expect(panel.getByTestId('batch-how')).toContainText('Say the change once.')
      await panel.getByTestId('batch-examples').getByRole('button', { name: 'Make every offer line say 25% off' }).click()
      await expect(panel.getByLabel('What to change in every video')).toHaveValue('Make every offer line say 25% off')
      await expect(panel.getByTestId('batch-picker')).toContainText('3 of 3 videos picked')
      await rec.shot()
      await panel.getByRole('button', { name: 'Plan it for 3 videos' }).click()
      const gate = panel.getByTestId('batch-gate')
      await expect(gate.getByTestId('batch-totals')).toContainText('3 videos', { timeout: 60_000 })
      await expect(gate.getByTestId('batch-cap')).toContainText('You pay at most')
      await expect(gate.getByRole('button').last()).toHaveText('Go · 3 videos')
      await rec.shot()
      await gate.getByRole('button', { name: 'Go · 3 videos' }).click()
      await noErrorBanner(page)
    })

    await test.step('B1: the board says what is happening, then what finished', async () => {
      const board = page.getByTestId('batch-board')
      await expect(board).toBeVisible({ timeout: 60_000 })
      await expect(board.getByTestId('batch-summary')).not.toBeEmpty()
      await dismissTips(page)
      await rec.shot()
      await expect(board).toContainText('Batch finished', { timeout: 300_000 })
      await expect(board.getByTestId('batch-row')).toHaveCount(3)
      await expect(board.getByTestId('batch-summary')).toHaveText(/^Done\. /)
      const ready = board.locator('[data-testid=batch-row][data-state=ready]')
      await expect(ready.first()).toBeVisible()
      await expect(ready.first().getByTestId('batch-review')).toHaveAttribute('href', /#v\/[\w-]+$/)
      await rec.shot()
      const add = board.getByRole('button', { name: /^Add all that passed/ })
      await expect(board.getByRole('button').last()).toHaveText(/^Add all that passed/)
      await add.click()
      await expect(board.locator('[data-testid=batch-row][data-state=added]').first()).toBeVisible({ timeout: 120_000 })
      await expect(board.getByTestId('batch-summary')).toContainText('the changes added')
      await rec.shot()
      await noErrorBanner(page)
    })

    await test.step('B2: language versions of one video, stacked under it', async () => {
      await page.getByTestId('make-languages').first().click()
      const dialog = page.getByTestId('language-dialog')
      await expect(dialog.getByRole('checkbox', { name: /Hindi/ })).toBeVisible({ timeout: 60_000 })
      await dialog.getByRole('checkbox', { name: /Hindi/ }).check()
      await expect(dialog.getByTestId('language-gate')).toContainText('You pay at most', { timeout: 60_000 })
      await rec.shot()
      await dialog.getByRole('button', { name: 'Make 1 version' }).click()
      await expect(dialog).toBeHidden({ timeout: 60_000 })
      await expect(page.getByTestId('language-versions').getByRole('link', { name: /Open the Hindi version/ })).toBeVisible({ timeout: 60_000 })
      const board = page.getByTestId('batch-board')
      await expect(board).toContainText('Hindi', { timeout: 60_000 })
      await expect(board).toContainText('Batch finished', { timeout: 300_000 })
      await rec.shot()
      await noErrorBanner(page)
    })

    await test.step('B3: every video picked, one preset, one zip and a share link', async () => {
      const panel = page.getByTestId('batch-export')
      await panel.scrollIntoViewIfNeeded()
      const rows = panel.getByTestId('export-video')
      await expect(rows.first()).toBeVisible({ timeout: 60_000 })
      const n = await rows.count()
      expect(n).toBeGreaterThanOrEqual(3)
      for (let i = 0; i < n; i++) await expect(rows.nth(i).getByRole('checkbox')).toBeChecked()
      await expect(panel).not.toContainText('Not approved')
      await rec.shot()
      await panel.getByRole('button', { name: `Export ${n} files` }).click()
      const run = panel.getByTestId('export-run')
      await expect(run).toContainText(/Exporting|Export finished/, { timeout: 60_000 })
      await rec.shot()
      await expect(run).toContainText('Export finished', { timeout: 400_000 })
      await expect(run.locator('[data-testid=export-file][data-state=ready]')).toHaveCount(n)
      const zip = run.getByRole('link', { name: 'Download all (.zip)' })
      await expect(zip).toHaveAttribute('href', /\/exports\/[\w-]+\/zip(\?|$)/)
      const got = await page.request.get((await zip.getAttribute('href'))!)
      expect(got.status()).toBe(200)
      expect((await got.body()).subarray(0, 2).toString()).toBe('PK')
      await dismissTips(page)
      await run.getByRole('button', { name: 'Share link' }).click()
      await expect(run.getByRole('textbox', { name: 'Share link' })).toHaveValue(/#s\//)
      await rec.shot()
      await noErrorBanner(page)
    })

    await test.step('settings: delete the account', async () => {
      await deleteAccount(page, email, rec)
    })
    expect(server.errors, 'no server errors behind the journey').toEqual([])
  } finally {
    await rec.finish()
  }
})
