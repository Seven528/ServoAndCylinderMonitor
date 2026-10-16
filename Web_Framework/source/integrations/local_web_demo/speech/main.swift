import AVFAudio
import Foundation
import Speech

func emit(_ value: [String: Any], code: Int32 = 0) -> Never {
    let data = (try? JSONSerialization.data(withJSONObject: value)) ?? Data("{}".utf8)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
    exit(code)
}
func fail(_ code: String, _ message: String) -> Never {
    emit(["status": "error", "code": code, "message": String(message.prefix(400)), "on_device": true], code: 1)
}

@available(macOS 26.0, *)
func run() async {
    let arguments = CommandLine.arguments
    guard let locale = await DictationTranscriber.supportedLocale(equivalentTo: Locale(identifier: "zh-CN")) else {
        fail("local_model_unavailable", "当前系统不支持中文本机转写；不会使用在线识别。")
    }
    let transcriber = DictationTranscriber(locale: locale, preset: .shortDictation)
    let status = await AssetInventory.status(forModules: [transcriber])
    if arguments.count == 2 && arguments[1] == "--probe" {
        emit(["available": true, "model_ready": status == .installed,
              "model_status": String(describing: status), "language": "zh-CN",
              "engine": "macos-on-device", "implementation": "SpeechAnalyzer.DictationTranscriber"])
    }
    if arguments.count == 2 && arguments[1] == "--prepare" {
        do {
            // Keep only this explicitly requested locale reserved for this helper.
            // Never release or replace another application's reserved languages.
            try await AssetInventory.reserve(locale: locale)
            if let installation = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
                try await installation.downloadAndInstall()
            }
            guard await AssetInventory.status(forModules: [transcriber]) == .installed else {
                fail("local_model_unavailable", "中文离线模型尚未准备完成，未启动录音。")
            }
            emit(["status": "ok", "on_device": true, "model_ready": true])
        } catch {
            fail("model_install_failed", "中文离线模型准备失败：" + error.localizedDescription)
        }
    }
    guard arguments.count == 3 && arguments[1] == "--transcribe" else {
        fail("invalid_arguments", "使用 --probe、--prepare 或 --transcribe <audio.wav>")
    }
    guard status == .installed else {
        fail("local_model_unavailable", "需要先准备中文离线模型；录音未送往在线识别。")
    }
    let url = URL(fileURLWithPath: arguments[2])
    guard arguments[2].hasPrefix("/"), url.pathExtension == "wav",
          let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
          let size = attributes[.size] as? NSNumber, size.intValue > 44, size.intValue <= 2 * 1024 * 1024 else {
        fail("invalid_audio", "只接受不超过 2 MiB 的本机 WAV 录音。")
    }
    let analyzer = SpeechAnalyzer(modules: [transcriber])
    let results = Task { () throws -> String in
        var text = ""
        for try await result in transcriber.results {
            text += String(result.text.characters)
            if text.count > 8000 { text = String(text.prefix(8000)) }
        }
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    do {
        let audio = try AVAudioFile(forReading: url)
        guard audio.fileFormat.channelCount == 1,
              audio.fileFormat.sampleRate == 16000,
              audio.length > 0, audio.length <= 960000 else {
            fail("invalid_audio", "需要 60 秒以内的 16kHz 单声道录音。")
        }
        if let end = try await analyzer.analyzeSequence(from: audio) {
            try await analyzer.finalizeAndFinish(through: end)
        } else {
            await analyzer.cancelAndFinishNow()
        }
        let text = try await results.value
        guard !text.isEmpty else { fail("no_speech", "没有识别到清晰语音，请重试。") }
        emit(["status": "ok", "text": text, "on_device": true])
    } catch {
        results.cancel()
        await analyzer.cancelAndFinishNow()
        fail("local_recognition_failed", "本机转写失败：" + error.localizedDescription)
    }
}

let timeout: TimeInterval = CommandLine.arguments.contains("--prepare") ? 240 : 70
DispatchQueue.global().asyncAfter(deadline: .now() + timeout) {
    fail("local_timeout", "本机语音操作超时，已停止；不会回退在线识别。")
}
if #available(macOS 26.0, *) {
    Task { await run() }
    RunLoop.main.run()
} else {
    if CommandLine.arguments.contains("--probe") {
        emit(["available": false, "model_ready": false, "engine": "macos-on-device",
              "message": "本机转写需要 macOS 26 或更新版本。"])
    }
    fail("unsupported_os", "本机转写需要 macOS 26 或更新版本；在线回退已禁用。")
}
