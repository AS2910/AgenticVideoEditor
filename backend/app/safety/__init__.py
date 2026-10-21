"""G6: trust and safety behind interfaces, each with a fake provider.

    liveness      LivenessProvider: the speaker reads a random sentence aloud
                  before their voice is cloned; the attempt is stored
    figures       PublicFigureCheck: cloning a known public figure is refused
    provenance    Watermarker + C2PASigner: an invisible marker in each
                  export's metadata and a signed C2PA-style manifest beside it

None of the fakes talks to a network or holds a real key; what a real one
needs is in SETUP_NEEDED.md.
"""
