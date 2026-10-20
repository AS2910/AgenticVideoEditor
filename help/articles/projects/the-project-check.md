---
title: The project check
section: Projects
order: 1103
---
The project check reads every video in a project, as each one says it now (its lines as shot and the lines you added), and lists where they do not agree. It makes no new audio.

What it looks for: prices, percentages, dates, phone numbers and web addresses that differ between videos; offer and product names that differ (the text pass); the same role, such as "Narrator", voiced by different voices; a project word that a take did not say the project's way; a banned word said, or a required line missing; and videos whose loudness is more than 2 LU apart. Loudness comes from each video's latest render; a video with no render yet is named and skipped.

Cost: the rule checks are free. The text pass is one short Claude read over the transcripts, priced before you run it ("about $0.01"), and the cost shows in Usage under the project. Choose Rules only to run the free checks alone; without a Claude key they are all that runs.

After a brief change the free checks run again on their own, so the Issues panel stays current.

Each issue names the videos and the times. Select a time to open that video there. Fix in this video asks Voltage to fix it in that video, as a normal turn. Fix in all does the same in every video the issue names, one after another. Ignore hides the issue until the words it was found in change; then it comes back.
