// Generates the bundled placeholder clip for the Voltage editor.
// 1280x720, 30fps, 2.3s — matching the backend's canned transcript exactly.

import AVFoundation
import CoreGraphics
import CoreText
import Foundation

let W = 1280, H = 720, FPS: Int32 = 30
let words: [(String, Double, Double)] = [
    ("Get", 0.0, 0.4),
    ("20%", 0.4, 0.9),
    ("off", 0.9, 1.3),
    ("today", 1.3, 1.8),
    ("only", 1.8, 2.3),
]
let duration = 2.3
let frameCount = Int((duration * Double(FPS)).rounded())

// Voltage palette.
func rgb(_ hex: UInt32, _ a: CGFloat = 1) -> CGColor {
    CGColor(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255, alpha: a)
}
let bg = rgb(0x0A0E14), surface = rgb(0x121721), border = rgb(0x1E2733)
let electric = rgb(0x2E6BFF), cyan = rgb(0x22D3EE), muted = rgb(0x8B98A9)

let outPath = CommandLine.arguments[1]
let url = URL(fileURLWithPath: outPath)
try? FileManager.default.removeItem(at: url)

let writer = try AVAssetWriter(outputURL: url, fileType: .mp4)
let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: W,
    AVVideoHeightKey: H,
])
input.expectsMediaDataInRealTime = false
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
    kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32BGRA),
    kCVPixelBufferWidthKey as String: W,
    kCVPixelBufferHeightKey as String: H,
])
writer.add(input)
guard writer.startWriting() else { fatalError("startWriting failed: \(String(describing: writer.error))") }
writer.startSession(atSourceTime: .zero)

let bigFont = CTFontCreateWithName("Helvetica-Bold" as CFString, 68, nil)
let smallFont = CTFontCreateWithName("Helvetica" as CFString, 22, nil)

func line(_ s: String, _ font: CTFont, _ color: CGColor) -> CTLine {
    let attrs: [CFString: Any] = [
        kCTFontAttributeName: font,
        kCTForegroundColorAttributeName: color,
        kCTKernAttributeName: 1.0,
    ]
    let astr = CFAttributedStringCreate(nil, s as CFString, attrs as CFDictionary)!
    return CTLineCreateWithAttributedString(astr)
}
func width(_ l: CTLine) -> CGFloat { CGFloat(CTLineGetTypographicBounds(l, nil, nil, nil)) }

// Pre-measure the caption row so it stays centered and stable across frames.
let gap: CGFloat = 26
let measured = words.map { width(line($0.0, bigFont, muted)) }
let rowWidth = measured.reduce(0, +) + gap * CGFloat(words.count - 1)
let rowX = (CGFloat(W) - rowWidth) / 2
let rowY = CGFloat(H) / 2 - 24

let cs = CGColorSpaceCreateDeviceRGB()
let bitmapInfo = CGImageAlphaInfo.noneSkipFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue

for i in 0..<frameCount {
    let t = Double(i) / Double(FPS)

    var pb: CVPixelBuffer?
    CVPixelBufferPoolCreatePixelBuffer(nil, adaptor.pixelBufferPool!, &pb)
    guard let buffer = pb else { fatalError("no pixel buffer") }
    CVPixelBufferLockBaseAddress(buffer, [])
    let ctx = CGContext(data: CVPixelBufferGetBaseAddress(buffer), width: W, height: H,
                        bitsPerComponent: 8, bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
                        space: cs, bitmapInfo: bitmapInfo)!

    ctx.setFillColor(bg)
    ctx.fill(CGRect(x: 0, y: 0, width: W, height: H))

    // Subtle framing panel, so the clip reads as deliberate placeholder art.
    ctx.setFillColor(surface)
    ctx.fill(CGRect(x: 80, y: 110, width: CGFloat(W) - 160, height: CGFloat(H) - 220))
    ctx.setStrokeColor(border)
    ctx.setLineWidth(2)
    ctx.stroke(CGRect(x: 80, y: 110, width: CGFloat(W) - 160, height: CGFloat(H) - 220))

    // Caption row — the active word lights up electric blue with a glow.
    var x = rowX
    for (idx, w) in words.enumerated() {
        let active = t >= w.1 && t < w.2
        ctx.saveGState()
        if active {
            ctx.setShadow(offset: .zero, blur: 30, color: electric)
        }
        let l = line(w.0, bigFont, active ? electric : muted)
        ctx.textPosition = CGPoint(x: x, y: rowY)
        CTLineDraw(l, ctx)
        ctx.restoreGState()
        x += measured[idx] + gap
    }

    // Progress bar tracking the same 2.3s the transcript covers.
    let barY: CGFloat = 190, barX: CGFloat = 140, barW = CGFloat(W) - 280
    ctx.setFillColor(border)
    ctx.fill(CGRect(x: barX, y: barY, width: barW, height: 6))
    ctx.setFillColor(cyan)
    ctx.fill(CGRect(x: barX, y: barY, width: barW * CGFloat(t / duration), height: 6))

    let label = line("SAMPLE — placeholder clip, no real audio", smallFont, muted)
    ctx.textPosition = CGPoint(x: (CGFloat(W) - width(label)) / 2, y: barY - 46)
    CTLineDraw(label, ctx)

    CVPixelBufferUnlockBaseAddress(buffer, [])

    while !input.isReadyForMoreMediaData { usleep(2000) }
    adaptor.append(buffer, withPresentationTime: CMTime(value: Int64(i), timescale: FPS))
}

input.markAsFinished()
let sem = DispatchSemaphore(value: 0)
writer.finishWriting { sem.signal() }
sem.wait()

if writer.status != .completed { fatalError("write failed: \(String(describing: writer.error))") }
print("wrote \(outPath) — \(frameCount) frames")
