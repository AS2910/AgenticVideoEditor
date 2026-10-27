# Real messy clips: please add 20

The messy-audio eval (`evals/messy/`) runs on 20 variants we made from our own
fixtures. Made noise is cleaner than the real thing, so we also need real clips.
This folder is empty on purpose. Please drop in 20 short clips you have the
rights to use, recorded the way your users record.

## What to send

Each clip 10 to 60 seconds, someone talking, any common video or audio format.
Roughly this mix:

| How many | What it sounds like |
| --- | --- |
| 4 | Talking over music: a reel or an ad with a song or a beat under the voice |
| 4 | A busy place: cafe, street, shop, office chatter |
| 3 | An echoey room: a hall, a stairwell, a big bare room, far from the phone |
| 3 | Two people talking over each other: an interview, a podcast, an argument |
| 3 | Phone or call quality: a WhatsApp voice note, a Zoom or phone recording |
| 3 | Too loud: a mic too close, a shout, distorted or crackly sound |

Mixed languages are welcome (Hinglish especially).

## For each clip, a line in `clips.csv`

    file,kind,language,speakers,words
    cafe-01.mp4,noise,en,1,"exactly what is said, as you hear it"

`words` is what is really said, typed by a person. It is what transcription is
scored against, so it matters most. Leave it empty if you cannot, and we will
score timing and voice only.

## Privacy

Clips here are read by the eval only and never leave this machine, except that
the eval sends their sound to the transcription and voice vendors, as an upload
would. Do not add anything you would not upload to Voltage yourself. Clips are
not committed (this folder ignores everything but this README).
