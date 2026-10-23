import { expect, test } from '@playwright/test'
import { Recorder, addProposal, deleteAccount, dropOwner, freshEmail, inviteAs, joinByInvite, makeOwner, noErrorBanner, turnToProposal, videoPlays, watchServer } from './helpers'

/** Journey 3, an Editor: invited by an owner (made through the API), they sign up through
 *  the invite email, open the owner's video, take a turn and add the proposal, are not
 *  given Billing or Members, and delete their account (the owner's stays). */
test('editor: invited, takes a turn on the owner video, adds it', async ({ page, baseURL }) => {
  const rec = new Recorder('editor')
  rec.watch(page)
  const server = watchServer(page)
  const owner = await makeOwner(page, baseURL!)
  const email = freshEmail('editor')
  try {
    await inviteAs(owner, email, 'editor')

    await test.step('sign up through the invite email, confirm, accept', async () => {
      await joinByInvite(page, email, 'Editor', rec)
      await noErrorBanner(page)
    })

    await test.step("open the owner's video", async () => {
      const card = page.getByTestId('video-card').filter({ hasText: 'spring-ad.mp4' })
      await expect(card).toBeVisible()
      await card.click()
      await expect(page).toHaveURL(new RegExp(`#v/${owner.videoId}$`))
      await expect(page.getByText('Get 20% off today only.').first()).toBeVisible()
      await videoPlays(page)
      await rec.shot()
      await noErrorBanner(page)
    })

    await test.step('a turn: Voltage proposes a line; Add it', async () => {
      const proposal = await turnToProposal(page, 'Add a short line at the start', rec)
      await noErrorBanner(page)
      await addProposal(page, proposal, rec)
      await noErrorBanner(page)
      // The owner sees the Editor's line in their video.
      const plan = await owner.api.get(`/api/videos/${owner.videoId}`)
      expect(plan.status()).toBe(200)
      expect(await plan.text()).toContain('Fresh every morning.')
    })

    await test.step('Billing and Members are the owner\'s', async () => {
      await page.goto('/#settings')
      const nav = page.getByRole('navigation', { name: 'Settings sections' })
      await expect(nav).toBeVisible()
      await expect(nav.getByRole('link', { name: 'Billing' })).toHaveCount(0)
      await page.goto('/#billing')
      await expect(page.getByTestId('billing-not-owner')).toContainText('Billing belongs to the workspace owner.')
      await noErrorBanner(page)
      await page.goto('/#members')
      await expect(page.getByTestId('members-not-owner')).toContainText('Editor')
      await expect(page.getByTestId('invite-form')).toHaveCount(0)
      await rec.shot()
      await noErrorBanner(page)
    })

    await test.step('delete the account; the owner and their videos stay', async () => {
      await deleteAccount(page, email, rec)
      const still = await owner.api.get('/api/videos')
      expect(still.status(), 'the owner is still signed in').toBe(200)
      expect(((await still.json()).videos ?? []).length, "the owner's videos are untouched").toBe(2)
    })
    expect(server.errors, 'no server errors behind the journey').toEqual([])
  } finally {
    await rec.finish()
    await dropOwner(owner)
  }
})
