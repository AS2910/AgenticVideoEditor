import { expect, test } from '@playwright/test'
import { Recorder, deleteAccount, dropOwner, freshEmail, inviteAs, joinByInvite, makeOwner, noErrorBanner, videoPlays, watchServer } from './helpers'

/** Journey 2, a Reviewer: an owner (made through the API) shares one project and invites
 *  them; they sign up through the invite email, see only that project, watch its video,
 *  cannot change it or open Billing, and delete their account. */
test('reviewer: invited, watches the shared video, changes nothing', async ({ page, baseURL }) => {
  const rec = new Recorder('reviewer')
  rec.watch(page)
  const server = watchServer(page)
  const owner = await makeOwner(page, baseURL!, { privateClip: true })
  const email = freshEmail('reviewer')
  try {
    await inviteAs(owner, email, 'reviewer')

    await test.step('sign up through the invite email, confirm, accept', async () => {
      await joinByInvite(page, email, 'Reviewer', rec)
      await noErrorBanner(page)
    })

    await test.step('Home shows only the shared project', async () => {
      const side = page.getByTestId('projects-side')
      await expect(side.getByRole('link', { name: /Sample: bhaji-cam ad/ })).toBeVisible()
      await expect(page.getByTestId('video-card').filter({ hasText: 'spring-ad.mp4' })).toBeVisible()
      await expect(page.getByTestId('video-card')).toHaveCount(2)              // the sample and the shared upload
      await expect(page.getByText('private-ad.mp4')).toHaveCount(0)           // never the owner's unshared video
      await rec.shot()
      await noErrorBanner(page)
    })

    await test.step('open the shared video: it plays', async () => {
      await page.getByTestId('video-card').filter({ hasText: 'spring-ad.mp4' }).click()
      await expect(page).toHaveURL(/#v\/[\w-]+$/)
      await expect(page.getByText('Get 20% off today only.').first()).toBeVisible()
      await videoPlays(page)
      await rec.shot()
    })

    await test.step('a change is refused, plainly', async () => {
      // There is no comment box for workspace Reviewers in the public profile (projects.review is
      // off), so watching is what a Reviewer does here; a change is refused in words.
      const box = page.getByLabel('Describe a change')
      await box.fill('Add a short line at the start')
      await box.press('Enter')
      await expect(page.getByText('As a Reviewer you can watch and comment.').first()).toBeVisible()
      await rec.shot()
    })

    await test.step('Billing is not offered, and says whose it is', async () => {
      await page.goto('/#settings')
      await expect(page.getByRole('navigation', { name: 'Settings sections' })).toBeVisible()
      await expect(page.getByRole('navigation', { name: 'Settings sections' }).getByRole('link', { name: 'Billing' })).toHaveCount(0)
      await page.goto('/#billing')
      await expect(page.getByTestId('billing-not-owner')).toContainText('Billing belongs to the workspace owner.')
      await expect(page.getByTestId('credits-card')).toHaveCount(0)
      await rec.shot()
      await noErrorBanner(page)
    })

    await test.step('delete the account; the owner and their videos stay', async () => {
      await deleteAccount(page, email, rec)
      const still = await owner.api.get('/api/videos')
      expect(still.status(), 'the owner is still signed in').toBe(200)
      expect(((await still.json()).videos ?? []).length, "the owner's videos are untouched").toBe(3)
    })
    expect(server.errors, 'no server errors behind the journey').toEqual([])
  } finally {
    await rec.finish()
    await dropOwner(owner)
  }
})
