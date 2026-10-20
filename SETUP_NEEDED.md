# What you need to set up

- B3/F6 share links: set `AVE_PUBLIC_URL` to the address people open the app at (default `http://localhost:5173`), or links will point at localhost. Optional: `AVE_SHARE_SECRET` (a long random string) to sign links; without it one is generated into the data dir (`share_secret`) on first start; keep that file if you move the data dir, or every link stops working.
- B3 captions in non-Latin scripts (Hindi, Tamil for B2): the installed ffmpeg has no libass. Install an ffmpeg built with libass (for example `brew install homebrew-ffmpeg/ffmpeg/ffmpeg`) and the subtitles filter is used automatically; until then captions are drawn with OpenCV (Latin letters only).
