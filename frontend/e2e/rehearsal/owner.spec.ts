import { expect, test } from '@playwright/test'
import { Recorder, SAMPLE_CLIP, addProposal, deleteAccount, dismissTour, freshEmail, noErrorBanner, signUp, turnToProposal, watchServer } from './helpers'

/** Journey 1, the owner: sign up, confirm, the sample, an upload, a turn, Add it,
 *  export, a test-mode top-up, an invite, and deleting the account. */
test('owner: sign up to delete account', async ({ page }) => {
  const rec = new Recorder('owner')
  rec.watch(page)
  const server = watchServer(page)
  const email = freshEmail('owner')
  const reviewer = freshEmail('invited')
  try {
    await test.step('sign up, accept the Terms, open the confirm link', async () => {
      await signUp(page, email, rec)
      await expect(page).toHaveURL(/#home$/)
      await expect(page.getByRole('heading', { name: /What should your next video/ })).toBeVisible()
      await dismissTour(page)
      await noErrorBanner(page)
    })

    await test.step('Home shows the sample project; open it and its video', async () => {
      const sample = page.getByTestId('projects-side').getByRole('link', { name: /Sample/ })
      await expect(sample).toBeVisible()
      await sample.click()
      await expect(page).toHaveURL(/#p\/[\w-]+$/)
      await page.getByText('sample-ad.mp4').first().click()
      await expect(page).toHaveURL(/#v\/[\w-]+$/)
      await expect(page.locator('video').first()).toBeAttached()
      await expect(page.getByTestId('voltage-pane')).toBeVisible()
      await expect(page.getByText('Get 20% off today only.').first()).toBeVisible()
      await rec.shot()
      await noErrorBanner(page)
    })

    await test.step('upload a short video; the editor opens on it', async () => {
      await page.goto('/#home')
      await dismissTour(page)
      await page.locator('input[type=file]').first().setInputFiles(SAMPLE_CLIP)
      await expect(page).toHaveURL(/#v\/[\w-]+$/, { timeout: 90_000 })
      await expect(page.getByLabel('Describe a change')).toBeVisible({ timeout: 60_000 })
      await expect(page.getByText('Get 20% off today only.').first()).toBeVisible({ timeout: 60_000 })
      await noErrorBanner(page)
    })

    await test.step('a turn: Voltage proposes a line; Add it', async () => {
      const proposal = await turnToProposal(page, 'Add a short line at the start', rec)
      await noErrorBanner(page)
      await addProposal(page, proposal, rec)
      await noErrorBanner(page)
    })

    await test.step('export: the render finishes and the download is offered', async () => {
      await page.locator('a[data-tour=export]').click()
      await expect(page).toHaveURL(/#v\/[\w-]+\/export$/)
      // A clear status the whole time: Rendering… then Rendered.
      await expect(page.locator('main [role=status]').first()).toHaveText(/Rendering…|Rendered|Reading the receipt…/)
      await rec.shot()
      await expect(page.locator('main [role=status]').first()).toHaveText(/Rendered/, { timeout: 180_000 })
      const download = page.getByRole('link', { name: 'Download MP4' })
      await expect(download).toHaveAttribute('href', /\S+/)
      await expect(page.getByTestId('render')).toBeVisible()
      await rec.shot()
      await noErrorBanner(page)
    })

    await test.step('billing: a top-up in test mode moves no money', async () => {
      await page.goto('/#billing')
      await expect(page.getByTestId('credits-card')).toBeVisible()
      await expect(page.getByText('Test mode: no card is asked for and no money moves.')).toBeVisible()
      await page.locator('section[aria-labelledby=topup-h] button').first().click()
      await expect(page.getByTestId('billing-status')).toContainText('Paid in test mode: no money moved.')
      await rec.shot()
      await noErrorBanner(page)
    })

    await test.step('members: invite a Reviewer, sharing the sample project', async () => {
      await page.goto('/#members')
      const form = page.getByTestId('invite-form')
      await form.getByLabel('Email').fill(reviewer)
      await form.getByRole('radio', { name: 'Reviewer' }).click()
      await page.getByTestId('share-picker').getByRole('checkbox').first().check()
      await rec.shot()
      await form.getByRole('button', { name: 'Send invite' }).click()
      await expect(page.getByText(`Invite sent to ${reviewer}.`)).toBeVisible()
      await expect(page.getByTestId('invites')).toContainText(reviewer)
      await rec.shot()
      await noErrorBanner(page)
    })

    await test.step('settings: delete the account; signed out; signing in again fails', async () => {
      await deleteAccount(page, email, rec)
    })
    expect(server.errors, 'no server errors behind the journey').toEqual([])
  } finally {
    await rec.finish()
  }
})
